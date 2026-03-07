# api/routes/storage.py
from fastapi import APIRouter, Depends
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from db.models import ApiKey
from api.auth import get_current_key
from collector.k8s_client import K8sClient

router = APIRouter()


@router.get("/")
async def get_storage(_auth: ApiKey = Depends(get_current_key)):
    """PVC ve PV bazlı storage izleme."""
    try:
        k8s = K8sClient()
        pvcs = k8s.collect_pvc_metrics()
        total_capacity  = round(sum(p['capacity_gib'] for p in pvcs), 3)
        total_requested = round(sum(p['requested_gib'] for p in pvcs), 3)
        unbound = [p for p in pvcs if not p['bound']]
        return {
            'pvcs': pvcs,
            'summary': {
                'total_pvcs': len(pvcs),
                'bound': sum(1 for p in pvcs if p['bound']),
                'unbound': len(unbound),
                'total_capacity_gib': total_capacity,
                'total_requested_gib': total_requested,
            },
            'unbound': unbound,
        }
    except Exception as e:
        return {'error': str(e), 'pvcs': []}
