# api/routes/metrics.py
from fastapi import APIRouter, HTTPException, Query
from datetime import datetime, timedelta
from typing import Optional, List
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from db.repository import MetricRepository
from pydantic import BaseModel

router = APIRouter()

# Response modelleri
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
async def get_summary():
    """Genel özet bilgilerini getir"""
    repo = MetricRepository()
    
    # Son 1 saatlik metrikler
    metrics = repo.get_latest_metrics(hours=1)
    
    if not metrics:
        repo.close()
        return SummaryMetric(
            total_namespaces=0,
            total_pods=0,
            total_cpu=0,
            total_memory=0,
            total_restarts=0,
            active_alerts=0
        )
    
    # Özet hesapla
    namespaces = set()
    total_pods = 0
    total_cpu = 0
    total_memory = 0
    total_restarts = 0
    
    for m in metrics:
        namespaces.add(m.namespace)
        total_pods += len(m.pod_data)
        total_cpu += m.total_cpu
        total_memory += m.total_memory
        total_restarts += m.total_restarts
    
    # Aktif alert sayısı
    alerts = repo.get_active_alerts()
    
    repo.close()
    
    return SummaryMetric(
        total_namespaces=len(namespaces),
        total_pods=total_pods,
        total_cpu=round(total_cpu, 2),
        total_memory=round(total_memory, 2),
        total_restarts=total_restarts,
        active_alerts=len(alerts)
    )

@router.get("/namespaces", response_model=List[NamespaceMetric])
async def get_namespace_metrics(
    hours: int = Query(1, description="Son kaç saatlik veri")
):
    """Namespace bazlı metrikleri getir"""
    repo = MetricRepository()
    metrics = repo.get_latest_metrics(hours=hours)
    
    if not metrics:
        repo.close()
        return []
    
    # Namespace bazlı grupla
    namespace_data = {}
    
    for m in metrics:
        if m.namespace not in namespace_data:
            namespace_data[m.namespace] = {
                'pod_count': 0,
                'total_cpu': 0,
                'total_memory': 0,
                'total_restarts': 0,
                'running_pods': 0,
                'pending_pods': 0,
                'failed_pods': 0,
                'pods': [],
                'sample_count': 0
            }
        
        data = namespace_data[m.namespace]
        data['sample_count'] += 1
        data['total_cpu'] += m.total_cpu
        data['total_memory'] += m.total_memory
        data['total_restarts'] += m.total_restarts
        
        # Pod detaylarını topla (ilk metriği kullan)
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
                
                # Pod durumlarını say
                if pod['status'] == 'Running':
                    data['running_pods'] += 1
                elif pod['status'] == 'Pending':
                    data['pending_pods'] += 1
                elif pod['status'] == 'Failed':
                    data['failed_pods'] += 1
    
    # Ortalamaları hesapla
    result = []
    for ns, data in namespace_data.items():
        result.append(NamespaceMetric(
            namespace=ns,
            pod_count=len(data['pods']),
            total_cpu=round(data['total_cpu'] / data['sample_count'], 2),
            total_memory=round(data['total_memory'] / data['sample_count'], 2),
            total_restarts=data['total_restarts'],
            running_pods=data['running_pods'],
            pending_pods=data['pending_pods'],
            failed_pods=data['failed_pods'],
            pods=data['pods']
        ))
    
    repo.close()
    return result

@router.get("/trend")
async def get_trend(days: int = 7):
    """Günlük trend verilerini getir"""
    repo = MetricRepository()
    
    # Son N günlük veri
    metrics = repo.get_latest_metrics(hours=days*24)
    
    # Günlük grupla
    daily_data = {}
    
    for m in metrics:
        day = m.timestamp.strftime('%Y-%m-%d')
        if day not in daily_data:
            daily_data[day] = {'cpu': 0, 'memory': 0, 'count': 0}
        
        daily_data[day]['cpu'] += m.total_cpu
        daily_data[day]['memory'] += m.total_memory
        daily_data[day]['count'] += 1
    
    # Response hazırla
    result = {
        'labels': [],
        'cpu': [],
        'memory': []
    }
    
    for day in sorted(daily_data.keys()):
        result['labels'].append(day[-5:])  # Sadece ay-gün
        avg_cpu = daily_data[day]['cpu'] / daily_data[day]['count']
        avg_memory = daily_data[day]['memory'] / daily_data[day]['count']
        result['cpu'].append(round(avg_cpu, 2))
        result['memory'].append(round(avg_memory, 2))
    
    repo.close()
    return result
