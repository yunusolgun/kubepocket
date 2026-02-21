#!/usr/bin/env python3
# collector/statistics.py
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.repository import MetricRepository
from db.models import Statistics, Alert
from datetime import datetime, timedelta
import numpy as np
from sklearn.linear_model import LinearRegression
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class StatisticsCalculator:
    def __init__(self):
        self.repo = MetricRepository()
    
    def calculate_statistics(self):
        """Calculate statistics for each namespace"""
        logger.info("📊 Calculating statistics...")
        
        # Get last 7 days of data
        since = datetime.utcnow() - timedelta(days=7)
        metrics = self.repo.db.query(Metric).filter(Metric.timestamp >= since).all()
        
        if len(metrics) < 10:
            logger.warning("⚠️ Insufficient data for statistics (need at least 10 records)")
            return
        
        # Group by namespace
        namespaces = {}
        for m in metrics:
            if m.namespace not in namespaces:
                namespaces[m.namespace] = {'cpu': [], 'memory': [], 'timestamps': []}
            
            namespaces[m.namespace]['cpu'].append(m.total_cpu)
            namespaces[m.namespace]['memory'].append(m.total_memory)
            namespaces[m.namespace]['timestamps'].append(m.timestamp.timestamp())
        
        # Calculate statistics for each namespace
        for ns, data in namespaces.items():
            self._calculate_namespace_stats(ns, data)
        
        logger.info(f"✅ Statistics calculated for {len(namespaces)} namespaces")
        self.repo.db.commit()
    
    def _calculate_namespace_stats(self, namespace, data):
        """Calculate statistics for a single namespace"""
        
        # CPU statistics
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
        self.repo.db.add(cpu_stats)
        
        # Memory statistics
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
        self.repo.db.add(memory_stats)
    
    def _calculate_trend(self, timestamps, values):
        """Calculate trend using linear regression"""
        if len(timestamps) < 2:
            return 0.0
        
        X = np.array(timestamps).reshape(-1, 1)
        y = np.array(values)
        
        model = LinearRegression()
        model.fit(X, y)
        
        return float(model.coef_[0])
    
    def detect_anomalies(self):
        """Detect anomalies using Z-score method"""
        logger.info("🚨 Detecting anomalies...")
        
        # Get last 1 hour of data
        recent = self.repo.get_latest_metrics(hours=1)
        
        for metric in recent:
            # Get latest statistics for this namespace
            cpu_stats = self.repo.db.query(Statistics).filter(
                Statistics.namespace == metric.namespace,
                Statistics.metric_type == 'cpu'
            ).order_by(Statistics.calculated_at.desc()).first()
            
            if cpu_stats and cpu_stats.std_dev > 0:
                # Calculate Z-score
                z_score = abs(metric.total_cpu - cpu_stats.avg_value) / cpu_stats.std_dev
                
                if z_score > 3:  # 3 sigma rule
                    self._create_anomaly_alert(
                        metric.namespace,
                        'cpu',
                        metric.total_cpu,
                        cpu_stats.avg_value,
                        z_score
                    )
                
                # Check trend
                if abs(cpu_stats.trend_slope) > 0.1:
                    direction = "increasing" if cpu_stats.trend_slope > 0 else "decreasing"
                    self._create_trend_alert(
                        metric.namespace,
                        'cpu',
                        cpu_stats.trend_slope,
                        direction
                    )
    
    def _create_anomaly_alert(self, namespace, metric_type, current, avg, z_score):
        """Create anomaly alert"""
        
        message = f"⚠️ Anomaly detected: {namespace} namespace {metric_type} usage is unusually high! "
        message += f"(Current: {current:.2f}, Average: {avg:.2f}, Z-Score: {z_score:.2f})"
        
        alert = Alert(
            namespace=namespace,
            message=message,
            severity='anomaly',
            created_at=datetime.utcnow()
        )
        self.repo.db.add(alert)
        logger.info(f"🚨 Anomaly alert created: {message}")
    
    def _create_trend_alert(self, namespace, metric_type, slope, direction):
        """Create trend alert"""
        
        message = f"📈 Trend detected: {namespace} namespace {metric_type} usage is consistently {direction} "
        message += f"(slope: {slope:.4f})"
        
        alert = Alert(
            namespace=namespace,
            message=message,
            severity='warning',
            created_at=datetime.utcnow()
        )
        self.repo.db.add(alert)
        logger.info(f"📊 Trend alert created: {message}")
    
    def forecast(self, namespace, metric_type, days=7):
        """Forecast future usage"""
        # Get last 30 days of data
        since = datetime.utcnow() - timedelta(days=30)
        metrics = self.repo.db.query(Metric).filter(
            Metric.namespace == namespace,
            Metric.timestamp >= since
        ).all()
        
        if len(metrics) < 5:
            return None
        
        # Calculate daily averages
        daily = {}
        for m in metrics:
            day = m.timestamp.strftime('%Y-%m-%d')
            if day not in daily:
                daily[day] = {'cpu': [], 'memory': []}
            
            if metric_type == 'cpu':
                daily[day]['cpu'].append(m.total_cpu)
            else:
                daily[day]['memory'].append(m.total_memory)
        
        # Prepare data for regression
        days_list = []
        values_list = []
        
        for day in sorted(daily.keys()):
            days_list.append(len(days_list))
            if metric_type == 'cpu':
                values_list.append(np.mean(daily[day]['cpu']))
            else:
                values_list.append(np.mean(daily[day]['memory']))
        
        if len(days_list) < 3:
            return None
        
        # Linear regression for forecasting
        X = np.array(days_list).reshape(-1, 1)
        y = np.array(values_list)
        
        model = LinearRegression()
        model.fit(X, y)
        
        # Forecast future days
        forecast_days = np.array(range(len(days_list), len(days_list) + days)).reshape(-1, 1)
        forecast_values = model.predict(forecast_days)
        
        return {
            'historical_days': days_list,
            'historical_values': values_list,
            'forecast_days': list(range(len(days_list), len(days_list) + days)),
            'forecast_values': forecast_values.tolist(),
            'trend': float(model.coef_[0]),
            'confidence': self._calculate_confidence(values_list, forecast_values)
        }
    
    def _calculate_confidence(self, historical, forecast):
        """Calculate forecast confidence (simplified R²)"""
        if len(historical) < 3:
            return 0.5
        
        # Simple confidence score based on volatility
        volatility = np.std(historical) / (np.mean(historical) + 0.01)
        confidence = max(0, min(1, 1 - volatility))
        
        return confidence
    
    def close(self):
        self.repo.close()

if __name__ == "__main__":
    calc = StatisticsCalculator()
    calc.calculate_statistics()
    calc.detect_anomalies()
    
    # Example forecast
    forecast = calc.forecast('default', 'cpu', days=7)
    if forecast:
        print(f"📈 CPU Forecast: {forecast['forecast_values']}")
        print(f"📊 Confidence: {forecast['confidence']:.2%}")
    
    calc.close()
