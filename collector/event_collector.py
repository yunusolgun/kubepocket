# collector/event_collector.py
"""
Kubernetes event collector.

Tracks: OOMKilled, BackOff, Evicted, FailedScheduling,
        Unhealthy (probe failures), Failed, Killing
"""
from db.models import SessionLocal, KubeEvent
from kubernetes.client.rest import ApiException
from kubernetes import client, config
import os
import sys
import logging
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


logger = logging.getLogger(__name__)

# Takip edilecek event reason'ları
TRACKED_REASONS = {
    'OOMKilling',
    'OOMKilled',
    'BackOff',
    'CrashLoopBackOff',
    'Evicted',
    'Evicting',
    'FailedScheduling',
    'Unhealthy',        # liveness/readiness probe fail
    'Failed',
    'Killing',
    'NodeNotReady',
    'Preempting',
    'ImagePullBackOff',
    'ErrImagePull',
    'FailedMount',
    'FailedAttachVolume',
}

# Reason → normalized event_type
EVENT_TYPE_MAP = {
    'OOMKilling': 'OOMKilled',
    'OOMKilled': 'OOMKilled',
    'BackOff': 'CrashLoopBackOff',
    'CrashLoopBackOff': 'CrashLoopBackOff',
    'Evicted': 'Evicted',
    'Evicting': 'Evicted',
    'FailedScheduling': 'FailedScheduling',
    'Unhealthy': 'ProbeFailed',
    'Failed': 'Failed',
    'Killing': 'Killing',
    'NodeNotReady': 'NodeNotReady',
    'Preempting': 'Preempting',
    'ImagePullBackOff': 'ImagePullBackOff',
    'ErrImagePull': 'ImagePullBackOff',
    'FailedMount': 'FailedMount',
    'FailedAttachVolume': 'FailedMount',
}


def _parse_k8s_time(dt):
    """Kubernetes datetime → Python datetime (UTC, naive)"""
    if dt is None:
        return None
    if hasattr(dt, 'replace'):
        return dt.replace(tzinfo=None)
    return None


class EventCollector:

    def __init__(self, cluster_id=None):
        try:
            config.load_incluster_config()
        except:
            config.load_kube_config()

        self.core_v1 = client.CoreV1Api()
        self.cluster_id = cluster_id

    def collect_events(self):
        """
        Tüm namespace'lerden kritik event'leri topla ve DB'ye kaydet.
        Aynı (pod, event_type) için yeni kayıt eklemek yerine count'u güncelle.
        """
        db = SessionLocal()
        saved = 0
        updated = 0

        try:
            # Tüm namespace'lerden event'leri çek
            events = self.core_v1.list_event_for_all_namespaces(
                field_selector='type=Warning'  # sadece Warning event'leri
            )

            for event in events.items:
                reason = event.reason or ''
                if reason not in TRACKED_REASONS:
                    continue

                # Pod adını bul
                involved = event.involved_object
                if involved.kind not in ('Pod', 'Node'):
                    continue

                pod_name = involved.name or 'unknown'
                namespace = event.metadata.namespace or 'default'
                event_type = EVENT_TYPE_MAP.get(reason, reason)
                message = event.message or ''
                count = event.count or 1
                first_seen = _parse_k8s_time(event.first_timestamp)
                last_seen = _parse_k8s_time(event.last_timestamp)

                # Aynı pod + event_type varsa güncelle
                existing = (
                    db.query(KubeEvent)
                    .filter(
                        KubeEvent.namespace == namespace,
                        KubeEvent.pod_name == pod_name,
                        KubeEvent.event_type == event_type,
                    )
                    .order_by(KubeEvent.created_at.desc())
                    .first()
                )

                if existing:
                    existing.count = max(existing.count, count)
                    existing.last_seen = last_seen or existing.last_seen
                    existing.message = message or existing.message
                    updated += 1
                else:
                    db.add(KubeEvent(
                        cluster_id=self.cluster_id,
                        namespace=namespace,
                        pod_name=pod_name,
                        event_type=event_type,
                        reason=reason,
                        message=message,
                        count=count,
                        first_seen=first_seen,
                        last_seen=last_seen,
                    ))
                    saved += 1

            db.commit()
            logger.info(f"Events: {saved} new, {updated} updated")
            return saved, updated

        except ApiException as e:
            logger.error(f"Kubernetes API error: {e}")
            db.rollback()
            return 0, 0
        except Exception as e:
            logger.error(f"Event collection error: {e}", exc_info=True)
            db.rollback()
            return 0, 0
        finally:
            db.close()

    def get_event_summary(self, hours=24):
        """Son X saatteki event özetini döndür"""
        from datetime import timedelta
        db = SessionLocal()
        try:
            since = datetime.utcnow() - timedelta(hours=hours)
            events = (
                db.query(KubeEvent)
                .filter(KubeEvent.created_at >= since)
                .order_by(KubeEvent.last_seen.desc())
                .all()
            )
            return events
        finally:
            db.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    collector = EventCollector()
    saved, updated = collector.collect_events()
    print(f'Done: {saved} saved, {updated} updated')
