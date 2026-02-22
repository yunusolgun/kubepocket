# collector/cost.py
"""
Göreceli maliyet ve waste tespiti.

Gerçek $ fiyatı yok — cluster içi oransal analiz yapılır:
- Namespace'in cluster toplamına oranı (%)
- Pod başına kaynak verimliliği (waste score)
- Boşa giden kaynak miktarı (idle resource)
"""
from typing import List, Dict, Any


def calculate_relative_cost(metrics: list) -> Dict[str, Any]:
    """
    Her namespace'in cluster toplamına oranını hesapla.
    
    metrics: get_latest_per_namespace() sonucu
    """
    if not metrics:
        return {}

    total_cpu = sum(m.total_cpu for m in metrics)
    total_memory = sum(m.total_memory for m in metrics)

    namespaces = []
    for m in metrics:
        cpu_pct = (m.total_cpu / total_cpu * 100) if total_cpu > 0 else 0
        mem_pct = (m.total_memory / total_memory * 100) if total_memory > 0 else 0

        # Ağırlıklı maliyet oranı — CPU ve memory eşit ağırlık
        cost_pct = (cpu_pct + mem_pct) / 2

        namespaces.append({
            'namespace': m.namespace,
            'cpu_cores': round(m.total_cpu, 3),
            'memory_gib': round(m.total_memory, 3),
            'cpu_pct': round(cpu_pct, 1),
            'memory_pct': round(mem_pct, 1),
            'cost_pct': round(cost_pct, 1),   # cluster toplam maliyetindeki payı
            'pod_count': len(m.pod_data),
        })

    # Maliyet oranına göre sırala
    namespaces.sort(key=lambda x: x['cost_pct'], reverse=True)

    return {
        'cluster_total_cpu': round(total_cpu, 3),
        'cluster_total_memory_gib': round(total_memory, 3),
        'namespaces': namespaces,
    }


def detect_waste(metrics: list) -> Dict[str, Any]:
    """
    Pod bazlı kaynak israfı tespiti.

    Waste kriterleri:
    1. CPU waste  — request > 0 ama pod çok eski ve hiç restart almamış
                    → muhtemelen fazla request etmiş
    2. Memory waste — request > cluster ortalamasının 2 katı
                      ama pod stabil (restart yok)
    3. Idle pod  — Pending/Failed durumda kaynak bloke eden pod
    4. Oversized — Tek pod namespace CPU'sunun %80'inden fazlasını istiyor
    """
    if not metrics:
        return {'waste_pods': [], 'summary': {}}

    # Cluster genelinde ortalamalar
    all_pods = []
    for m in metrics:
        for pod in m.pod_data:
            all_pods.append({
                **pod,
                'namespace': m.namespace,
                'ns_total_cpu': m.total_cpu,
                'ns_pod_count': max(len(m.pod_data), 1),
            })

    if not all_pods:
        return {'waste_pods': [], 'summary': {}}

    avg_cpu = sum(p.get('cpu_request', 0) for p in all_pods) / len(all_pods)
    avg_memory = sum(p.get('memory_request', 0) for p in all_pods) / len(all_pods)

    waste_pods = []

    for pod in all_pods:
        cpu = pod.get('cpu_request', 0)
        memory = pod.get('memory_request', 0)
        restarts = pod.get('restart_count', 0)
        age_hours = pod.get('age_hours', 0)
        status = pod.get('status', 'Unknown')
        ns_total_cpu = pod.get('ns_total_cpu', 0)

        waste_reasons = []
        waste_score = 0  # 0-100

        # 1. Idle pod — kaynak bloklayan ama çalışmayan pod
        if status in ('Pending', 'Failed') and (cpu > 0 or memory > 0):
            waste_reasons.append({
                'type': 'idle_pod',
                'message': f'Pod {status} durumda ama {cpu:.2f} CPU + {memory:.2f}Gi memory bloklıyor',
                'severity': 'high'
            })
            waste_score += 60

        # 2. Oversized — namespace CPU'sunun büyük kısmını tek pod yiyor
        if ns_total_cpu > 0 and cpu / ns_total_cpu > 0.8 and pod.get('ns_pod_count', 1) > 1:
            pct = cpu / ns_total_cpu * 100
            waste_reasons.append({
                'type': 'oversized',
                'message': f'Namespace CPU\'sunun %{pct:.0f}\'ini tek başına istiyor',
                'severity': 'high'
            })
            waste_score += 40

        # 3. High memory, stabil pod — muhtemelen fazla request etmiş
        if (memory > avg_memory * 2.5
                and restarts == 0
                and age_hours > 24
                and status == 'Running'):
            waste_reasons.append({
                'type': 'memory_overrequest',
                'message': f'Cluster ortalamasının {memory/max(avg_memory,0.001):.1f}x memory\'si var, hiç restart almamış',
                'severity': 'medium'
            })
            waste_score += 30

        # 4. High CPU request, uzun süredir stabil
        if (cpu > avg_cpu * 3
                and restarts == 0
                and age_hours > 48
                and status == 'Running'):
            waste_reasons.append({
                'type': 'cpu_overrequest',
                'message': f'Cluster ortalamasının {cpu/max(avg_cpu,0.001):.1f}x CPU\'su var, {age_hours:.0f} saattir stabil',
                'severity': 'medium'
            })
            waste_score += 25

        # 5. Crash loop — sürekli restart → kaynak israfı
        if restarts >= 10:
            waste_reasons.append({
                'type': 'crash_loop',
                'message': f'{restarts} restart — pod sürekli çöküyor, kaynakları boşa harcıyor',
                'severity': 'high'
            })
            waste_score += 50

        if waste_reasons:
            waste_pods.append({
                'pod': pod.get('name', ''),
                'namespace': pod.get('namespace', ''),
                'status': status,
                'cpu_request': round(cpu, 3),
                'memory_request_gib': round(memory, 3),
                'restart_count': restarts,
                'age_hours': round(age_hours, 1),
                'waste_score': min(100, waste_score),
                'reasons': waste_reasons,
                # Öneri
                'recommendation': _get_recommendation(waste_reasons, cpu, memory, avg_cpu, avg_memory),
            })

    # Waste score'a göre sırala
    waste_pods.sort(key=lambda x: x['waste_score'], reverse=True)

    # Özet istatistikler
    total_wasted_cpu = sum(
        p['cpu_request'] for p in waste_pods
        if any(r['type'] in ('idle_pod', 'cpu_overrequest', 'oversized') for r in p['reasons'])
    )
    total_wasted_memory = sum(
        p['memory_request_gib'] for p in waste_pods
        if any(r['type'] in ('idle_pod', 'memory_overrequest') for r in p['reasons'])
    )

    cluster_cpu = sum(p.get('cpu_request', 0) for p in all_pods)
    cluster_memory = sum(p.get('memory_request', 0) for p in all_pods)

    return {
        'waste_pods': waste_pods,
        'summary': {
            'total_pods_analyzed': len(all_pods),
            'waste_pod_count': len(waste_pods),
            'waste_pct': round(len(waste_pods) / max(len(all_pods), 1) * 100, 1),
            'wasted_cpu_cores': round(total_wasted_cpu, 3),
            'wasted_memory_gib': round(total_wasted_memory, 3),
            'wasted_cpu_pct': round(total_wasted_cpu / max(cluster_cpu, 0.001) * 100, 1),
            'wasted_memory_pct': round(total_wasted_memory / max(cluster_memory, 0.001) * 100, 1),
        }
    }


def _get_recommendation(reasons, cpu, memory, avg_cpu, avg_memory) -> str:
    types = [r['type'] for r in reasons]

    if 'idle_pod' in types:
        return 'Pod çalışmıyor, silinmesi veya debug edilmesi önerilir'
    if 'crash_loop' in types:
        return 'Pod sürekli crash alıyor, uygulama logları incelenmeli'
    if 'oversized' in types:
        return f'CPU request {cpu:.2f} yerine {cpu*0.5:.2f} core denenebilir'
    if 'memory_overrequest' in types and 'cpu_overrequest' in types:
        return f'CPU\'yu {avg_cpu*1.5:.2f} core, memory\'yi {avg_memory*1.5:.2f}Gi\'a düşürmeyi dene'
    if 'memory_overrequest' in types:
        return f'Memory request {memory:.2f}Gi yerine {avg_memory*1.5:.2f}Gi denenebilir'
    if 'cpu_overrequest' in types:
        return f'CPU request {cpu:.2f} yerine {avg_cpu*1.5:.2f} core denenebilir'
    return 'Kaynak kullanımını izlemeye devam et'
