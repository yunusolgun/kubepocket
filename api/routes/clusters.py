# api/routes/clusters.py
from pydantic import BaseModel
from api.auth import get_current_key
from db.models import Cluster, Metric, ApiKey
from db.dependencies import get_db
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


router = APIRouter()


class ClusterResponse(BaseModel):
    id: int
    name: str
    context: str
    created_at: datetime
    last_seen: Optional[datetime] = None


@router.get("/", response_model=List[ClusterResponse])
async def get_clusters(
    db: Session = Depends(get_db),
    _auth: ApiKey = Depends(get_current_key)
):
    clusters = db.query(Cluster).all()

    result = []
    for c in clusters:
        last_metric = (
            db.query(Metric)
            .filter(Metric.cluster_id == c.id)
            .order_by(Metric.timestamp.desc())
            .first()
        )
        result.append(ClusterResponse(
            id=c.id,
            name=c.name,
            context=c.context,
            created_at=c.created_at,
            last_seen=last_metric.timestamp if last_metric else None
        ))

    return result
