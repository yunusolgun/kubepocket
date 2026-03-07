#!/usr/bin/env python3
# prometheus_exporter/exporter.py
from sqlalchemy import func
from prometheus_client import REGISTRY
from prometheus_client.core import GaugeMetricFamily
from collector.cost import calculate_relative_cost, detect_waste
from db.repository import MetricRepository
from db.models import Statistics, KubeEvent, SessionLocal
import sys
import os
import logging
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CLUSTER_NAME = os.getenv('CLUSTER_NAME', 'default')


class KubePocketCollector:

    def collect(self):
        db = SessionLocal()
        try:
            logger.info('Scraping metrics...')
            repo = MetricRepository(db)
            metrics = repo.get_latest_per_namespace()

            if not metrics:
                logger.warning('No metrics found')
                yield GaugeMetricFamily('kubepocket_up', 'KubePocket exporter status', value=1)
                return

            logger.info(f"{len(metrics)} namespaces — cluster: {CLUSTER_NAME}")

            ns_cpu = GaugeMetricFamily('kubepocket_namespace_cpu_cores',
                                       'Total CPU request per namespace',    labels=['namespace', 'cluster'])
            ns_memory = GaugeMetricFamily('kubepocket_namespace_memory_gib',
                                          'Total memory request per namespace', labels=['namespace', 'cluster'])
            ns_restarts = GaugeMetricFamily('kubepocket_namespace_restarts_total',
                                            'Total pod restarts per namespace',   labels=['namespace', 'cluster'])
            ns_anomaly = GaugeMetricFamily('kubepocket_anomaly_score',
                                           'Namespace anomaly score (0-100)',    labels=['namespace', 'metric_type', 'cluster'])
            ns_forecast = GaugeMetricFamily(
                'kubepocket_forecast_cpu_7d',          'CPU forecast 7 days',               labels=['namespace', 'cluster'])
            pod_cpu = GaugeMetricFamily('kubepocket_pod_cpu_cores',        'CPU request per pod',
                                        labels=['pod', 'namespace', 'cluster'])
            pod_memory = GaugeMetricFamily('kubepocket_pod_memory_gib',       'Memory request per pod',                    labels=[
                                           'pod', 'namespace', 'cluster'])
            pod_restarts = GaugeMetricFamily('kubepocket_pod_restarts_total',   'Restart count per pod',                     labels=[
                                             'pod', 'namespace', 'cluster'])
            pod_status = GaugeMetricFamily('kubepocket_pod_running',          'Pod running status (1=Running, 0=other)',    labels=[
                                           'pod', 'namespace', 'status', 'cluster'])
            pod_age = GaugeMetricFamily('kubepocket_pod_age_hours',        'Pod age in hours',
                                        labels=['pod', 'namespace', 'cluster'])
            pod_anomaly = GaugeMetricFamily('kubepocket_pod_anomaly_score',    'Pod anomaly score (0-100)',
                                            labels=['pod', 'namespace', 'cluster', 'recommendation'])
            pod_restart_score = GaugeMetricFamily(
                'kubepocket_pod_restart_anomaly',  'Pod restart anomaly (0-100)',               labels=['pod', 'namespace', 'cluster'])
            pod_cpu_score = GaugeMetricFamily(
                'kubepocket_pod_cpu_anomaly',      'Pod CPU anomaly (0-100)',                   labels=['pod', 'namespace', 'cluster'])
            ns_cost_pct = GaugeMetricFamily(
                'kubepocket_namespace_cost_pct',   'Namespace cost share in cluster (%)',       labels=['namespace', 'cluster'])
            ns_cpu_pct = GaugeMetricFamily(
                'kubepocket_namespace_cpu_pct',    'Namespace CPU share (%)',                   labels=['namespace', 'cluster'])
            ns_memory_pct = GaugeMetricFamily(
                'kubepocket_namespace_memory_pct', 'Namespace memory share (%)',                labels=['namespace', 'cluster'])
            pod_waste_score = GaugeMetricFamily('kubepocket_pod_waste_score',      'Pod resource waste score (0-100)',
                                                labels=['pod', 'namespace', 'cluster', 'recommendation'])
            pod_waste_cpu = GaugeMetricFamily(
                'kubepocket_pod_waste_cpu_cores',  'Wasted CPU amount (cores)',                 labels=['pod', 'namespace', 'cluster'])
            pod_waste_memory = GaugeMetricFamily(
                'kubepocket_pod_waste_memory_gib', 'Wasted memory amount (GiB)',               labels=['pod', 'namespace', 'cluster'])
            cluster_waste_pct = GaugeMetricFamily(
                'kubepocket_cluster_waste_pct',    'Cluster-wide waste percentage (%)',        labels=['cluster', 'resource'])
            pod_cpu_actual = GaugeMetricFamily(
                'kubepocket_pod_cpu_actual_cores',      'Actual CPU usage per pod (cores)',        labels=['pod', 'namespace', 'cluster'])
            pod_mem_actual = GaugeMetricFamily('kubepocket_pod_memory_actual_gib',
                                               'Actual memory usage per pod (GiB)',       labels=['pod', 'namespace', 'cluster'])
            pod_cpu_eff = GaugeMetricFamily('kubepocket_pod_cpu_efficiency_pct',
                                            'CPU efficiency pct (actual/request)',     labels=['pod', 'namespace', 'cluster'])
            pod_mem_eff = GaugeMetricFamily('kubepocket_pod_memory_efficiency_pct',
                                            'Memory efficiency pct (actual/request)', labels=['pod', 'namespace', 'cluster'])
            node_cpu_cap = GaugeMetricFamily(
                'kubepocket_node_cpu_capacity',       'Node CPU capacity (cores)',              labels=['node', 'cluster'])
            node_cpu_alloc = GaugeMetricFamily(
                'kubepocket_node_cpu_allocatable',    'Node CPU allocatable (cores)',           labels=['node', 'cluster'])
            node_cpu_req = GaugeMetricFamily(
                'kubepocket_node_cpu_requested',      'Node CPU requested by pods (cores)',     labels=['node', 'cluster'])
            node_cpu_actual = GaugeMetricFamily(
                'kubepocket_node_cpu_actual',         'Node CPU actual usage (cores)',          labels=['node', 'cluster'])
            node_cpu_req_pct = GaugeMetricFamily(
                'kubepocket_node_cpu_request_pct',    'Node CPU request % of allocatable',     labels=['node', 'cluster'])
            node_cpu_act_pct = GaugeMetricFamily(
                'kubepocket_node_cpu_actual_pct',     'Node CPU actual % of allocatable',      labels=['node', 'cluster'])
            node_mem_cap = GaugeMetricFamily(
                'kubepocket_node_mem_capacity_gib',   'Node memory capacity (GiB)',             labels=['node', 'cluster'])
            node_mem_alloc = GaugeMetricFamily(
                'kubepocket_node_mem_allocatable_gib', 'Node memory allocatable (GiB)',          labels=['node', 'cluster'])
            node_mem_req = GaugeMetricFamily(
                'kubepocket_node_mem_requested_gib',  'Node memory requested by pods (GiB)',   labels=['node', 'cluster'])
            node_mem_actual = GaugeMetricFamily(
                'kubepocket_node_mem_actual_gib',     'Node memory actual usage (GiB)',        labels=['node', 'cluster'])
            node_mem_req_pct = GaugeMetricFamily(
                'kubepocket_node_mem_request_pct',    'Node memory request % of allocatable',  labels=['node', 'cluster'])
            node_mem_act_pct = GaugeMetricFamily(
                'kubepocket_node_mem_actual_pct',     'Node memory actual % of allocatable',   labels=['node', 'cluster'])
            node_pods_run = GaugeMetricFamily(
                'kubepocket_node_pods_running',       'Number of pods on node',                labels=['node', 'cluster'])
            node_pods_pct = GaugeMetricFamily(
                'kubepocket_node_pods_pct',           'Pod count % of capacity',               labels=['node', 'cluster'])
            node_ready = GaugeMetricFamily(
                'kubepocket_node_ready',              'Node ready status (1=Ready)',            labels=['node', 'cluster'])
            pod_startup = GaugeMetricFamily('kubepocket_pod_startup_seconds',
                                            'Pod startup latency seconds (Pending->Running)', labels=['pod', 'namespace', 'cluster'])
            pod_event_count = GaugeMetricFamily('kubepocket_pod_event_count',            'Kubernetes event count per pod (last 24h)', labels=[
                                                'pod', 'namespace', 'event_type', 'cluster'])

            _waste_pre = detect_waste(metrics)
            waste_rec_map = {
                (wp['pod'], wp['namespace']): wp.get('recommendation', '')
                for wp in _waste_pre.get('waste_pods', [])
            }

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

                    startup = pod.get('startup_seconds')
                    if startup is not None:
                        pod_startup.add_metric(pod_labels, startup)

                    cpu_act = pod.get('cpu_actual')
                    mem_act = pod.get('memory_actual_gib')
                    cpu_eff = pod.get('cpu_efficiency_pct')
                    mem_eff = pod.get('memory_efficiency_pct')
                    if cpu_act is not None:
                        pod_cpu_actual.add_metric(pod_labels, cpu_act)
                    if mem_act is not None:
                        pod_mem_actual.add_metric(pod_labels, mem_act)
                    if cpu_eff is not None:
                        pod_cpu_eff.add_metric(pod_labels, cpu_eff)
                    if mem_eff is not None:
                        pod_mem_eff.add_metric(pod_labels, mem_eff)

                    pod_status.add_metric(
                        [pod_name, pod_ns, status, CLUSTER_NAME], 1.0 if status == 'Running' else 0.0)

                    cpu_ratio = cpu_req / max(ns_avg_cpu, 0.001)
                    cpu_anom = min(100.0, max(0.0, (cpu_ratio - 1) * 30))
                    restart_anom = min(100.0, restarts * 10.0)
                    total_anom = (cpu_anom * 0.4) + (restart_anom * 0.6)

                    if restart_anom >= 60:
                        anomaly_rec = f'Critical: {restarts} restarts — pod is unstable, check logs immediately'
                    elif restart_anom >= 30:
                        anomaly_rec = f'{restarts} restarts detected — investigate application crashes'
                    elif restart_anom > 0 and cpu_anom == 0:
                        anomaly_rec = f'{restarts} restarts — likely memory or liveness probe issue'
                    elif cpu_anom >= 60:
                        anomaly_rec = f'CPU is {cpu_ratio:.1f}x namespace average — possible runaway process or missing limit'
                    elif cpu_anom >= 30:
                        anomaly_rec = f'CPU {cpu_ratio:.1f}x above average — monitor for sustained spike'
                    elif cpu_anom > 0 and restart_anom > 0:
                        anomaly_rec = f'Both CPU spike and {restarts} restarts — likely thrashing under load'
                    else:
                        anomaly_rec = f'Anomaly score {round(total_anom, 1)} — monitor closely'

                    pod_anomaly.add_metric(
                        [pod_name, pod_ns, CLUSTER_NAME, anomaly_rec], round(total_anom, 2))
                    pod_cpu_score.add_metric(pod_labels, round(cpu_anom, 2))
                    pod_restart_score.add_metric(
                        pod_labels, round(restart_anom, 2))

            cost_data = calculate_relative_cost(metrics)
            for ns_data in cost_data.get('namespaces', []):
                ns_labels = [ns_data['namespace'], CLUSTER_NAME]
                ns_cost_pct.add_metric(ns_labels, ns_data['cost_pct'])
                ns_cpu_pct.add_metric(ns_labels, ns_data['cpu_pct'])
                ns_memory_pct.add_metric(ns_labels, ns_data['memory_pct'])

            waste_data = detect_waste(metrics)
            for wp in waste_data.get('waste_pods', []):
                rec = wp.get('recommendation', 'No recommendation')
                pod_waste_score.add_metric(
                    [wp['pod'], wp['namespace'], CLUSTER_NAME, rec], wp['waste_score'])
                pod_labels = [wp['pod'], wp['namespace'], CLUSTER_NAME]
                pod_waste_cpu.add_metric(pod_labels, wp['cpu_request'])
                pod_waste_memory.add_metric(
                    pod_labels, wp['memory_request_gib'])

            summary = waste_data.get('summary', {})
            if summary:
                cluster_waste_pct.add_metric(
                    [CLUSTER_NAME, 'cpu'],    summary.get('wasted_cpu_pct', 0))
                cluster_waste_pct.add_metric(
                    [CLUSTER_NAME, 'memory'], summary.get('wasted_memory_pct', 0))

            # Node metrikleri
            try:
                from collector.k8s_client import K8sClient
                k8s = K8sClient()
                node_data = k8s.collect_node_metrics()
                for nd in node_data:
                    nl = [nd['name'], CLUSTER_NAME]
                    node_cpu_cap.add_metric(nl, nd['cpu_capacity'])
                    node_cpu_alloc.add_metric(nl, nd['cpu_allocatable'])
                    node_cpu_req.add_metric(nl, nd['cpu_requested'])
                    node_cpu_req_pct.add_metric(nl, nd['cpu_request_pct'])
                    node_mem_cap.add_metric(nl, nd['mem_capacity_gib'])
                    node_mem_alloc.add_metric(nl, nd['mem_allocatable_gib'])
                    node_mem_req.add_metric(nl, nd['mem_requested_gib'])
                    node_mem_req_pct.add_metric(nl, nd['mem_request_pct'])
                    node_pods_run.add_metric(nl, nd['pods_running'])
                    node_pods_pct.add_metric(nl, nd['pods_pct'])
                    node_ready.add_metric(nl, 1.0 if nd['ready'] else 0.0)
                    if nd['cpu_actual'] is not None:
                        node_cpu_actual.add_metric(nl, nd['cpu_actual'])
                    if nd['cpu_actual_pct'] is not None:
                        node_cpu_act_pct.add_metric(nl, nd['cpu_actual_pct'])
                    if nd['mem_actual_gib'] is not None:
                        node_mem_actual.add_metric(nl, nd['mem_actual_gib'])
                    if nd['mem_actual_pct'] is not None:
                        node_mem_act_pct.add_metric(nl, nd['mem_actual_pct'])
            except Exception as e:
                logger.warning(f"Node metrics error: {e}")

            since = datetime.utcnow() - timedelta(hours=24)
            kube_events = (
                db.query(KubeEvent.pod_name, KubeEvent.namespace, KubeEvent.event_type,
                         func.sum(KubeEvent.count).label('total'))
                .filter(KubeEvent.created_at >= since)
                .group_by(KubeEvent.pod_name, KubeEvent.namespace, KubeEvent.event_type)
                .all()
            )
            for ev in kube_events:
                pod_event_count.add_metric(
                    [ev.pod_name, ev.namespace, ev.event_type, CLUSTER_NAME],
                    float(ev.total or 0)
                )

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
            yield node_cpu_cap
            yield node_cpu_alloc
            yield node_cpu_req
            yield node_cpu_actual
            yield node_cpu_req_pct
            yield node_cpu_act_pct
            yield node_mem_cap
            yield node_mem_alloc
            yield node_mem_req
            yield node_mem_actual
            yield node_mem_req_pct
            yield node_mem_act_pct
            yield node_pods_run
            yield node_pods_pct
            yield node_ready
            yield pod_startup
            yield pod_event_count
            yield pod_cpu_actual
            yield pod_mem_actual
            yield pod_cpu_eff
            yield pod_mem_eff
            yield GaugeMetricFamily('kubepocket_up', 'KubePocket exporter status', value=1)

        except Exception as e:
            logger.error(f"Collect error: {e}", exc_info=True)
            yield GaugeMetricFamily('kubepocket_up', 'KubePocket exporter status', value=0)
        finally:
            db.close()


def start_exporter(port: int = 8001):
    from prometheus_client import make_wsgi_app
    from wsgiref.simple_server import make_server

    REGISTRY.register(KubePocketCollector())
    app = make_wsgi_app()
    httpd = make_server('0.0.0.0', port, app)
    logger.info(
        f"Prometheus exporter listening on :{port}/metrics — cluster: {CLUSTER_NAME}")
    httpd.serve_forever()


if __name__ == "__main__":
    port = int(os.getenv('EXPORTER_PORT', '8001'))
    start_exporter(port)
