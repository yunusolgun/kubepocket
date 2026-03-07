# api/routes/nodes.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from db.dependencies import get_db
from db.models import ApiKey
from api.auth import get_current_key
from collector.k8s_client import K8sClient

router = APIRouter()


@router.get("/")
async def get_nodes(_auth: ApiKey = Depends(get_current_key)):
    """Node bazlı kapasite, allocatable, kullanım ve pod dağılımı."""
    try:
        k8s = K8sClient()
        nodes = k8s.collect_node_metrics()
        return {
            'nodes': nodes,
            'summary': {
                'total_nodes': len(nodes),
                'ready_nodes': sum(1 for n in nodes if n['ready']),
                'total_cpu_capacity': round(sum(n['cpu_capacity'] for n in nodes), 2),
                'total_cpu_requested': round(sum(n['cpu_requested'] for n in nodes), 2),
                'total_mem_capacity_gib': round(sum(n['mem_capacity_gib'] for n in nodes), 2),
                'total_mem_requested_gib': round(sum(n['mem_requested_gib'] for n in nodes), 2),
                'total_pods_running': sum(n['pods_running'] for n in nodes),
            }
        }
    except Exception as e:
        return {'error': str(e), 'nodes': []}
