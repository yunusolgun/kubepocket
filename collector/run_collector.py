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


def collect_once(context=None):
    print(f"\n{'='*50}")
    print(f"KubePocket Collector - {datetime.now()}")
    print('='*50)

    init_db()

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
