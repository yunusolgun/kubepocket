#!/usr/bin/env python3
# reporter/simple_report.py
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.repository import MetricRepository
from datetime import datetime, timedelta
from collections import defaultdict

def print_report(hours=24):
    """Print report for the last X hours."""
    
    repo = MetricRepository()
    metrics = repo.get_latest_metrics(hours=hours)
    
    if not metrics:
        print("❌ No metrics found!")
        return
    
    print(f"\n{'='*60}")
    print(f"📊 KubePocket Report - Last {hours} Hours")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print('='*60)
    
    # Namespace summary
    ns_summary = defaultdict(lambda: {
        'cpu': 0, 'memory': 0, 'restarts': 0, 'samples': 0
    })
    
    for m in metrics:
        ns = m.namespace
        ns_summary[ns]['cpu'] += m.total_cpu
        ns_summary[ns]['memory'] += m.total_memory
        ns_summary[ns]['restarts'] += m.total_restarts
        ns_summary[ns]['samples'] += 1
    
    print(f"\n📁 Namespace Summary:")
    print(f"{'Namespace':<20} {'CPU (cores)':>12} {'Memory (Gi)':>12} {'Restarts':>10}")
    print('-'*60)
    
    for ns, data in ns_summary.items():
        avg_cpu = data['cpu'] / data['samples']
        avg_mem = data['memory'] / data['samples']
        print(f"{ns:<20} {avg_cpu:>12.2f} {avg_mem:>12.2f} {data['restarts']:>10}")
    
    # Active alerts
    alerts = repo.get_active_alerts()
    if alerts:
        print(f"\n🚨 Active Alerts:")
        for alert in alerts:
            print(f"   • {alert.message} [{alert.severity}]")
    
    print('='*60)
    repo.close()

if __name__ == "__main__":
    # Son 24 saat
    print_report(24)
