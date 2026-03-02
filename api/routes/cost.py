# api/routes/cost.py
from collector.cost import calculate_relative_cost, detect_waste
from api.auth import get_current_key
from db.models import ApiKey
from db.repository import MetricRepository
from db.dependencies import get_db
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


router = APIRouter()


@router.get("/relative")
async def get_relative_cost(
    db: Session = Depends(get_db),
    _auth: ApiKey = Depends(get_current_key)
):
    """
    Her namespace'in cluster toplam maliyetindeki oransal payı.
    Gerçek $ değil, % cinsinden göreceli maliyet.
    """
    repo = MetricRepository(db)
    metrics = repo.get_latest_per_namespace()
    return calculate_relative_cost(metrics)


@router.get("/waste")
async def get_waste(
    db: Session = Depends(get_db),
    _auth: ApiKey = Depends(get_current_key)
):
    """
    Kaynak israfı yapan pod'ları tespit et.
    Her pod için waste_score (0-100) ve öneri döndürür.
    """
    repo = MetricRepository(db)
    metrics = repo.get_latest_per_namespace()
    return detect_waste(metrics)


@router.get("/summary")
async def get_cost_summary(
    db: Session = Depends(get_db),
    _auth: ApiKey = Depends(get_current_key)
):
    """
    Göreceli maliyet + waste tespiti özeti — tek endpoint'te.
    """
    repo = MetricRepository(db)
    metrics = repo.get_latest_per_namespace()

    relative = calculate_relative_cost(metrics)
    waste = detect_waste(metrics)

    return {
        'relative_cost': relative,
        'waste': waste,
    }


@router.get("/efficiency")
async def get_efficiency(
    namespace: str = Query(None, description="Filter by namespace"),
    db: Session = Depends(get_db),
    _auth: ApiKey = Depends(get_current_key)
):
    """
    Gerçek kullanım vs request karşılaştırması.
    Metrics Server verisi pod_data içinde cpu_actual/memory_actual_gib olarak saklanır.
    """
    repo = MetricRepository(db)
    metrics = repo.get_latest_per_namespace()

    results = []
    for m in metrics:
        if namespace and m.namespace != namespace:
            continue
        for pod in m.pod_data:
            cpu_req = pod.get('cpu_request', 0)
            mem_req = pod.get('memory_request', 0)
            cpu_act = pod.get('cpu_actual')
            mem_act = pod.get('memory_actual_gib')

            if cpu_act is None and mem_act is None:
                continue

            results.append({
                'pod': pod.get('name'),
                'namespace': pod.get('namespace', m.namespace),
                'cpu_request': round(cpu_req, 4),
                'cpu_actual': cpu_act,
                'cpu_efficiency_pct': pod.get('cpu_efficiency_pct'),
                'cpu_wasted_cores': round(cpu_req - cpu_act, 4) if cpu_act is not None else None,
                'memory_request_gib': round(mem_req, 4),
                'memory_actual_gib': mem_act,
                'memory_efficiency_pct': pod.get('memory_efficiency_pct'),
                'memory_wasted_gib': round(mem_req - mem_act, 4) if mem_act is not None else None,
            })

    results.sort(key=lambda x: (x.get('cpu_efficiency_pct') or 100))

    return {
        'pods': results,
        'summary': {
            'total_pods_with_data': len(results),
            'avg_cpu_efficiency_pct': round(
                sum(r['cpu_efficiency_pct']
                    for r in results if r['cpu_efficiency_pct'] is not None)
                / max(sum(1 for r in results if r['cpu_efficiency_pct'] is not None), 1), 1
            ),
            'avg_memory_efficiency_pct': round(
                sum(r['memory_efficiency_pct']
                    for r in results if r['memory_efficiency_pct'] is not None)
                / max(sum(1 for r in results if r['memory_efficiency_pct'] is not None), 1), 1
            ),
        }
    }
