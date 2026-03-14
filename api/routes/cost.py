# api/routes/cost.py
from collector.cost import calculate_relative_cost, detect_waste
from api.auth import get_current_key
from db.models import ApiKey
from db.repository import MetricRepository
from db.dependencies import get_db
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


router = APIRouter()


def _get_metrics(db, cluster: Optional[str], repo: MetricRepository):
    if not cluster:
        return repo.get_latest_per_namespace()
    c = repo.get_cluster_by_name(cluster)
    if not c:
        return []
    return repo.get_latest_per_namespace(cluster_id=c.id)


@router.get("/relative")
async def get_relative_cost(
    cluster: Optional[str] = Query(None, description="Filter by cluster name"),
    db: Session = Depends(get_db),
    _auth: ApiKey = Depends(get_current_key)
):
    """Relative cost share per namespace as a percentage of cluster total."""
    repo = MetricRepository(db)
    metrics = _get_metrics(db, cluster, repo)
    return calculate_relative_cost(metrics)


@router.get("/waste")
async def get_waste(
    cluster: Optional[str] = Query(None, description="Filter by cluster name"),
    db: Session = Depends(get_db),
    _auth: ApiKey = Depends(get_current_key)
):
    """Detect resource waste per pod with waste_score (0-100) and recommendation."""
    repo = MetricRepository(db)
    metrics = _get_metrics(db, cluster, repo)
    return detect_waste(metrics)


@router.get("/summary")
async def get_cost_summary(
    cluster: Optional[str] = Query(None, description="Filter by cluster name"),
    db: Session = Depends(get_db),
    _auth: ApiKey = Depends(get_current_key)
):
    """Relative cost + waste detection in a single response."""
    repo = MetricRepository(db)
    metrics = _get_metrics(db, cluster, repo)
    return {
        'relative_cost': calculate_relative_cost(metrics),
        'waste':         detect_waste(metrics),
    }


@router.get("/efficiency")
async def get_efficiency(
    cluster:   Optional[str] = Query(None, description="Filter by cluster name"),
    namespace: Optional[str] = Query(None, description="Filter by namespace"),
    db: Session = Depends(get_db),
    _auth: ApiKey = Depends(get_current_key)
):
    """Actual usage vs requested resources (requires Metrics Server)."""
    repo = MetricRepository(db)
    metrics = _get_metrics(db, cluster, repo)

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
                'pod':                    pod.get('name'),
                'namespace':              pod.get('namespace', m.namespace),
                'cpu_request':            round(cpu_req, 4),
                'cpu_actual':             cpu_act,
                'cpu_efficiency_pct':     pod.get('cpu_efficiency_pct'),
                'cpu_wasted_cores':       round(cpu_req - cpu_act, 4) if cpu_act is not None else None,
                'memory_request_gib':     round(mem_req, 4),
                'memory_actual_gib':      mem_act,
                'memory_efficiency_pct':  pod.get('memory_efficiency_pct'),
                'memory_wasted_gib':      round(mem_req - mem_act, 4) if mem_act is not None else None,
            })

    results.sort(key=lambda x: (x.get('cpu_efficiency_pct') or 100))

    return {
        'pods': results,
        'summary': {
            'total_pods_with_data': len(results),
            'avg_cpu_efficiency_pct': round(
                sum(r['cpu_efficiency_pct'] for r in results if r['cpu_efficiency_pct'] is not None)
                / max(sum(1 for r in results if r['cpu_efficiency_pct'] is not None), 1), 1
            ),
            'avg_memory_efficiency_pct': round(
                sum(r['memory_efficiency_pct'] for r in results if r['memory_efficiency_pct'] is not None)
                / max(sum(1 for r in results if r['memory_efficiency_pct'] is not None), 1), 1
            ),
        }
    }
