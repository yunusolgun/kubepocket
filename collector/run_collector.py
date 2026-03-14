#!/usr/bin/env python3
# collector/run_collector.py
from db.models import init_db, SessionLocal
from db.repository import MetricRepository
from collector.event_collector import EventCollector
from collector.k8s_client import K8sClient
import sys
import os
import time
from datetime import datetime, timedelta
import argparse

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CLUSTER_NAME = os.getenv('CLUSTER_NAME', 'default')
LICENSE_KEY = os.getenv('KUBEPOCKET_LICENSE_KEY', '')


def _get_license():
    try:
        from licensing.license import verify_license
        return verify_license(LICENSE_KEY)
    except ImportError:
        return None


def _check_cluster_limit(license, repo) -> bool:
    """
    Returns True if this cluster is allowed to collect data.
    For free tier: only 1 cluster allowed.
    For pro tier: unlimited.
    If the cluster already exists in DB it is always allowed
    (it was registered when the license was valid).
    """
    if license is None or license.is_unlimited_clusters():
        return True

    # If this cluster is already registered, always allow
    existing = repo.get_cluster_by_name(CLUSTER_NAME)
    if existing:
        return True

    # New cluster — check how many clusters already exist
    all_clusters = repo.get_all_clusters()
    if len(all_clusters) >= license.cluster_limit:
        print(f"⛔ Cluster limit reached ({len(all_clusters)}/{license.cluster_limit}). "
              f"This cluster ({CLUSTER_NAME}) will not be registered. "
              f"Upgrade to Pro for unlimited clusters.")
        return False

    return True


def _cleanup_old_data(db, cluster_id: int, license):
    """
    Retention cleanup — only deletes data collected AFTER the license
    downgrade/expiry date. Data collected during an active Pro period
    is never touched, preserving history if the customer renews.
    """
    try:
        from db.models import Metric

        retention_days = license.retention_days

        if license.pro_expired and license.pro_expired_at:
            try:
                expiry_date = datetime.fromisoformat(license.pro_expired_at)
            except ValueError:
                expiry_date = datetime.utcnow()
            cutoff = expiry_date + timedelta(days=retention_days)
            if datetime.utcnow() < cutoff:
                return
            delete_before = expiry_date
        else:
            delete_before = datetime.utcnow() - timedelta(days=retention_days)

        deleted = (
            db.query(Metric)
            .filter(
                Metric.cluster_id == cluster_id,
                Metric.timestamp < delete_before,
            )
            .delete()
        )
        if deleted:
            db.commit()
            print(f"  🗑  Retention cleanup: removed {deleted} old metric records "
                  f"(before {delete_before.date()})")
    except Exception as e:
        print(f"  Warning: Retention cleanup failed: {e}")


def collect_once(context=None):
    print(f"\n{'='*50}")
    print(f"KubePocket Collector - {datetime.now()}")
    print('='*50)

    init_db()

    # ── License ───────────────────────────────────────────────
    license = _get_license()
    if license is not None:
        if not license.valid:
            print(f"⚠️  License: {license.error}")
            print("   Running in Free tier mode (4 namespace, 1 cluster limit)")
            from licensing.license import LicenseInfo
            license = LicenseInfo(valid=True)
        else:
            tier_label = license.tier.upper()
            ns_label = "unlimited" if license.is_unlimited_namespaces() else str(
                license.namespace_limit)
            cl_label = "unlimited" if license.is_unlimited_clusters() else str(license.cluster_limit)
            print(f"🔑 License: {tier_label} — {license.customer} "
                  f"(namespaces: {ns_label}, clusters: {cl_label})")
            if license.pro_expired:
                print(f"⚠️  Pro license expired on {license.pro_expired_at}. "
                      f"Downgraded to Free tier. Existing data preserved.")
            elif license.is_trial and license.trial_expired:
                print("⚠️  Free trial expired. System continues in Free tier mode.")
            elif license.days_until_expiry() is not None and license.days_until_expiry() <= 30:
                print(
                    f"⚠️  License expires in {license.days_until_expiry()} days!")
    # ──────────────────────────────────────────────────────────

    try:
        k8s = K8sClient(context=context)
    except Exception as e:
        print(f"Kubernetes connection error: {e}")
        return False

    db = SessionLocal()
    try:
        repo = MetricRepository(db)

        # ── Cluster limit check ───────────────────────────────
        if not _check_cluster_limit(license, repo):
            return False
        # ─────────────────────────────────────────────────────

        cluster = repo.get_or_create_cluster(
            CLUSTER_NAME, context or 'in-cluster')

        print("\nCollecting metrics...")
        metrics = k8s.collect_all_metrics_with_usage()

        if not metrics:
            print("No metrics collected!")
            return False

        # Namespace limit
        if license is not None and not license.is_unlimited_namespaces():
            if len(metrics) > license.namespace_limit:
                print(f"⚠️  Namespace limit: {license.namespace_limit} (found {len(metrics)}). "
                      f"Only first {license.namespace_limit} will be saved. "
                      f"Upgrade to Pro for unlimited namespaces.")
                metrics = metrics[:license.namespace_limit]

        saved = repo.save_metrics(cluster.id, metrics)

        # Retention cleanup
        if license is not None:
            _cleanup_old_data(db, cluster.id, license)

        print("\nCollecting Kubernetes events...")
        try:
            event_collector = EventCollector(cluster_id=cluster.id)
            ev_saved, ev_updated = event_collector.collect_events()
            print(f"  -> {ev_saved} new events, {ev_updated} updated")
        except Exception as e:
            print(f"  Warning: Event collection failed: {e}")

        problematic = k8s.get_high_restart_pods(threshold=5)
        for p in problematic:
            repo.create_alert(cluster.id, p['namespace'],
                              f"Pod {p['pod_name']} restarted {p['restarts']} times", 'warning')

        # PVC alert checks
        try:
            from db.models import Alert
            pvcs = k8s.collect_pvc_metrics()
            pvc_names = {pvc['name'] for pvc in pvcs}

            active_pvc_alerts = (
                db.query(Alert)
                .filter(Alert.resolved == False, Alert.message.like('PVC %'))
                .all()
            )

            triggering_pvcs = set()
            for pvc in pvcs:
                if not pvc['bound']:
                    triggering_pvcs.add(pvc['name'])
                    existing = next((a for a in active_pvc_alerts
                                     if pvc['name'] in a.message and 'not bound' in a.message), None)
                    if not existing:
                        repo.create_alert(
                            cluster.id, pvc['namespace'],
                            f"PVC {pvc['name']} is not bound (phase: {pvc['phase']})",
                            'critical'
                        )
                if pvc['used_pct'] is not None:
                    if pvc['used_pct'] >= 90:
                        triggering_pvcs.add(pvc['name'])
                        existing = next((a for a in active_pvc_alerts
                                         if pvc['name'] in a.message and 'full' in a.message), None)
                        if not existing:
                            repo.create_alert(
                                cluster.id, pvc['namespace'],
                                f"PVC {pvc['name']} is {pvc['used_pct']}% full "
                                f"({pvc['actual_gib']:.2f}/{pvc['capacity_gib']:.2f} GiB)",
                                'critical'
                            )
                    elif pvc['used_pct'] >= 75:
                        triggering_pvcs.add(pvc['name'])
                        existing = next((a for a in active_pvc_alerts
                                         if pvc['name'] in a.message and 'full' in a.message), None)
                        if not existing:
                            repo.create_alert(
                                cluster.id, pvc['namespace'],
                                f"PVC {pvc['name']} is {pvc['used_pct']}% full "
                                f"({pvc['actual_gib']:.2f}/{pvc['capacity_gib']:.2f} GiB)",
                                'warning'
                            )

            resolved = 0
            for alert in active_pvc_alerts:
                alert_pvc = next(
                    (n for n in pvc_names if n in alert.message), None)
                if alert_pvc is None:
                    alert.resolved = True
                    resolved += 1
                    print(f"  ✅ Resolved (PVC gone): {alert.message[:60]}")
                elif alert_pvc not in triggering_pvcs:
                    alert.resolved = True
                    resolved += 1
                    print(f"  ✅ Resolved: {alert.message[:60]}")
            if resolved:
                db.commit()

            print(
                f"  PVC checks: {len(pvcs)} PVCs checked, {resolved} alerts resolved")
        except Exception as e:
            print(f"  Warning: PVC alert check failed: {e}")

        active_alerts = repo.get_active_alerts(cluster.id)
        print(f"\n{'='*50}")
        print(f"Done!")
        print(f"  Namespaces: {len(metrics)}")
        print(f"  Saved:      {saved}")
        print(f"  Alerts:     {len(active_alerts)}")
        print(f"{'='*50}\n")

        return True

    except Exception as e:
        print(f"Collector error: {e}")
        return False
    finally:
        db.close()


def run_daemon(interval=300):
    print(f"Daemon mode started, interval: {interval}s")
    while True:
        try:
            collect_once()
            print(f"Sleeping {interval}s...")
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nShutting down...")
            break
        except Exception as e:
            print(f"Error: {e}, retrying in 60s...")
            time.sleep(60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='KubePocket Collector')
    parser.add_argument('--daemon',   action='store_true')
    parser.add_argument('--interval', type=int, default=300)
    parser.add_argument('--context',  help='Kubernetes context')
    args = parser.parse_args()

    if args.daemon:
        run_daemon(args.interval)
    else:
        collect_once(args.context)
