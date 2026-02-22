# api/routes/metrics.py
from pydantic import BaseModel
from api.auth import get_current_key
from db.models import ApiKey
from db.repository import MetricRepository
from db.dependencies import get_db
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


router = APIRouter()


class PodMetric(BaseModel):
    name: str
    namespace: str
    status: str
    restart_count: int
    cpu_request: float
    memory_request: float
    age_hours: float


class NamespaceMetric(BaseModel):
    namespace: str
    pod_count: int
    total_cpu: float
    total_memory: float
    total_restarts: int
    running_pods: int
    pending_pods: int
    failed_pods: int
    pods: List[PodMetric]


class SummaryMetric(BaseModel):
    total_namespaces: int
    total_pods: int
    total_cpu: float
    total_memory: float
    total_restarts: int
    active_alerts: int


@router.get("/summary", response_model=SummaryMetric)
async def get_summary(
    db: Session = Depends(get_db),
    _auth: ApiKey = Depends(get_current_key)
):
    repo = MetricRepository(db)
    metrics = repo.get_latest_metrics(hours=1)

    if not metrics:
        return SummaryMetric(
            total_namespaces=0, total_pods=0, total_cpu=0,
            total_memory=0, total_restarts=0, active_alerts=0
        )

    namespaces = set()
    total_pods = 0
    total_cpu = 0.0
    total_memory = 0.0
    total_restarts = 0

    for m in metrics:
        namespaces.add(m.namespace)
        total_pods += len(m.pod_data)
        total_cpu += m.total_cpu
        total_memory += m.total_memory
        total_restarts += m.total_restarts

    active_alerts = repo.get_active_alerts()

    return SummaryMetric(
        total_namespaces=len(namespaces),
        total_pods=total_pods,
        total_cpu=round(total_cpu, 2),
        total_memory=round(total_memory, 2),
        total_restarts=total_restarts,
        active_alerts=len(active_alerts)
    )


@router.get("/namespaces", response_model=List[NamespaceMetric])
async def get_namespace_metrics(
    hours: int = Query(1, description="Son kaç saatlik veri"),
    db: Session = Depends(get_db),
    _auth: ApiKey = Depends(get_current_key)
):
    repo = MetricRepository(db)
    metrics = repo.get_latest_metrics(hours=hours)

    if not metrics:
        return []

    namespace_data = {}

    for m in metrics:
        if m.namespace not in namespace_data:
            namespace_data[m.namespace] = {
                'total_cpu': 0.0, 'total_memory': 0.0, 'total_restarts': 0,
                'running_pods': 0, 'pending_pods': 0, 'failed_pods': 0,
                'pods': [], 'sample_count': 0
            }

        data = namespace_data[m.namespace]
        data['sample_count'] += 1
        data['total_cpu'] += m.total_cpu
        data['total_memory'] += m.total_memory
        data['total_restarts'] += m.total_restarts

        if not data['pods']:
            for pod in m.pod_data:
                data['pods'].append(PodMetric(
                    name=pod['name'],
                    namespace=pod['namespace'],
                    status=pod['status'],
                    restart_count=pod['restart_count'],
                    cpu_request=pod['cpu_request'],
                    memory_request=round(pod['memory_request'], 2),
                    age_hours=round(pod['age_hours'], 1)
                ))
                if pod['status'] == 'Running':
                    data['running_pods'] += 1
                elif pod['status'] == 'Pending':
                    data['pending_pods'] += 1
                elif pod['status'] == 'Failed':
                    data['failed_pods'] += 1

    result = []
    for ns, data in namespace_data.items():
        count = data['sample_count']
        result.append(NamespaceMetric(
            namespace=ns,
            pod_count=len(data['pods']),
            total_cpu=round(data['total_cpu'] / count, 2),
            total_memory=round(data['total_memory'] / count, 2),
            total_restarts=data['total_restarts'],
            running_pods=data['running_pods'],
            pending_pods=data['pending_pods'],
            failed_pods=data['failed_pods'],
            pods=data['pods']
        ))

    return result


@router.get("/trend")
async def get_trend(
    days: int = 7,
    db: Session = Depends(get_db),
    _auth: ApiKey = Depends(get_current_key)
):
    repo = MetricRepository(db)
    metrics = repo.get_latest_metrics(hours=days * 24)

    daily_data = {}
    for m in metrics:
        day = m.timestamp.strftime('%Y-%m-%d')
        if day not in daily_data:
            daily_data[day] = {'cpu': 0.0, 'memory': 0.0, 'count': 0}
        daily_data[day]['cpu'] += m.total_cpu
        daily_data[day]['memory'] += m.total_memory
        daily_data[day]['count'] += 1

    result = {'labels': [], 'cpu': [], 'memory': []}
    for day in sorted(daily_data.keys()):
        count = daily_data[day]['count']
        result['labels'].append(day[-5:])
        result['cpu'].append(round(daily_data[day]['cpu'] / count, 2))
        result['memory'].append(round(daily_data[day]['memory'] / count, 2))

    return result
