#!/usr/bin/env python3
# prometheus_exporter/exporter.py
from prometheus_client import REGISTRY
from prometheus_client.core import GaugeMetricFamily
from db.repository import MetricRepository
from db.models import Statistics, Metric, SessionLocal
import sys
import os
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Cluster adını environment variable'dan al.
# Helm values.yaml'da veya k8s configmap'te set edilir.
# Örnek: CLUSTER_NAME=production-eu-west-1
CLUSTER_NAME = os.getenv('CLUSTER_NAME', 'default')


class KubePocketCollector:
    """
    Prometheus custom collector.
    Her scrape isteğinde collect() çağrılır.
    Session her collect() çağrısında açılıp kapatılır —
    uzun ömürlü bağlantı tutmak exporter'lar için iyi pratik değil.
    """

    def collect(self):
        db = SessionLocal()
        try:
            logger.info("📡 Scraping metrics...")
            repo = MetricRepository(db)
            metrics = repo.get_latest_metrics(hours=1)

            if not metrics:
                logger.warning("⚠️ No metrics found in last 1 hour")
                yield GaugeMetricFamily('kubepocket_up', 'KubePocket exporter status', value=1)
                return

            logger.info(
                f"✅ Found {len(metrics)} metric records — cluster: {CLUSTER_NAME}")

            cpu_gauge = GaugeMetricFamily(
                'kubepocket_namespace_cpu_cores',
                'Total CPU request (cores) per namespace',
                labels=['namespace', 'cluster']
            )
            memory_gauge = GaugeMetricFamily(
                'kubepocket_namespace_memory_gib',
                'Total memory request (GiB) per namespace',
                labels=['namespace', 'cluster']
            )
            restart_gauge = GaugeMetricFamily(
                'kubepocket_namespace_restarts_total',
                'Total pod restarts per namespace',
                labels=['namespace', 'cluster']
            )
            anomaly_gauge = GaugeMetricFamily(
                'kubepocket_anomaly_score',
                'Anomaly score (0-100, higher = more anomalous)',
                labels=['namespace', 'metric_type', 'cluster']
            )
            forecast_gauge = GaugeMetricFamily(
                'kubepocket_forecast_cpu_7d',
                'Predicted CPU usage 7 days from now (cores)',
                labels=['namespace', 'cluster']
            )

            for m in metrics:
                labels = [m.namespace, CLUSTER_NAME]

                cpu_gauge.add_metric(labels, m.total_cpu)
                memory_gauge.add_metric(labels, m.total_memory)
                restart_gauge.add_metric(labels, m.total_restarts)

                # İstatistik varsa anomaly score ve forecast hesapla
                stats = (
                    db.query(Statistics)
                    .filter(
                        Statistics.namespace == m.namespace,
                        Statistics.metric_type == 'cpu'
                    )
                    .order_by(Statistics.calculated_at.desc())
                    .first()
                )

                if stats and stats.std_dev > 0:
                    z_score = abs(m.total_cpu - stats.avg_value) / \
                        stats.std_dev
                    anomaly_score = min(100.0, z_score * 20)
                    anomaly_gauge.add_metric(
                        [m.namespace, 'cpu', CLUSTER_NAME], anomaly_score)

                    forecast_value = stats.avg_value + (stats.trend_slope * 7)
                    forecast_gauge.add_metric(labels, max(0.0, forecast_value))

            yield cpu_gauge
            yield memory_gauge
            yield restart_gauge
            yield anomaly_gauge
            yield forecast_gauge
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
    logger.info(
        f"💾 Database: {os.getenv('DATABASE_PATH', '/app/data/kubepocket.db')}")

    httpd.serve_forever()


if __name__ == "__main__":
    port = int(os.getenv('EXPORTER_PORT', '8001'))
    start_exporter(port)
