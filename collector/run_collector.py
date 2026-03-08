#!/usr/bin/env python3
# collector/run_collector.py
from db.models import init_db, SessionLocal
from db.repository import MetricRepository
from collector.event_collector import EventCollector
from collector.k8s_client import K8sClient
import sys
import os
import time
from datetime import datetime
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


def collect_once(context=None):
    print(f"\n{'='*50}")
    print(f"KubePocket Collector - {datetime.now()}")
    print('='*50)

    init_db()

    # ── License kontrolü ──────────────────────────────────────
    license = _get_license()
    if license is not None:
        if not license.valid:
            print(f"⚠️  License: {license.error}")
            print("   Running in Free tier mode (3 namespace limit)")
            from licensing.license import LicenseInfo
            license = LicenseInfo(valid=True)  # community defaults
        else:
            tier_label = license.tier.upper()
            ns_label = "unlimited" if license.is_unlimited_namespaces() else str(
                license.namespace_limit)
            print(
                f"🔑 License: {tier_label} — {license.customer} (namespaces: {ns_label})")
            if license.days_until_expiry() is not None and license.days_until_expiry() <= 30:
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

        cluster = repo.get_or_create_cluster(
            CLUSTER_NAME, context or 'in-cluster')

        print("\nCollecting metrics...")
        metrics = k8s.collect_all_metrics_with_usage()

        if not metrics:
            print("No metrics collected!")
            return False

        # Namespace limit kontrolü
        if license is not None and not license.is_unlimited_namespaces():
            if len(metrics) > license.namespace_limit:
                print(f"⚠️  Namespace limit: {license.namespace_limit} (found {len(metrics)}). "
                      f"Only first {license.namespace_limit} will be saved. "
                      f"Upgrade to Pro for unlimited namespaces.")
                metrics = metrics[:license.namespace_limit]

        saved = repo.save_metrics(cluster.id, metrics)

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

        # PVC alert kontrolleri
        try:
            from db.models import Alert
            pvcs = k8s.collect_pvc_metrics()
            pvc_names = {pvc['name'] for pvc in pvcs}

            # Mevcut aktif PVC alertlarını al
            active_pvc_alerts = (
                db.query(Alert)
                .filter(
                    Alert.resolved == False,
                    Alert.message.like('PVC %')
                )
                .all()
            )

            # Her PVC için durum kontrolü
            triggering_pvcs = set()
            for pvc in pvcs:
                # Unbound kontrolü
                if not pvc['bound']:
                    triggering_pvcs.add(pvc['name'])
                    # Aynı alert zaten var mı?
                    existing = next((a for a in active_pvc_alerts
                                     if pvc['name'] in a.message and 'not bound' in a.message), None)
                    if not existing:
                        repo.create_alert(
                            cluster.id, pvc['namespace'],
                            f"PVC {pvc['name']} is not bound (phase: {pvc['phase']})",
                            'critical'
                        )
                # Doluluk kontrolü
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

            # Artık geçerli olmayan PVC alertlarını resolve et
            resolved = 0
            for alert in active_pvc_alerts:
                # Hangi PVC'ye ait olduğunu bul
                alert_pvc = next(
                    (n for n in pvc_names if n in alert.message), None)
                if alert_pvc is None:
                    # PVC artık cluster'da yok — resolve et
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
    parser.add_argument('--daemon', action='store_true')
    parser.add_argument('--interval', type=int, default=300)
    parser.add_argument('--context', help='Kubernetes context')
    args = parser.parse_args()

    if args.daemon:
        run_daemon(args.interval)
    else:
        collect_once(args.context)
