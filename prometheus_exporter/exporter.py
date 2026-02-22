#!/usr/bin/env python3
# prometheus_exporter/exporter.py
import sys
import os
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import Statistics, SessionLocal
from db.repository import MetricRepository
from prometheus_client.core import GaugeMetricFamily
from prometheus_client import REGISTRY

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

CLUSTER_NAME = os.getenv('CLUSTER_NAME', 'default')


class KubePocketCollector:

    def collect(self):
        db = SessionLocal()
        try:
            logger.info("📡 Scraping metrics...")
            repo = MetricRepository(db)
            metrics = repo.get_latest_per_namespace()

            if not metrics:
                logger.warning("⚠️ No metrics found")
                yield GaugeMetricFamily('kubepocket_up', 'KubePocket exporter status', value=1)
                return

            logger.info(f"✅ {len(metrics)} namespace — cluster: {CLUSTER_NAME}")

            # --- Namespace bazlı ---
            ns_cpu = GaugeMetricFamily('kubepocket_namespace_cpu_cores', 'Total CPU request per namespace', labels=['namespace', 'cluster'])
            ns_memory = GaugeMetricFamily('kubepocket_namespace_memory_gib', 'Total memory request per namespace', labels=['namespace', 'cluster'])
            ns_restarts = GaugeMetricFamily('kubepocket_namespace_restarts_total', 'Total pod restarts per namespace', labels=['namespace', 'cluster'])
            ns_anomaly = GaugeMetricFamily('kubepocket_anomaly_score', 'Namespace anomaly score (0-100)', labels=['namespace', 'metric_type', 'cluster'])
            ns_forecast = GaugeMetricFamily('kubepocket_forecast_cpu_7d', 'CPU forecast 7 days', labels=['namespace', 'cluster'])

            # --- Pod bazlı ---
            pod_cpu = GaugeMetricFamily('kubepocket_pod_cpu_cores', 'CPU request per pod', labels=['pod', 'namespace', 'cluster'])
            pod_memory = GaugeMetricFamily('kubepocket_pod_memory_gib', 'Memory request per pod', labels=['pod', 'namespace', 'cluster'])
            pod_restarts = GaugeMetricFamily('kubepocket_pod_restarts_total', 'Restart count per pod', labels=['pod', 'namespace', 'cluster'])
            pod_status = GaugeMetricFamily('kubepocket_pod_running', 'Pod running status (1=Running, 0=other)', labels=['pod', 'namespace', 'status', 'cluster'])
            pod_age = GaugeMetricFamily('kubepocket_pod_age_hours', 'Pod age in hours', labels=['pod', 'namespace', 'cluster'])

            # --- Pod anomaly ---
            pod_anomaly = GaugeMetricFamily(
                'kubepocket_pod_anomaly_score',
                'Pod anomaly score (0-100) — restart + CPU bazlı',
                labels=['pod', 'namespace', 'cluster']
            )
            pod_restart_score = GaugeMetricFamily(
                'kubepocket_pod_restart_anomaly',
                'Pod restart anomaly contribution (0-100)',
                labels=['pod', 'namespace', 'cluster']
            )
            pod_cpu_score = GaugeMetricFamily(
                'kubepocket_pod_cpu_anomaly',
                'Pod CPU anomaly contribution (0-100)',
                labels=['pod', 'namespace', 'cluster']
            )

            for m in metrics:
                ns_labels = [m.namespace, CLUSTER_NAME]

                # Namespace toplamları
                ns_cpu.add_metric(ns_labels, m.total_cpu)
                ns_memory.add_metric(ns_labels, m.total_memory)
                ns_restarts.add_metric(ns_labels, m.total_restarts)

                # Namespace anomaly & forecast
                stats = (
                    db.query(Statistics)
                    .filter(Statistics.namespace == m.namespace, Statistics.metric_type == 'cpu')
                    .order_by(Statistics.calculated_at.desc())
                    .first()
                )
                if stats and stats.std_dev > 0:
                    z_score = abs(m.total_cpu - stats.avg_value) / stats.std_dev
                    ns_anomaly.add_metric([m.namespace, 'cpu', CLUSTER_NAME], min(100.0, z_score * 20))
                    forecast_value = stats.avg_value + (stats.trend_slope * 7)
                    ns_forecast.add_metric(ns_labels, max(0.0, forecast_value))

                # Namespace'deki pod başına ortalama CPU
                pod_count = max(len(m.pod_data), 1)
                ns_avg_cpu = m.total_cpu / pod_count

                # Pod bazlı metrikler
                for pod in m.pod_data:
                    pod_name = pod.get('name', '')
                    pod_ns = pod.get('namespace', m.namespace)
                    pod_labels = [pod_name, pod_ns, CLUSTER_NAME]

                    cpu_req = pod.get('cpu_request', 0)
                    restarts = pod.get('restart_count', 0)
                    status = pod.get('status', 'Unknown')

                    pod_cpu.add_metric(pod_labels, cpu_req)
                    pod_memory.add_metric(pod_labels, pod.get('memory_request', 0))
                    pod_restarts.add_metric(pod_labels, restarts)
                    pod_age.add_metric(pod_labels, pod.get('age_hours', 0))
                    pod_status.add_metric([pod_name, pod_ns, status, CLUSTER_NAME], 1.0 if status == 'Running' else 0.0)

                    # Pod anomaly score hesapla
                    # CPU: namespace ortalamasına göre ne kadar sapıyor
                    cpu_ratio = cpu_req / max(ns_avg_cpu, 0.001)
                    cpu_anom = min(100.0, max(0.0, (cpu_ratio - 1) * 30))

                    # Restart: her restart 10 puan, max 100
                    restart_anom = min(100.0, restarts * 10.0)

                    # Genel: restart ağırlıklı (crash daha kritik)
                    total_anom = (cpu_anom * 0.4) + (restart_anom * 0.6)

                    pod_anomaly.add_metric(pod_labels, round(total_anom, 2))
                    pod_cpu_score.add_metric(pod_labels, round(cpu_anom, 2))
                    pod_restart_score.add_metric(pod_labels, round(restart_anom, 2))

            yield ns_cpu
            yield ns_memory
            yield ns_restarts
            yield ns_anomaly
            yield ns_forecast
            yield pod_cpu
            yield pod_memory
            yield pod_restarts
            yield pod_status
            yield pod_age
            yield pod_anomaly
            yield pod_cpu_score
            yield pod_restart_score
            yield GaugeMetricFamily('kubepocket_up', 'KubePocket exporter status', value=1)

        except Exception as e:
            logger.error(f"❌ Collect error: {e}", exc_info=True)
            yield GaugeMetricFamily('kubepocket_up', 'KubePocket exporter status', value=0)
        finally:
            db.close()


def start_exporter(port: int = 8001):
    from prometheus_client import make_wsgi_app
    from wsgiref.simple_server import make_server

    REGISTRY.register(KubePocketCollector())
    app = make_wsgi_app()
    httpd = make_server('0.0.0.0', port, app)

    logger.info(f"🚀 Prometheus exporter listening on :{port}/metrics")
    logger.info(f"🏷️  Cluster label: {CLUSTER_NAME}")
    logger.info(f"💾 Database: {os.getenv('DATABASE_PATH', '/data/kubepocket.db')}")

    httpd.serve_forever()


if __name__ == "__main__":
    port = int(os.getenv('EXPORTER_PORT', '8001'))
    start_exporter(port)
