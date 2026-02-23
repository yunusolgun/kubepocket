#!/usr/bin/env python3
# prometheus_exporter/exporter.py
from prometheus_client import REGISTRY
from prometheus_client.core import GaugeMetricFamily
from collector.cost import calculate_relative_cost, detect_waste
from db.repository import MetricRepository
from db.models import Statistics, SessionLocal
import sys
import os
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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

            logger.info(
                f"✅ {len(metrics)} namespace — cluster: {CLUSTER_NAME}")

            # --- Namespace bazlı ---
            ns_cpu = GaugeMetricFamily('kubepocket_namespace_cpu_cores',
                                       'Total CPU request per namespace', labels=['namespace', 'cluster'])
            ns_memory = GaugeMetricFamily(
                'kubepocket_namespace_memory_gib', 'Total memory request per namespace', labels=['namespace', 'cluster'])
            ns_restarts = GaugeMetricFamily('kubepocket_namespace_restarts_total',
                                            'Total pod restarts per namespace', labels=['namespace', 'cluster'])
            ns_anomaly = GaugeMetricFamily(
                'kubepocket_anomaly_score', 'Namespace anomaly score (0-100)', labels=['namespace', 'metric_type', 'cluster'])
            ns_forecast = GaugeMetricFamily(
                'kubepocket_forecast_cpu_7d', 'CPU forecast 7 days', labels=['namespace', 'cluster'])

            # --- Pod bazlı ---
            pod_cpu = GaugeMetricFamily('kubepocket_pod_cpu_cores', 'CPU request per pod', labels=[
                                        'pod', 'namespace', 'cluster'])
            pod_memory = GaugeMetricFamily('kubepocket_pod_memory_gib', 'Memory request per pod', labels=[
                                           'pod', 'namespace', 'cluster'])
            pod_restarts = GaugeMetricFamily('kubepocket_pod_restarts_total', 'Restart count per pod', labels=[
                                             'pod', 'namespace', 'cluster'])
            pod_status = GaugeMetricFamily('kubepocket_pod_running', 'Pod running status (1=Running, 0=other)', labels=[
                                           'pod', 'namespace', 'status', 'cluster'])
            pod_age = GaugeMetricFamily('kubepocket_pod_age_hours', 'Pod age in hours', labels=[
                                        'pod', 'namespace', 'cluster'])
            pod_anomaly = GaugeMetricFamily(
                'kubepocket_pod_anomaly_score', 'Pod anomaly score (0-100)', labels=['pod', 'namespace', 'cluster'])
            pod_restart_score = GaugeMetricFamily(
                'kubepocket_pod_restart_anomaly', 'Pod restart anomaly (0-100)', labels=['pod', 'namespace', 'cluster'])
            pod_cpu_score = GaugeMetricFamily(
                'kubepocket_pod_cpu_anomaly', 'Pod CPU anomaly (0-100)', labels=['pod', 'namespace', 'cluster'])

            # --- Göreceli maliyet ---
            ns_cost_pct = GaugeMetricFamily(
                'kubepocket_namespace_cost_pct',
                'Namespace cost share in cluster (%)',
                labels=['namespace', 'cluster']
            )
            ns_cpu_pct = GaugeMetricFamily(
                'kubepocket_namespace_cpu_pct',
                'Namespace CPU share (%)',
                labels=['namespace', 'cluster']
            )
            ns_memory_pct = GaugeMetricFamily(
                'kubepocket_namespace_memory_pct',
                'Namespace memory share (%)',
                labels=['namespace', 'cluster']
            )

            # --- Waste tespiti ---
            pod_waste_score = GaugeMetricFamily(
                'kubepocket_pod_waste_score',
                'Pod resource waste score (0-100)',
                labels=['pod', 'namespace', 'cluster']
            )
            pod_waste_cpu = GaugeMetricFamily(
                'kubepocket_pod_waste_cpu_cores',
                'Wasted CPU amount (cores)',
                labels=['pod', 'namespace', 'cluster']
            )
            pod_waste_memory = GaugeMetricFamily(
                'kubepocket_pod_waste_memory_gib',
                'Wasted memory amount (GiB)',
                labels=['pod', 'namespace', 'cluster']
            )
            cluster_waste_pct = GaugeMetricFamily(
                'kubepocket_cluster_waste_pct',
                'Cluster-wide waste percentage (%)',
                labels=['cluster', 'resource']
            )

            # Namespace metrikleri
            for m in metrics:
                ns_labels = [m.namespace, CLUSTER_NAME]
                ns_cpu.add_metric(ns_labels, m.total_cpu)
                ns_memory.add_metric(ns_labels, m.total_memory)
                ns_restarts.add_metric(ns_labels, m.total_restarts)

                stats = (
                    db.query(Statistics)
                    .filter(Statistics.namespace == m.namespace, Statistics.metric_type == 'cpu')
                    .order_by(Statistics.calculated_at.desc())
                    .first()
                )
                if stats and stats.std_dev > 0:
                    z_score = abs(m.total_cpu - stats.avg_value) / \
                        stats.std_dev
                    ns_anomaly.add_metric(
                        [m.namespace, 'cpu', CLUSTER_NAME], min(100.0, z_score * 20))
                    forecast_value = stats.avg_value + (stats.trend_slope * 7)
                    ns_forecast.add_metric(ns_labels, max(0.0, forecast_value))

                ns_avg_cpu = m.total_cpu / max(len(m.pod_data), 1)

                for pod in m.pod_data:
                    pod_name = pod.get('name', '')
                    pod_ns = pod.get('namespace', m.namespace)
                    pod_labels = [pod_name, pod_ns, CLUSTER_NAME]

                    cpu_req = pod.get('cpu_request', 0)
                    restarts = pod.get('restart_count', 0)
                    status = pod.get('status', 'Unknown')

                    pod_cpu.add_metric(pod_labels, cpu_req)
                    pod_memory.add_metric(
                        pod_labels, pod.get('memory_request', 0))
                    pod_restarts.add_metric(pod_labels, restarts)
                    pod_age.add_metric(pod_labels, pod.get('age_hours', 0))
                    pod_status.add_metric(
                        [pod_name, pod_ns, status, CLUSTER_NAME], 1.0 if status == 'Running' else 0.0)

                    cpu_ratio = cpu_req / max(ns_avg_cpu, 0.001)
                    cpu_anom = min(100.0, max(0.0, (cpu_ratio - 1) * 30))
                    restart_anom = min(100.0, restarts * 10.0)
                    total_anom = (cpu_anom * 0.4) + (restart_anom * 0.6)

                    pod_anomaly.add_metric(pod_labels, round(total_anom, 2))
                    pod_cpu_score.add_metric(pod_labels, round(cpu_anom, 2))
                    pod_restart_score.add_metric(
                        pod_labels, round(restart_anom, 2))

            # Göreceli maliyet hesapla
            cost_data = calculate_relative_cost(metrics)
            for ns_data in cost_data.get('namespaces', []):
                ns_labels = [ns_data['namespace'], CLUSTER_NAME]
                ns_cost_pct.add_metric(ns_labels, ns_data['cost_pct'])
                ns_cpu_pct.add_metric(ns_labels, ns_data['cpu_pct'])
                ns_memory_pct.add_metric(ns_labels, ns_data['memory_pct'])

            # Waste tespiti
            waste_data = detect_waste(metrics)
            for wp in waste_data.get('waste_pods', []):
                pod_labels = [wp['pod'], wp['namespace'], CLUSTER_NAME]
                pod_waste_score.add_metric(pod_labels, wp['waste_score'])
                pod_waste_cpu.add_metric(pod_labels, wp['cpu_request'])
                pod_waste_memory.add_metric(
                    pod_labels, wp['memory_request_gib'])

            summary = waste_data.get('summary', {})
            if summary:
                cluster_waste_pct.add_metric(
                    [CLUSTER_NAME, 'cpu'], summary.get('wasted_cpu_pct', 0))
                cluster_waste_pct.add_metric(
                    [CLUSTER_NAME, 'memory'], summary.get('wasted_memory_pct', 0))

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
            yield ns_cost_pct
            yield ns_cpu_pct
            yield ns_memory_pct
            yield pod_waste_score
            yield pod_waste_cpu
            yield pod_waste_memory
            yield cluster_waste_pct
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

    httpd.serve_forever()


if __name__ == "__main__":
    port = int(os.getenv('EXPORTER_PORT', '8001'))
    start_exporter(port)
