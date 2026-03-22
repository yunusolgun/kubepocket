# api/routes/alerts.py
from pydantic import BaseModel
from api.auth import get_current_key
from db.models import Alert, ApiKey
from db.repository import MetricRepository
from db.dependencies import get_db
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


router = APIRouter()


class AlertResponse(BaseModel):
    id: int
    cluster: Optional[str] = None
    namespace: str
    message: str
    severity: str
    created_at: datetime


@router.get("/", response_model=List[AlertResponse])
async def get_alerts(
    cluster: Optional[str] = Query(None, description="Filter by cluster name"),
    active_only: bool = True,
    db: Session = Depends(get_db),
    _auth: ApiKey = Depends(get_current_key)
):
    repo = MetricRepository(db)

    # Resolve cluster_id
    cluster_id = None
    if cluster:
        c = repo.get_cluster_by_name(cluster)
        if not c:
            return []
        cluster_id = c.id

    if active_only:
        alerts = repo.get_active_alerts(cluster_id=cluster_id)
    else:
        query = db.query(Alert)
        if cluster_id:
            query = query.filter(Alert.cluster_id == cluster_id)
        alerts = query.all()

    # Build cluster id→name map
    all_clusters = {cl.id: cl.name for cl in repo.get_all_clusters()}

    return [
        AlertResponse(
            id=a.id,
            cluster=all_clusters.get(a.cluster_id),
            namespace=a.namespace,
            message=a.message,
            severity=a.severity,
            created_at=a.created_at
        )
        for a in alerts
    ]


@router.post("/{alert_id}/resolve")
async def resolve_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    _auth: ApiKey = Depends(get_current_key)
):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.resolved = True
    db.commit()

    return {"status": "resolved", "id": alert_id}
