# api/routes/events.py
from datetime import datetime, timedelta
from api.auth import get_current_key
from db.models import ApiKey, KubeEvent
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


@router.get("/")
async def get_events(
    cluster:    Optional[str] = Query(None, description="Filter by cluster name"),
    namespace:  Optional[str] = None,
    event_type: Optional[str] = None,
    pod:        Optional[str] = None,
    hours: int  = Query(24, description="Last N hours"),
    limit: int  = Query(100, description="Max results"),
    db: Session = Depends(get_db),
    _auth: ApiKey = Depends(get_current_key)
):
    """List Kubernetes events. Filter by cluster, namespace, event_type, pod."""
    repo = MetricRepository(db)

    # Resolve cluster_id
    cluster_id = None
    if cluster:
        c = repo.get_cluster_by_name(cluster)
        if not c:
            return []
        cluster_id = c.id

    since = datetime.utcnow() - timedelta(hours=hours)
    query = db.query(KubeEvent).filter(KubeEvent.created_at >= since)

    if cluster_id:
        query = query.filter(KubeEvent.cluster_id == cluster_id)
    if namespace:
        query = query.filter(KubeEvent.namespace == namespace)
    if event_type:
        query = query.filter(KubeEvent.event_type == event_type)
    if pod:
        query = query.filter(KubeEvent.pod_name.ilike(f'%{pod}%'))

    events = query.order_by(KubeEvent.last_seen.desc()).limit(limit).all()

    return [
        {
            'id':         e.id,
            'cluster_id': e.cluster_id,
            'namespace':  e.namespace,
            'pod':        e.pod_name,
            'event_type': e.event_type,
            'reason':     e.reason,
            'message':    e.message,
            'count':      e.count,
            'first_seen': e.first_seen.isoformat() if e.first_seen else None,
            'last_seen':  e.last_seen.isoformat()  if e.last_seen  else None,
        }
        for e in events
    ]


@router.get("/summary")
async def get_event_summary(
    cluster: Optional[str] = Query(None, description="Filter by cluster name"),
    hours: int = Query(24, description="Last N hours"),
    db: Session = Depends(get_db),
    _auth: ApiKey = Depends(get_current_key)
):
    """Event count statistics grouped by type, namespace, and top pods."""
    from sqlalchemy import func
    repo = MetricRepository(db)

    cluster_id = None
    if cluster:
        c = repo.get_cluster_by_name(cluster)
        if not c:
            return {'period_hours': hours, 'by_type': [], 'by_namespace': [], 'top_pods': []}
        cluster_id = c.id

    since = datetime.utcnow() - timedelta(hours=hours)

    base = db.query(KubeEvent).filter(KubeEvent.created_at >= since)
    if cluster_id:
        base = base.filter(KubeEvent.cluster_id == cluster_id)

    by_type = (
        base.with_entities(KubeEvent.event_type, func.count(KubeEvent.id).label('count'))
        .group_by(KubeEvent.event_type)
        .order_by(func.count(KubeEvent.id).desc())
        .all()
    )

    by_namespace = (
        base.with_entities(KubeEvent.namespace, func.count(KubeEvent.id).label('count'))
        .group_by(KubeEvent.namespace)
        .order_by(func.count(KubeEvent.id).desc())
        .all()
    )

    top_pods = (
        base.with_entities(
            KubeEvent.pod_name, KubeEvent.namespace,
            func.sum(KubeEvent.count).label('total')
        )
        .group_by(KubeEvent.pod_name, KubeEvent.namespace)
        .order_by(func.sum(KubeEvent.count).desc())
        .limit(10)
        .all()
    )

    return {
        'period_hours': hours,
        'by_type':      [{'event_type': r.event_type, 'count': r.count} for r in by_type],
        'by_namespace': [{'namespace': r.namespace,   'count': r.count} for r in by_namespace],
        'top_pods':     [{'pod': r.pod_name, 'namespace': r.namespace, 'total_events': r.total} for r in top_pods],
    }
