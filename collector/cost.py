# collector/cost.py
"""
Relative cost and waste detection.

No real $ pricing — uses proportional cluster analysis:
- Namespace share of cluster total (%)
- Pod resource efficiency (waste score)
- Idle resource amount
"""
from typing import List, Dict, Any


def calculate_relative_cost(metrics: list) -> Dict[str, Any]:
    """
    Calculate each namespace's share of cluster total.

    metrics: result of get_latest_per_namespace()
    """
    if not metrics:
        return {}

    total_cpu = sum(m.total_cpu for m in metrics)
    total_memory = sum(m.total_memory for m in metrics)

    namespaces = []
    for m in metrics:
        cpu_pct = (m.total_cpu / total_cpu * 100) if total_cpu > 0 else 0
        mem_pct = (m.total_memory / total_memory * 100) if total_memory > 0 else 0
        cost_pct = (cpu_pct + mem_pct) / 2

        namespaces.append({
            'namespace': m.namespace,
            'cpu_cores': round(m.total_cpu, 3),
            'memory_gib': round(m.total_memory, 3),
            'cpu_pct': round(cpu_pct, 1),
            'memory_pct': round(mem_pct, 1),
            'cost_pct': round(cost_pct, 1),
            'pod_count': len(m.pod_data),
        })

    namespaces.sort(key=lambda x: x['cost_pct'], reverse=True)

    return {
        'cluster_total_cpu': round(total_cpu, 3),
        'cluster_total_memory_gib': round(total_memory, 3),
        'namespaces': namespaces,
    }


def detect_waste(metrics: list) -> Dict[str, Any]:
    """
    Pod-level resource waste detection.

    Waste criteria:
    1. CPU waste    — high request, old pod, zero restarts
    2. Memory waste — request > 2.5x cluster average, stable pod
    3. Idle pod     — Pending/Failed but blocking resources
    4. Oversized    — single pod consuming >80% of namespace CPU
    5. Crash loop   — excessive restarts wasting resources
    """
    if not metrics:
        return {'waste_pods': [], 'summary': {}}

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
        waste_score = 0

        # 1. Idle pod — blocking resources but not running
        if status in ('Pending', 'Failed') and (cpu > 0 or memory > 0):
            waste_reasons.append({
                'type': 'idle_pod',
                'message': f'Pod is {status} but blocking {cpu:.2f} CPU + {memory:.2f}Gi memory',
                'severity': 'high'
            })
            waste_score += 60

        # 2. Oversized — single pod consuming most of namespace CPU
        if ns_total_cpu > 0 and cpu / ns_total_cpu > 0.8 and pod.get('ns_pod_count', 1) > 1:
            pct = cpu / ns_total_cpu * 100
            waste_reasons.append({
                'type': 'oversized',
                'message': f'Requesting {pct:.0f}% of namespace CPU alone',
                'severity': 'high'
            })
            waste_score += 40

        # 3. High memory, stable pod
        if (memory > avg_memory * 2.5
                and restarts == 0
                and age_hours > 24
                and status == 'Running'):
            ratio = memory / max(avg_memory, 0.001)
            waste_reasons.append({
                'type': 'memory_overrequest',
                'message': f'{ratio:.1f}x cluster average memory, zero restarts',
                'severity': 'medium'
            })
            waste_score += 30

        # 4. High CPU request, long stable run
        if (cpu > avg_cpu * 3
                and restarts == 0
                and age_hours > 48
                and status == 'Running'):
            ratio = cpu / max(avg_cpu, 0.001)
            waste_reasons.append({
                'type': 'cpu_overrequest',
                'message': f'{ratio:.1f}x cluster average CPU, stable for {age_hours:.0f}h',
                'severity': 'medium'
            })
            waste_score += 25

        # 5. Crash loop — wasting resources with constant restarts
        if restarts >= 10:
            waste_reasons.append({
                'type': 'crash_loop',
                'message': f'{restarts} restarts — pod keeps crashing, wasting resources',
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
                'recommendation': _get_recommendation(waste_reasons, cpu, memory, avg_cpu, avg_memory),
            })

    waste_pods.sort(key=lambda x: x['waste_score'], reverse=True)

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
        return 'Pod is not running, consider deleting or debugging it'
    if 'crash_loop' in types:
        return 'Pod keeps crashing, check application logs'
    if 'oversized' in types:
        return f'Try reducing CPU request from {cpu:.2f} to {cpu*0.5:.2f} cores'
    if 'memory_overrequest' in types and 'cpu_overrequest' in types:
        return f'Try reducing CPU to {avg_cpu*1.5:.2f} cores and memory to {avg_memory*1.5:.2f}Gi'
    if 'memory_overrequest' in types:
        return f'Try reducing memory request from {memory:.2f}Gi to {avg_memory*1.5:.2f}Gi'
    if 'cpu_overrequest' in types:
        return f'Try reducing CPU request from {cpu:.2f} to {avg_cpu*1.5:.2f} cores'
    return 'Continue monitoring resource usage'
