# api/routes/alerts.py
from fastapi import APIRouter, HTTPException
from datetime import datetime
from typing import List, Optional
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from db.repository import MetricRepository
from pydantic import BaseModel

router = APIRouter()

class AlertResponse(BaseModel):
    id: int
    namespace: str
    message: str
    severity: str
    created_at: datetime

@router.get("/", response_model=List[AlertResponse])
async def get_alerts(active_only: bool = True):
    """Aktif uyarıları getir"""
    repo = MetricRepository()
    
    if active_only:
        alerts = repo.get_active_alerts()
    else:
        alerts = repo.db.query(repo.db.models.Alert).all()
    
    result = [
        AlertResponse(
            id=a.id,
            namespace=a.namespace,
            message=a.message,
            severity=a.severity,
            created_at=a.created_at
        )
        for a in alerts
    ]
    
    repo.close()
    return result

@router.post("/{alert_id}/resolve")
async def resolve_alert(alert_id: int):
    """Uyarıyı çözüldü olarak işaretle"""
    repo = MetricRepository()
    
    alert = repo.db.query(repo.db.models.Alert).filter(
        repo.db.models.Alert.id == alert_id
    ).first()
    
    if not alert:
        repo.close()
        raise HTTPException(status_code=404, detail="Alert not found")
    
    alert.resolved = True
    repo.db.commit()
    
    repo.close()
    return {"status": "resolved", "id": alert_id}
