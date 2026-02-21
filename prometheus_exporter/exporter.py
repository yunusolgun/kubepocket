#!/usr/bin/env python3
from prometheus_client import start_http_server, generate_latest, REGISTRY
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily
import time
import sys
import os
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.repository import MetricRepository
from db.models import Statistics, Metric  # Metric import eklendi!

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class KubePocketCollector:
    def __init__(self):
        logger.info("🚀 Starting KubePocket Collector...")
        self.repo = MetricRepository()
        
    def collect(self):
        try:
            logger.info("📡 Collecting metrics...")
            metrics = self.repo.get_latest_metrics(hours=1)
            
            if not metrics:
                logger.warning("⚠️ No metrics found!")
                yield GaugeMetricFamily('kubepocket_up', 'KubePocket exporter status', value=1)
                return
            
            logger.info(f"✅ Found {len(metrics)} namespaces with metrics")
            
            # CPU Gauge
            cpu_gauge = GaugeMetricFamily('kubepocket_namespace_cpu_cores', 'CPU usage (cores)', labels=['namespace', 'cluster'])
            
            # Memory Gauge
            memory_gauge = GaugeMetricFamily('kubepocket_namespace_memory_gib', 'Memory usage (GiB)', labels=['namespace', 'cluster'])
            
            # Anomaly metrics
            anomaly_gauge = GaugeMetricFamily('kubepocket_anomaly_score', 'Anomaly score (0-100)', labels=['namespace', 'metric', 'cluster'])
            
            # Forecast metrics
            forecast_cpu_gauge = GaugeMetricFamily('kubepocket_forecast_cpu_7d', 'CPU forecast 7 days', labels=['namespace', 'cluster'])
            
            cluster_name = 'minikube'
            
            for m in metrics:
                cpu_gauge.add_metric([m.namespace, cluster_name], m.total_cpu)
                memory_gauge.add_metric([m.namespace, cluster_name], m.total_memory)
                
                stats = self.repo.db.query(Statistics).filter(
                    Statistics.namespace == m.namespace
                ).order_by(Statistics.calculated_at.desc()).first()
                
                if stats and stats.std_dev > 0:
                    z_score = abs(m.total_cpu - stats.avg_value) / stats.std_dev
                    anomaly_score = min(100, z_score * 20)
                    anomaly_gauge.add_metric([m.namespace, 'cpu', cluster_name], anomaly_score)
                    
                    forecast_value = stats.avg_value + stats.trend_slope * 7
                    forecast_cpu_gauge.add_metric([m.namespace, cluster_name], max(0, forecast_value))
            
            yield cpu_gauge
            yield memory_gauge
            yield anomaly_gauge
            yield forecast_cpu_gauge
            yield GaugeMetricFamily('kubepocket_up', 'KubePocket exporter status', value=1)
            
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            yield GaugeMetricFamily('kubepocket_up', 'KubePocket exporter status', value=0)
    
    def close(self):
        self.repo.close()

def start_exporter(port=8001):
    from prometheus_client import make_wsgi_app
    from wsgiref.simple_server import make_server
    
    REGISTRY.register(KubePocketCollector())
    app = make_wsgi_app()
    httpd = make_server('0.0.0.0', port, app)
    logger.info(f"🚀 Prometheus exporter running at http://localhost:{port}/metrics")
    httpd.serve_forever()

if __name__ == "__main__":
    start_exporter()
