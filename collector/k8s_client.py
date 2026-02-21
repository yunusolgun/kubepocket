# collector/k8s_client.py
from kubernetes import client, config
from kubernetes.client.rest import ApiException
import os
from datetime import datetime
import time

class K8sClient:
    def __init__(self, context=None):
        """Kubernetes client'ı başlat"""
        try:
            # Önce in-cluster config dene (production)
            config.load_incluster_config()
            print("✅ In-cluster config yüklendi")
        except:
            try:
                # Yoksa kubeconfig dene (development)
                config.load_kube_config(context=context)
                print(f"✅ Kubeconfig yüklendi (context: {context or 'default'})")
            except Exception as e:
                print(f"❌ Kubernetes bağlantı hatası: {e}")
                raise
        
        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
        
        # Metrics API varsa kullan (opsiyonel)
        try:
            self.metrics_api = client.CustomObjectsApi()
            self.has_metrics = True
        except:
            self.has_metrics = False
            print("⚠️ Metrics API bulunamadı, sadece temel metrikler toplanacak")
    
    def parse_cpu(self, cpu_str):
        """CPU string'ini (100m, 1, 500m) float core değerine çevir"""
        if not cpu_str:
            return 0
        if cpu_str.endswith('m'):
            return float(cpu_str[:-1]) / 1000
        return float(cpu_str)
    
    def parse_memory(self, mem_str):
        """Memory string'ini (128Mi, 1Gi, 512Ki) Gi cinsine çevir"""
        if not mem_str:
            return 0
        
        multipliers = {
            'Ki': 1/1024/1024,  # Ki to Gi
            'Mi': 1/1024,        # Mi to Gi
            'Gi': 1,
            'Ti': 1024
        }
        
        for unit, multiplier in multipliers.items():
            if mem_str.endswith(unit):
                return float(mem_str[:-2]) * multiplier
        
        # Varsayılan byte ise
        return float(mem_str) / (1024**3)
    
    def collect_all_metrics(self):
        """Tüm namespace'lerden metrik topla"""
        try:
            # Tüm namespace'leri getir
            namespaces = self.core_v1.list_namespace()
            results = []
            
            for ns in namespaces.items:
                ns_name = ns.metadata.name
                
                # Sistem namespace'lerini atla (opsiyonel)
                if ns_name.startswith(('kube-', 'minikube', 'kubernetes')):
                    continue
                
                print(f"📊 {ns_name} kontrol ediliyor...")
                
                # Namespace'deki podları getir
                pods = self.core_v1.list_namespaced_pod(ns_name)
                
                namespace_data = {
                    'namespace': ns_name,
                    'timestamp': datetime.utcnow().isoformat(),
                    'pods': [],
                    'total_restarts': 0,
                    'total_cpu_request': 0,
                    'total_memory_request': 0,
                    'total_cpu_limit': 0,
                    'total_memory_limit': 0,
                    'pod_count': len(pods.items),
                    'running_pods': 0,
                    'pending_pods': 0,
                    'failed_pods': 0
                }
                
                for pod in pods.items:
                    pod_info = self._process_pod(pod)
                    namespace_data['pods'].append(pod_info)
                    
                    # Toplamları güncelle
                    namespace_data['total_restarts'] += pod_info['restart_count']
                    namespace_data['total_cpu_request'] += pod_info['cpu_request']
                    namespace_data['total_memory_request'] += pod_info['memory_request']
                    namespace_data['total_cpu_limit'] += pod_info['cpu_limit']
                    namespace_data['total_memory_limit'] += pod_info['memory_limit']
                    
                    # Pod durumları
                    if pod_info['status'] == 'Running':
                        namespace_data['running_pods'] += 1
                    elif pod_info['status'] == 'Pending':
                        namespace_data['pending_pods'] += 1
                    elif pod_info['status'] == 'Failed':
                        namespace_data['failed_pods'] += 1
                
                results.append(namespace_data)
                
                # Özet yazdır
                print(f"   → {namespace_data['pod_count']} pod, "
                      f"{namespace_data['total_cpu_request']:.2f} CPU, "
                      f"{namespace_data['total_memory_request']:.2f} Gi, "
                      f"{namespace_data['total_restarts']} restart")
            
            return results
            
        except ApiException as e:
            print(f"❌ API Hatası: {e}")
            return []
    
    def _process_pod(self, pod):
        """Tek bir pod'un detaylarını işle"""
        
        # Restart sayısı
        restart_count = 0
        if pod.status.container_statuses:
            restart_count = sum(cs.restart_count for cs in pod.status.container_statuses)
        
        # Resource hesaplamaları
        cpu_request = 0
        memory_request = 0
        cpu_limit = 0
        memory_limit = 0
        
        for container in pod.spec.containers:
            if container.resources.requests:
                cpu_req = container.resources.requests.get('cpu', '0')
                mem_req = container.resources.requests.get('memory', '0')
                cpu_request += self.parse_cpu(cpu_req)
                memory_request += self.parse_memory(mem_req)
            
            if container.resources.limits:
                cpu_lim = container.resources.limits.get('cpu', '0')
                mem_lim = container.resources.limits.get('memory', '0')
                cpu_limit += self.parse_cpu(cpu_lim)
                memory_limit += self.parse_memory(mem_lim)
        
        # Pod durumu
        status = pod.status.phase
        
        # Yaş (creation time'dan bu yana)
        age = datetime.utcnow() - pod.metadata.creation_timestamp.replace(tzinfo=None)
        
        return {
            'name': pod.metadata.name,
            'namespace': pod.metadata.namespace,
            'status': status,
            'restart_count': restart_count,
            'cpu_request': cpu_request,
            'memory_request': memory_request,
            'cpu_limit': cpu_limit,
            'memory_limit': memory_limit,
            'node_name': pod.spec.node_name,
            'age_hours': age.total_seconds() / 3600,
            'created_at': pod.metadata.creation_timestamp.isoformat()
        }
    
    def get_high_restart_pods(self, threshold=5):
        """Belirli bir eşikten fazla restart alan podları getir"""
        all_metrics = self.collect_all_metrics()
        problematic = []
        
        for ns_data in all_metrics:
            for pod in ns_data['pods']:
                if pod['restart_count'] >= threshold:
                    problematic.append({
                        'namespace': ns_data['namespace'],
                        'pod_name': pod['name'],
                        'restarts': pod['restart_count'],
                        'status': pod['status']
                    })
        
        return problematic

# Test fonksiyonu
if __name__ == "__main__":
    print("🚀 Kubernetes client test ediliyor...")
    
    # Client'ı başlat
    client = K8sClient()
    
    # Tüm metrikleri topla
    print("\n📊 Metrikler toplanıyor...")
    metrics = client.collect_all_metrics()
    
    print(f"\n✅ {len(metrics)} namespace bulundu")
    
    # Yüksek restart alan podları kontrol et
    problematic = client.get_high_restart_pods(threshold=3)
    if problematic:
        print(f"\n⚠️ Yüksek restart alan podlar:")
        for p in problematic:
            print(f"   - {p['namespace']}/{p['pod_name']}: {p['restarts']} restart")
    
    print("\n✅ Test tamamlandı!")
