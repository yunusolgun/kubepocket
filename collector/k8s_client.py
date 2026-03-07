# collector/k8s_client.py
from kubernetes import client, config
from kubernetes.client.rest import ApiException
import os
from datetime import datetime
import time


class K8sClient:
    def __init__(self, context=None):
        try:
            config.load_incluster_config()
            print("✅ In-cluster config yüklendi")
        except:
            try:
                config.load_kube_config(context=context)
                print(
                    f"✅ Kubeconfig yüklendi (context: {context or 'default'})")
            except Exception as e:
                print(f"❌ Kubernetes bağlantı hatası: {e}")
                raise

        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()

        try:
            self.metrics_api = client.CustomObjectsApi()
            self.has_metrics = True
        except:
            self.has_metrics = False
            print("⚠️ Metrics API bulunamadı")

    def parse_cpu(self, cpu_str):
        if not cpu_str:
            return 0
        if cpu_str.endswith('n'):      # nanoseconds — Metrics Server kullanır
            return float(cpu_str[:-1]) / 1_000_000_000
        if cpu_str.endswith('u'):      # microseconds
            return float(cpu_str[:-1]) / 1_000_000
        if cpu_str.endswith('m'):      # millicores
            return float(cpu_str[:-1]) / 1000
        return float(cpu_str)

    def parse_memory(self, mem_str):
        if not mem_str:
            return 0
        multipliers = {
            'Ki': 1/1024/1024,
            'Mi': 1/1024,
            'Gi': 1,
            'Ti': 1024
        }
        for unit, multiplier in multipliers.items():
            if mem_str.endswith(unit):
                return float(mem_str[:-2]) * multiplier
        return float(mem_str) / (1024**3)

    def collect_all_metrics(self):
        try:
            namespaces = self.core_v1.list_namespace()
            results = []

            for ns in namespaces.items:
                ns_name = ns.metadata.name
                if ns_name.startswith(('kube-', 'minikube', 'kubernetes')):
                    continue

                print(f"📊 {ns_name} kontrol ediliyor...")
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
                    namespace_data['total_restarts'] += pod_info['restart_count']
                    namespace_data['total_cpu_request'] += pod_info['cpu_request']
                    namespace_data['total_memory_request'] += pod_info['memory_request']
                    namespace_data['total_cpu_limit'] += pod_info['cpu_limit']
                    namespace_data['total_memory_limit'] += pod_info['memory_limit']

                    if pod_info['status'] == 'Running':
                        namespace_data['running_pods'] += 1
                    elif pod_info['status'] == 'Pending':
                        namespace_data['pending_pods'] += 1
                    elif pod_info['status'] == 'Failed':
                        namespace_data['failed_pods'] += 1

                results.append(namespace_data)
                print(f"   → {namespace_data['pod_count']} pod, "
                      f"{namespace_data['total_cpu_request']:.2f} CPU, "
                      f"{namespace_data['total_memory_request']:.2f} Gi, "
                      f"{namespace_data['total_restarts']} restart")

            return results

        except ApiException as e:
            print(f"❌ API Hatası: {e}")
            return []

    def _process_pod(self, pod):
        restart_count = 0
        if pod.status.container_statuses:
            restart_count = sum(
                cs.restart_count for cs in pod.status.container_statuses)

        cpu_request = 0
        memory_request = 0
        cpu_limit = 0
        memory_limit = 0

        for container in pod.spec.containers:
            if container.resources.requests:
                cpu_request += self.parse_cpu(
                    container.resources.requests.get('cpu', '0'))
                memory_request += self.parse_memory(
                    container.resources.requests.get('memory', '0'))
            if container.resources.limits:
                cpu_limit += self.parse_cpu(
                    container.resources.limits.get('cpu', '0'))
                memory_limit += self.parse_memory(
                    container.resources.limits.get('memory', '0'))

        status = pod.status.phase
        age = datetime.utcnow() - pod.metadata.creation_timestamp.replace(tzinfo=None)

        # Startup latency: creationTimestamp -> ilk container'ın startedAt
        # Sadece pod 1 saatten gençse anlamlı (restart'ta startedAt yanıltıcı olur)
        startup_seconds = None
        try:
            if pod.status.container_statuses and age.total_seconds() < 3600:
                for cs in pod.status.container_statuses:
                    if cs.state and cs.state.running and cs.state.running.started_at:
                        started_at = cs.state.running.started_at.replace(
                            tzinfo=None)
                        created_at = pod.metadata.creation_timestamp.replace(
                            tzinfo=None)
                        diff = (started_at - created_at).total_seconds()
                        if 0 < diff < 600:  # max 10 dakika — makul startup süresi
                            startup_seconds = round(diff, 1)
                        break
        except Exception:
            pass

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
            'created_at': pod.metadata.creation_timestamp.isoformat(),
            'startup_seconds': startup_seconds,
        }

    def get_high_restart_pods(self, threshold=5):
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

    def get_actual_usage(self, namespace):
        """Metrics Server'dan gerçek CPU/memory kullanımını çek."""
        if not self.has_metrics:
            return {}
        try:
            pod_metrics = self.metrics_api.list_namespaced_custom_object(
                group='metrics.k8s.io',
                version='v1beta1',
                namespace=namespace,
                plural='pods'
            )
            usage = {}
            for item in pod_metrics.get('items', []):
                pod_name = item['metadata']['name']
                cpu_total = 0
                mem_total = 0
                for container in item.get('containers', []):
                    cpu_total += self.parse_cpu(
                        container['usage'].get('cpu', '0'))
                    mem_total += self.parse_memory(
                        container['usage'].get('memory', '0'))
                usage[pod_name] = {
                    'cpu_actual': round(cpu_total, 4),
                    'memory_actual_gib': round(mem_total, 4),
                }
            return usage
        except Exception:
            return {}

    def collect_node_metrics(self):
        """Node bazlı kapasite, allocatable ve pod dağılımı."""
        try:
            nodes = self.core_v1.list_node()
            all_pods = self.core_v1.list_pod_for_all_namespaces()

            # Pod -> node mapping
            node_pods = {}
            node_cpu_requested = {}
            node_mem_requested = {}
            for pod in all_pods.items:
                node = pod.spec.node_name
                if not node:
                    continue
                node_pods[node] = node_pods.get(node, 0) + 1
                for container in pod.spec.containers:
                    if container.resources and container.resources.requests:
                        node_cpu_requested[node] = node_cpu_requested.get(node, 0) + \
                            self.parse_cpu(
                                container.resources.requests.get('cpu', '0'))
                        node_mem_requested[node] = node_mem_requested.get(node, 0) + \
                            self.parse_memory(
                                container.resources.requests.get('memory', '0'))

            results = []
            for node in nodes.items:
                name = node.metadata.name
                cap = node.status.capacity
                alloc = node.status.allocatable

                cpu_capacity = self.parse_cpu(cap.get('cpu', '0'))
                cpu_allocatable = self.parse_cpu(alloc.get('cpu', '0'))
                mem_capacity = self.parse_memory(cap.get('memory', '0'))
                mem_allocatable = self.parse_memory(alloc.get('memory', '0'))
                pods_capacity = int(cap.get('pods', 110))
                pods_running = node_pods.get(name, 0)
                cpu_requested = round(node_cpu_requested.get(name, 0), 4)
                mem_requested = round(node_mem_requested.get(name, 0), 4)

                # Actual usage from Metrics Server
                cpu_actual = None
                mem_actual = None
                try:
                    node_metrics = self.metrics_api.get_cluster_custom_object(
                        group='metrics.k8s.io',
                        version='v1beta1',
                        plural='nodes',
                        name=name
                    )
                    cpu_actual = round(self.parse_cpu(
                        node_metrics['usage']['cpu']), 4)
                    mem_actual = round(self.parse_memory(
                        node_metrics['usage']['memory']), 4)
                except Exception:
                    pass

                # Conditions
                conditions = {}
                for cond in (node.status.conditions or []):
                    conditions[cond.type] = cond.status

                ready = conditions.get('Ready', 'Unknown') == 'True'

                results.append({
                    'name': name,
                    'ready': ready,
                    'cpu_capacity': cpu_capacity,
                    'cpu_allocatable': cpu_allocatable,
                    'cpu_requested': cpu_requested,
                    'cpu_actual': cpu_actual,
                    'cpu_request_pct': round(cpu_requested / cpu_allocatable * 100, 1) if cpu_allocatable > 0 else 0,
                    'cpu_actual_pct': round(cpu_actual / cpu_allocatable * 100, 1) if cpu_actual and cpu_allocatable > 0 else None,
                    'mem_capacity_gib': mem_capacity,
                    'mem_allocatable_gib': mem_allocatable,
                    'mem_requested_gib': mem_requested,
                    'mem_actual_gib': mem_actual,
                    'mem_request_pct': round(mem_requested / mem_allocatable * 100, 1) if mem_allocatable > 0 else 0,
                    'mem_actual_pct': round(mem_actual / mem_allocatable * 100, 1) if mem_actual and mem_allocatable > 0 else None,
                    'pods_running': pods_running,
                    'pods_capacity': pods_capacity,
                    'pods_pct': round(pods_running / pods_capacity * 100, 1) if pods_capacity > 0 else 0,
                    'conditions': conditions,
                })

            return results

        except Exception as e:
            print(f"❌ Node metrics hatası: {e}")
            return []

    def collect_all_metrics_with_usage(self):
        """collect_all_metrics() + Metrics Server'dan gerçek kullanım."""
        metrics = self.collect_all_metrics()

        for ns_data in metrics:
            actual = self.get_actual_usage(ns_data['namespace'])
            for pod in ns_data['pods']:
                usage = actual.get(pod['name'], {})
                cpu_req = pod.get('cpu_request', 0)
                mem_req = pod.get('memory_request', 0)
                cpu_act = usage.get('cpu_actual')
                mem_act = usage.get('memory_actual_gib')

                pod['cpu_actual'] = cpu_act
                pod['memory_actual_gib'] = mem_act
                pod['cpu_efficiency_pct'] = round(
                    cpu_act / cpu_req * 100, 1) if cpu_act is not None and cpu_req > 0 else None
                pod['memory_efficiency_pct'] = round(
                    mem_act / mem_req * 100, 1) if mem_act is not None and mem_req > 0 else None

        return metrics
