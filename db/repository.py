# db/repository.py
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from .models import Cluster, Metric, Alert


class MetricRepository:
    def __init__(self, db: Session):
        """
        db parametresi zorunlu — FastAPI Depends(get_db) üzerinden gelir.
        Repository kendi session açmaz, dışarıdan alır.
        """
        self.db = db

    def get_or_create_cluster(self, name, context):
        """Cluster'ı bul veya oluştur"""
        cluster = self.db.query(Cluster).filter(Cluster.name == name).first()
        if not cluster:
            cluster = Cluster(name=name, context=context)
            self.db.add(cluster)
            self.db.commit()
            self.db.refresh(cluster)
            print(f"✅ Yeni cluster oluşturuldu: {name}")
        return cluster

    def save_metrics(self, cluster_id, metrics_data):
        """Metrikleri veritabanına kaydet"""
        saved_count = 0
        for ns_data in metrics_data:
            metric = Metric(
                cluster_id=cluster_id,
                namespace=ns_data['namespace'],
                pod_data=ns_data['pods'],
                total_cpu=ns_data['total_cpu_request'],
                total_memory=ns_data['total_memory_request'],
                total_restarts=ns_data['total_restarts']
            )
            self.db.add(metric)
            saved_count += 1

        self.db.commit()
        print(f"✅ {saved_count} namespace metriği kaydedildi")
        return saved_count

    def get_latest_metrics(self, cluster_id=None, namespace=None, hours=24):
        """Son X saatlik metrikleri getir"""
        query = self.db.query(Metric)

        if cluster_id:
            query = query.filter(Metric.cluster_id == cluster_id)
        if namespace:
            query = query.filter(Metric.namespace == namespace)

        since = datetime.utcnow() - timedelta(hours=hours)
        query = query.filter(Metric.timestamp >= since)

        return query.order_by(Metric.timestamp.desc()).all()

    def create_alert(self, cluster_id, namespace, message, severity='warning'):
        """Alert oluştur"""
        alert = Alert(
            cluster_id=cluster_id,
            namespace=namespace,
            message=message,
            severity=severity
        )
        self.db.add(alert)
        self.db.commit()
        print(f"🚨 Alert oluşturuldu: {message}")
        return alert

    def get_active_alerts(self, cluster_id=None):
        """Çözülmemiş alertleri getir"""
        query = self.db.query(Alert).filter(Alert.resolved == False)
        if cluster_id:
            query = query.filter(Alert.cluster_id == cluster_id)
        return query.all()
