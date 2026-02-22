#!/usr/bin/env python3
# collector/statistics.py
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from db.repository import MetricRepository
from db.models import Statistics, Alert, Metric
from datetime import datetime, timedelta
import numpy as np
from sklearn.linear_model import LinearRegression
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StatisticsCalculator:
    def __init__(self, db: Session):
        self.db = db
        self.repo = MetricRepository(db)

    def calculate_statistics(self):
        """Son 7 günün verisinden namespace bazlı istatistik hesapla"""
        logger.info("📊 Calculating statistics...")

        since = datetime.utcnow() - timedelta(days=7)
        metrics = self.db.query(Metric).filter(Metric.timestamp >= since).all()

        if len(metrics) < 10:
            logger.warning(f"⚠️ Insufficient data ({len(metrics)} records, need 10)")
            return

        # Namespace bazlı grupla
        namespaces = {}
        for m in metrics:
            if m.namespace not in namespaces:
                namespaces[m.namespace] = {'cpu': [], 'memory': [], 'timestamps': []}
            namespaces[m.namespace]['cpu'].append(m.total_cpu)
            namespaces[m.namespace]['memory'].append(m.total_memory)
            namespaces[m.namespace]['timestamps'].append(m.timestamp.timestamp())

        for ns, data in namespaces.items():
            self._calculate_namespace_stats(ns, data)

        self.db.commit()
        logger.info(f"✅ Statistics calculated for {len(namespaces)} namespaces")

    def _calculate_namespace_stats(self, namespace, data):
        cpu_array = np.array(data['cpu'])
        cpu_stats = Statistics(
            namespace=namespace,
            metric_type='cpu',
            avg_value=float(np.mean(cpu_array)),
            std_dev=float(np.std(cpu_array)),
            min_value=float(np.min(cpu_array)),
            max_value=float(np.max(cpu_array)),
            trend_slope=self._calculate_trend(data['timestamps'], data['cpu']),
            calculated_at=datetime.utcnow()
        )
        self.db.add(cpu_stats)

        memory_array = np.array(data['memory'])
        memory_stats = Statistics(
            namespace=namespace,
            metric_type='memory',
            avg_value=float(np.mean(memory_array)),
            std_dev=float(np.std(memory_array)),
            min_value=float(np.min(memory_array)),
            max_value=float(np.max(memory_array)),
            trend_slope=self._calculate_trend(data['timestamps'], data['memory']),
            calculated_at=datetime.utcnow()
        )
        self.db.add(memory_stats)

    def _calculate_trend(self, timestamps, values):
        if len(timestamps) < 2:
            return 0.0
        X = np.array(timestamps).reshape(-1, 1)
        y = np.array(values)
        model = LinearRegression()
        model.fit(X, y)
        return float(model.coef_[0])

    def detect_anomalies(self):
        """Son 1 saatteki veride Z-score anomaly tespiti"""
        logger.info("🚨 Detecting anomalies...")

        recent = self.repo.get_latest_metrics(hours=1)

        for metric in recent:
            cpu_stats = (
                self.db.query(Statistics)
                .filter(
                    Statistics.namespace == metric.namespace,
                    Statistics.metric_type == 'cpu'
                )
                .order_by(Statistics.calculated_at.desc())
                .first()
            )

            if cpu_stats and cpu_stats.std_dev > 0:
                z_score = abs(metric.total_cpu - cpu_stats.avg_value) / cpu_stats.std_dev

                if z_score > 3:
                    self._create_anomaly_alert(
                        metric.namespace, 'cpu',
                        metric.total_cpu, cpu_stats.avg_value, z_score
                    )

                if abs(cpu_stats.trend_slope) > 0.1:
                    direction = "increasing" if cpu_stats.trend_slope > 0 else "decreasing"
                    self._create_trend_alert(metric.namespace, 'cpu', cpu_stats.trend_slope, direction)

        self.db.commit()

    def _create_anomaly_alert(self, namespace, metric_type, current, avg, z_score):
        message = (
            f"⚠️ Anomaly: {namespace}/{metric_type} unusually high! "
            f"(Current: {current:.2f}, Avg: {avg:.2f}, Z-Score: {z_score:.2f})"
        )
        self.db.add(Alert(
            namespace=namespace,
            message=message,
            severity='anomaly',
            created_at=datetime.utcnow()
        ))
        logger.info(f"🚨 {message}")

    def _create_trend_alert(self, namespace, metric_type, slope, direction):
        message = (
            f"📈 Trend: {namespace}/{metric_type} consistently {direction} "
            f"(slope: {slope:.4f})"
        )
        self.db.add(Alert(
            namespace=namespace,
            message=message,
            severity='warning',
            created_at=datetime.utcnow()
        ))
        logger.info(f"📊 {message}")

    def forecast(self, namespace, metric_type, days=7):
        """Gelecek N gün için tahmin"""
        since = datetime.utcnow() - timedelta(days=30)
        metrics = self.db.query(Metric).filter(
            Metric.namespace == namespace,
            Metric.timestamp >= since
        ).all()

        if len(metrics) < 5:
            return None

        daily = {}
        for m in metrics:
            day = m.timestamp.strftime('%Y-%m-%d')
            if day not in daily:
                daily[day] = []
            daily[day].append(m.total_cpu if metric_type == 'cpu' else m.total_memory)

        days_list, values_list = [], []
        for day in sorted(daily.keys()):
            days_list.append(len(days_list))
            values_list.append(float(np.mean(daily[day])))

        if len(days_list) < 3:
            return None

        X = np.array(days_list).reshape(-1, 1)
        y = np.array(values_list)
        model = LinearRegression()
        model.fit(X, y)

        forecast_x = np.array(range(len(days_list), len(days_list) + days)).reshape(-1, 1)
        forecast_values = model.predict(forecast_x)

        volatility = np.std(values_list) / (np.mean(values_list) + 0.01)
        confidence = max(0.0, min(1.0, 1 - volatility))

        return {
            'historical_days': days_list,
            'historical_values': values_list,
            'forecast_days': list(range(len(days_list), len(days_list) + days)),
            'forecast_values': forecast_values.tolist(),
            'trend': float(model.coef_[0]),
            'confidence': confidence
        }


    def get_pod_anomalies(self, namespace=None):
        """
        Pod bazlı anomaly tespiti.
        Her pod'un restart sayısını ve CPU request'ini
        namespace ortalamasıyla karşılaştırır.
        """
        recent = self.repo.get_latest_per_namespace()
        pod_anomalies = []

        for metric in recent:
            if namespace and metric.namespace != namespace:
                continue

            ns_avg_cpu = metric.total_cpu / max(len(metric.pod_data), 1)

            for pod in metric.pod_data:
                pod_cpu = pod.get('cpu_request', 0)
                restarts = pod.get('restart_count', 0)

                # CPU anomaly — namespace ortalamasının 3 katından fazla ise
                cpu_ratio = pod_cpu / max(ns_avg_cpu, 0.001)
                cpu_score = min(100.0, max(0.0, (cpu_ratio - 1) * 30))

                # Restart anomaly — 5+ restart yüksek risk
                restart_score = min(100.0, restarts * 10.0)

                # Genel skor — ikisinin ağırlıklı ortalaması
                anomaly_score = (cpu_score * 0.4) + (restart_score * 0.6)

                pod_anomalies.append({
                    'pod': pod.get('name', ''),
                    'namespace': metric.namespace,
                    'cpu_score': round(cpu_score, 2),
                    'restart_score': round(restart_score, 2),
                    'anomaly_score': round(anomaly_score, 2),
                    'cpu_request': pod_cpu,
                    'restarts': restarts,
                    'status': pod.get('status', 'Unknown')
                })

        return sorted(pod_anomalies, key=lambda x: x['anomaly_score'], reverse=True)
