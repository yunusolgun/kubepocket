# api/routes/clusters.py
from fastapi import APIRouter
from datetime import datetime
from typing import List, Optional
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from db.repository import MetricRepository
from pydantic import BaseModel

router = APIRouter()

class ClusterResponse(BaseModel):
    id: int
    name: str
    context: str
    created_at: datetime
    last_seen: Optional[datetime] = None

@router.get("/", response_model=List[ClusterResponse])
async def get_clusters():
    """Tüm cluster'ları getir"""
    repo = MetricRepository()
    
    clusters = repo.db.query(repo.db.models.Cluster).all()
    
    result = []
    for c in clusters:
        # Son metrik zamanını bul
        last_metric = repo.db.query(repo.db.models.Metric).filter(
            repo.db.models.Metric.cluster_id == c.id
        ).order_by(repo.db.models.Metric.timestamp.desc()).first()
        
        result.append(ClusterResponse(
            id=c.id,
            name=c.name,
            context=c.context,
            created_at=c.created_at,
            last_seen=last_metric.timestamp if last_metric else None
        ))
    
    repo.close()
    return result
