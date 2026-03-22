#!/usr/bin/env python3
# prometheus_exporter/exporter.py
from sqlalchemy import func
from prometheus_client import REGISTRY
from prometheus_client.core import GaugeMetricFamily
from collector.k8s_client import K8sClient
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

            # ── Multi-cluster: iterate all known clusters ─────────────
            clusters = repo.get_all_clusters()
            if not clusters:
                logger.warning('No clusters found in DB')
                yield GaugeMetricFamily('kubepocket_up', 'KubePocket exporter status', value=1)
                return

            logger.info(f"Exporting metrics for {len(clusters)} cluster(s): "
                        f"{[c.name for c in clusters]}")

            # Metric families — shared across all clusters
            ns_cpu = GaugeMetricFamily('kubepocket_namespace_cpu_cores',
                                       'Total CPU request per namespace',           labels=['namespace', 'cluster'])
            ns_memory = GaugeMetricFamily('kubepocket_namespace_memory_gib',
                                          'Total memory request per namespace',        labels=['namespace', 'cluster'])
            ns_restarts = GaugeMetricFamily('kubepocket_namespace_restarts_total',
                                            'Total pod restarts per namespace',          labels=['namespace', 'cluster'])
            ns_anomaly = GaugeMetricFamily('kubepocket_anomaly_score',
                                           'Namespace anomaly score (0-100)',           labels=['namespace', 'metric_type', 'cluster'])
            ns_forecast = GaugeMetricFamily('kubepocket_forecast_cpu_7d',
                                            'CPU forecast 7 days',                       labels=['namespace', 'cluster'])
            pod_cpu = GaugeMetricFamily('kubepocket_pod_cpu_cores',              'CPU request per pod',
                                        labels=['pod', 'namespace', 'cluster'])
            pod_memory = GaugeMetricFamily('kubepocket_pod_memory_gib',             'Memory request per pod',                    labels=[
                                           'pod', 'namespace', 'cluster'])
            pod_restarts = GaugeMetricFamily('kubepocket_pod_restarts_total',
                                             'Restart count per pod',                     labels=['pod', 'namespace', 'cluster'])
            pod_status = GaugeMetricFamily('kubepocket_pod_running',                'Pod running status (1=Running, 0=other)',   labels=[
                                           'pod', 'namespace', 'status', 'cluster'])
            pod_age = GaugeMetricFamily('kubepocket_pod_age_hours',              'Pod age in hours',
                                        labels=['pod', 'namespace', 'cluster'])
            pod_anomaly = GaugeMetricFamily('kubepocket_pod_anomaly_score',          'Pod anomaly score (0-100)',
                                            labels=['pod', 'namespace', 'cluster', 'recommendation'])
            pod_rst_score = GaugeMetricFamily('kubepocket_pod_restart_anomaly',
                                              'Pod restart anomaly (0-100)',               labels=['pod', 'namespace', 'cluster'])
            pod_cpu_score = GaugeMetricFamily(
                'kubepocket_pod_cpu_anomaly',            'Pod CPU anomaly (0-100)',                   labels=['pod', 'namespace', 'cluster'])
            ns_cost_pct = GaugeMetricFamily('kubepocket_namespace_cost_pct',
                                            'Namespace cost share in cluster (%)',       labels=['namespace', 'cluster'])
            ns_cpu_pct = GaugeMetricFamily('kubepocket_namespace_cpu_pct',
                                           'Namespace CPU share (%)',                   labels=['namespace', 'cluster'])
            ns_mem_pct = GaugeMetricFamily('kubepocket_namespace_memory_pct',
                                           'Namespace memory share (%)',                labels=['namespace', 'cluster'])
            pod_waste_sc = GaugeMetricFamily('kubepocket_pod_waste_score',            'Pod resource waste score (0-100)',
                                             labels=['pod', 'namespace', 'cluster', 'recommendation'])
            pod_waste_cpu = GaugeMetricFamily('kubepocket_pod_waste_cpu_cores',
                                              'Wasted CPU amount (cores)',                 labels=['pod', 'namespace', 'cluster'])
            pod_waste_mem = GaugeMetricFamily('kubepocket_pod_waste_memory_gib',
                                              'Wasted memory amount (GiB)',                labels=['pod', 'namespace', 'cluster'])
            cl_waste_pct = GaugeMetricFamily('kubepocket_cluster_waste_pct',
                                             'Cluster-wide waste percentage (%)',         labels=['cluster', 'resource'])
            pod_cpu_act = GaugeMetricFamily('kubepocket_pod_cpu_actual_cores',
                                            'Actual CPU usage per pod (cores)',          labels=['pod', 'namespace', 'cluster'])
            pod_mem_act = GaugeMetricFamily('kubepocket_pod_memory_actual_gib',
                                            'Actual memory usage per pod (GiB)',         labels=['pod', 'namespace', 'cluster'])
            pod_cpu_eff = GaugeMetricFamily('kubepocket_pod_cpu_efficiency_pct',
                                            'CPU efficiency pct (actual/request)',       labels=['pod', 'namespace', 'cluster'])
            pod_mem_eff = GaugeMetricFamily('kubepocket_pod_memory_efficiency_pct',
                                            'Memory efficiency pct (actual/request)',    labels=['pod', 'namespace', 'cluster'])
            pvc_capacity = GaugeMetricFamily('kubepocket_pvc_capacity_gib',           'PVC capacity (GiB)',                        labels=[
                                             'namespace', 'pvc', 'storageclass', 'cluster'])
            pvc_requested = GaugeMetricFamily('kubepocket_pvc_requested_gib',          'PVC requested size (GiB)',                  labels=[
                                              'namespace', 'pvc', 'storageclass', 'cluster'])
            pvc_bound = GaugeMetricFamily('kubepocket_pvc_bound',                  'PVC bound status (1=Bound)',                labels=[
                                          'namespace', 'pvc', 'storageclass', 'cluster'])
            nd_cpu_cap = GaugeMetricFamily('kubepocket_node_cpu_capacity',
                                           'Node CPU capacity (cores)',                 labels=['node', 'cluster'])
            nd_cpu_alloc = GaugeMetricFamily('kubepocket_node_cpu_allocatable',
                                             'Node CPU allocatable (cores)',              labels=['node', 'cluster'])
            nd_cpu_req = GaugeMetricFamily('kubepocket_node_cpu_requested',
                                           'Node CPU requested by pods (cores)',        labels=['node', 'cluster'])
            nd_cpu_act = GaugeMetricFamily('kubepocket_node_cpu_actual',
                                           'Node CPU actual usage (cores)',             labels=['node', 'cluster'])
            nd_cpu_rp = GaugeMetricFamily('kubepocket_node_cpu_request_pct',
                                          'Node CPU request % of allocatable',        labels=['node', 'cluster'])
            nd_cpu_ap = GaugeMetricFamily('kubepocket_node_cpu_actual_pct',
                                          'Node CPU actual % of allocatable',         labels=['node', 'cluster'])
            nd_mem_cap = GaugeMetricFamily('kubepocket_node_mem_capacity_gib',
                                           'Node memory capacity (GiB)',                labels=['node', 'cluster'])
            nd_mem_alloc = GaugeMetricFamily('kubepocket_node_mem_allocatable_gib',
                                             'Node memory allocatable (GiB)',             labels=['node', 'cluster'])
            nd_mem_req = GaugeMetricFamily('kubepocket_node_mem_requested_gib',
                                           'Node memory requested by pods (GiB)',       labels=['node', 'cluster'])
            nd_mem_act = GaugeMetricFamily('kubepocket_node_mem_actual_gib',
                                           'Node memory actual usage (GiB)',            labels=['node', 'cluster'])
            nd_mem_rp = GaugeMetricFamily('kubepocket_node_mem_request_pct',
                                          'Node memory request % of allocatable',     labels=['node', 'cluster'])
            nd_mem_ap = GaugeMetricFamily('kubepocket_node_mem_actual_pct',
                                          'Node memory actual % of allocatable',      labels=['node', 'cluster'])
            nd_pods_run = GaugeMetricFamily('kubepocket_node_pods_running',
                                            'Number of pods on node',                   labels=['node', 'cluster'])
            nd_pods_pct = GaugeMetricFamily('kubepocket_node_pods_pct',
                                            'Pod count % of capacity',                  labels=['node', 'cluster'])
            nd_ready = GaugeMetricFamily('kubepocket_node_ready',
                                         'Node ready status (1=Ready)',              labels=['node', 'cluster'])
            pod_ev_cnt = GaugeMetricFamily('kubepocket_pod_event_count',            'Kubernetes event count per pod (last 24h)', labels=[
                                           'pod', 'namespace', 'event_type', 'cluster'])
            alert_metric = GaugeMetricFamily('kubepocket_active_alerts',              'Active unresolved alert count',             labels=[
                                             'namespace', 'severity', 'cluster'])
            alert_detail = GaugeMetricFamily('kubepocket_alert_detail',               'Alert detail with message',                 labels=[
                                             'namespace', 'severity', 'message', 'cluster'])

            # ── Per-cluster data collection ───────────────────────────
            for cluster in clusters:
                cname = cluster.name
                metrics = repo.get_latest_per_namespace(cluster_id=cluster.id)

                if not metrics:
                    logger.debug(f"No metrics for cluster: {cname}")
                    continue

                logger.info(f"  cluster={cname}: {len(metrics)} namespaces")

                _waste_pre = detect_waste(metrics)
                waste_rec_map = {
                    (wp['pod'], wp['namespace']): wp.get('recommendation', '')
                    for wp in _waste_pre.get('waste_pods', [])
                }

                for m in metrics:
                    ns_labels = [m.namespace, cname]
                    ns_cpu.add_metric(ns_labels, m.total_cpu)
                    ns_memory.add_metric(ns_labels, m.total_memory)
                    ns_restarts.add_metric(ns_labels, m.total_restarts)

                    stats = (
                        db.query(Statistics)
                        .filter(
                            Statistics.namespace == m.namespace,
                            Statistics.metric_type == 'cpu',
                            Statistics.cluster_id == cluster.id,
                        )
                        .order_by(Statistics.calculated_at.desc())
                        .first()
                    )
                    if stats and stats.std_dev and stats.std_dev > 0:
                        z_score = abs(
                            m.total_cpu - stats.avg_value) / stats.std_dev
                        ns_anomaly.add_metric(
                            [m.namespace, 'cpu', cname], min(100.0, z_score * 20))
                        forecast_value = stats.avg_value + \
                            (stats.trend_slope * 7)
                        ns_forecast.add_metric(
                            ns_labels, max(0.0, forecast_value))

                    ns_avg_cpu = m.total_cpu / max(len(m.pod_data), 1)

                    for pod in m.pod_data:
                        pod_name = pod.get('name', '')
                        pod_ns = pod.get('namespace', m.namespace)
                        plabels = [pod_name, pod_ns, cname]
                        cpu_req = pod.get('cpu_request', 0)
                        restarts = pod.get('restart_count', 0)
                        status = pod.get('status', 'Unknown')

                        pod_cpu.add_metric(plabels, cpu_req)
                        pod_memory.add_metric(
                            plabels, pod.get('memory_request', 0))
                        pod_restarts.add_metric(plabels, restarts)
                        pod_age.add_metric(plabels, pod.get('age_hours', 0))

                        cpu_act = pod.get('cpu_actual')
                        mem_act = pod.get('memory_actual_gib')
                        cpu_eff = pod.get('cpu_efficiency_pct')
                        mem_eff = pod.get('memory_efficiency_pct')
                        if cpu_act is not None:
                            pod_cpu_act.add_metric(plabels, cpu_act)
                        if mem_act is not None:
                            pod_mem_act.add_metric(plabels, mem_act)
                        if cpu_eff is not None:
                            pod_cpu_eff.add_metric(plabels, cpu_eff)
                        if mem_eff is not None:
                            pod_mem_eff.add_metric(plabels, mem_eff)

                        pod_status.add_metric([pod_name, pod_ns, status, cname],
                                              1.0 if status == 'Running' else 0.0)

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
                            [pod_name, pod_ns, cname, anomaly_rec], round(total_anom, 2))
                        pod_cpu_score.add_metric(plabels, round(cpu_anom, 2))
                        pod_rst_score.add_metric(
                            plabels, round(restart_anom, 2))

                # Cost
                cost_data = calculate_relative_cost(metrics)
                for ns_data in cost_data.get('namespaces', []):
                    nl = [ns_data['namespace'], cname]
                    ns_cost_pct.add_metric(nl, ns_data['cost_pct'])
                    ns_cpu_pct.add_metric(nl, ns_data['cpu_pct'])
                    ns_mem_pct.add_metric(nl, ns_data['memory_pct'])

                # Waste
                waste_data = detect_waste(metrics)
                for wp in waste_data.get('waste_pods', []):
                    rec = wp.get('recommendation', 'No recommendation')
                    pod_waste_sc.add_metric(
                        [wp['pod'], wp['namespace'], cname, rec], wp['waste_score'])
                    pod_waste_cpu.add_metric(
                        [wp['pod'], wp['namespace'], cname], wp['cpu_request'])
                    pod_waste_mem.add_metric(
                        [wp['pod'], wp['namespace'], cname], wp['memory_request_gib'])

                summary = waste_data.get('summary', {})
                if summary:
                    cl_waste_pct.add_metric(
                        [cname, 'cpu'],    summary.get('wasted_cpu_pct', 0))
                    cl_waste_pct.add_metric(
                        [cname, 'memory'], summary.get('wasted_memory_pct', 0))

                # PVC — only for the current (local) cluster
                if cname == CLUSTER_NAME:
                    try:
                        k8s = K8sClient()
                        pvc_data = k8s.collect_pvc_metrics()
                        for pv in pvc_data:
                            pl = [pv['namespace'], pv['name'],
                                  pv['storage_class'], cname]
                            pvc_capacity.add_metric(pl, pv['capacity_gib'])
                            pvc_requested.add_metric(pl, pv['requested_gib'])
                            pvc_bound.add_metric(
                                pl, 1.0 if pv['bound'] else 0.0)
                    except Exception as e:
                        logger.warning(f"PVC metrics error: {e}")

                    # Node metrics — only for local cluster
                    try:
                        node_data = k8s.collect_node_metrics()
                        for nd in node_data:
                            nl = [nd['name'], cname]
                            nd_cpu_cap.add_metric(nl, nd['cpu_capacity'])
                            nd_cpu_alloc.add_metric(nl, nd['cpu_allocatable'])
                            nd_cpu_req.add_metric(nl, nd['cpu_requested'])
                            nd_cpu_rp.add_metric(nl, nd['cpu_request_pct'])
                            nd_mem_cap.add_metric(nl, nd['mem_capacity_gib'])
                            nd_mem_alloc.add_metric(
                                nl, nd['mem_allocatable_gib'])
                            nd_mem_req.add_metric(nl, nd['mem_requested_gib'])
                            nd_mem_rp.add_metric(nl, nd['mem_request_pct'])
                            nd_pods_run.add_metric(nl, nd['pods_running'])
                            nd_pods_pct.add_metric(nl, nd['pods_pct'])
                            nd_ready.add_metric(
                                nl, 1.0 if nd['ready'] else 0.0)
                            if nd['cpu_actual'] is not None:
                                nd_cpu_act.add_metric(nl, nd['cpu_actual'])
                            if nd['cpu_actual_pct'] is not None:
                                nd_cpu_ap.add_metric(nl, nd['cpu_actual_pct'])
                            if nd['mem_actual_gib'] is not None:
                                nd_mem_act.add_metric(nl, nd['mem_actual_gib'])
                            if nd['mem_actual_pct'] is not None:
                                nd_mem_ap.add_metric(nl, nd['mem_actual_pct'])
                    except Exception as e:
                        logger.warning(f"Node metrics error: {e}")

                # Events
                since = datetime.utcnow() - timedelta(hours=24)
                kube_events = (
                    db.query(KubeEvent.pod_name, KubeEvent.namespace, KubeEvent.event_type,
                             func.sum(KubeEvent.count).label('total'))
                    .filter(KubeEvent.created_at >= since,
                            KubeEvent.cluster_id == cluster.id)
                    .group_by(KubeEvent.pod_name, KubeEvent.namespace, KubeEvent.event_type)
                    .all()
                )
                for ev in kube_events:
                    pod_ev_cnt.add_metric(
                        [ev.pod_name, ev.namespace, ev.event_type, cname],
                        float(ev.total or 0)
                    )

                # Alerts
                from db.models import Alert
                from sqlalchemy import func as sqlfunc
                active_counts = (
                    db.query(Alert.namespace, Alert.severity,
                             sqlfunc.count(Alert.id))
                    .filter(Alert.resolved == False, Alert.cluster_id == cluster.id)
                    .group_by(Alert.namespace, Alert.severity)
                    .all()
                )
                for namespace, severity, count in active_counts:
                    alert_metric.add_metric(
                        [namespace or '', severity or 'warning', cname], count)

                recent_alerts = (
                    db.query(Alert)
                    .filter(Alert.resolved == False, Alert.cluster_id == cluster.id)
                    .order_by(Alert.created_at.desc())
                    .limit(50)
                    .all()
                )
                for a in recent_alerts:
                    msg = (a.message or '')[:100]
                    alert_detail.add_metric(
                        [a.namespace or '', a.severity or 'warning', msg, cname], 1)

            # Yield all metric families
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
            yield pod_rst_score
            yield ns_cost_pct
            yield ns_cpu_pct
            yield ns_mem_pct
            yield pod_waste_sc
            yield pod_waste_cpu
            yield pod_waste_mem
            yield cl_waste_pct
            yield pvc_capacity
            yield pvc_requested
            yield pvc_bound
            yield nd_cpu_cap
            yield nd_cpu_alloc
            yield nd_cpu_req
            yield nd_cpu_act
            yield nd_cpu_rp
            yield nd_cpu_ap
            yield nd_mem_cap
            yield nd_mem_alloc
            yield nd_mem_req
            yield nd_mem_act
            yield nd_mem_rp
            yield nd_mem_ap
            yield nd_pods_run
            yield nd_pods_pct
            yield nd_ready
            yield pod_ev_cnt
            yield pod_cpu_act
            yield pod_mem_act
            yield pod_cpu_eff
            yield pod_mem_eff
            yield alert_metric
            yield alert_detail
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
