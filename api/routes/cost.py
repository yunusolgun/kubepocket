# api/routes/cost.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from db.dependencies import get_db
from db.repository import MetricRepository
from db.models import ApiKey
from api.auth import get_current_key
from collector.cost import calculate_relative_cost, detect_waste

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
