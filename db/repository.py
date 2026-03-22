# db/repository.py
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from .models import Cluster, Metric, Alert


class MetricRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create_cluster(self, name, context):
        cluster = self.db.query(Cluster).filter(Cluster.name == name).first()
        if not cluster:
            cluster = Cluster(name=name, context=context)
            self.db.add(cluster)
            self.db.commit()
            self.db.refresh(cluster)
            print(f"✅ New cluster created: {name}")
        else:
            cluster.last_seen = datetime.utcnow()
            self.db.commit()
        return cluster

    def get_cluster_by_name(self, name: str):
        return self.db.query(Cluster).filter(Cluster.name == name).first()

    def get_all_clusters(self):
        return self.db.query(Cluster).order_by(Cluster.name).all()

    def save_metrics(self, cluster_id, metrics_data):
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
        print(f"✅ {saved_count} namespace metrics saved")
        return saved_count

    def get_latest_metrics(self, cluster_id=None, namespace=None, hours=24):
        query = self.db.query(Metric)

        if cluster_id:
            query = query.filter(Metric.cluster_id == cluster_id)
        if namespace:
            query = query.filter(Metric.namespace == namespace)

        since = datetime.utcnow() - timedelta(hours=hours)
        query = query.filter(Metric.timestamp >= since)

        return query.order_by(Metric.timestamp.desc()).all()

    def get_latest_per_namespace(self, cluster_id=None):
        """
        Returns the most recent metric row per namespace.
        When cluster_id is provided, only that cluster's data is returned.
        When cluster_id is None, returns latest per namespace across ALL clusters
        (used by the exporter when iterating clusters explicitly).
        """
        subquery = (
            self.db.query(
                Metric.namespace,
                Metric.cluster_id,
                func.max(Metric.timestamp).label('max_ts')
            )
        )
        if cluster_id is not None:
            subquery = subquery.filter(Metric.cluster_id == cluster_id)

        subquery = subquery.group_by(
            Metric.namespace, Metric.cluster_id
        ).subquery()

        return (
            self.db.query(Metric)
            .join(
                subquery,
                (Metric.namespace == subquery.c.namespace) &
                (Metric.cluster_id == subquery.c.cluster_id) &
                (Metric.timestamp == subquery.c.max_ts)
            )
            .all()
        )

    def create_alert(self, cluster_id, namespace, message, severity='warning'):
        alert = Alert(
            cluster_id=cluster_id,
            namespace=namespace,
            message=message,
            severity=severity
        )
        self.db.add(alert)
        self.db.commit()
        print(f"🚨 Alert created: {message}")
        return alert

    def get_active_alerts(self, cluster_id=None):
        query = self.db.query(Alert).filter(Alert.resolved == False)
        if cluster_id:
            query = query.filter(Alert.cluster_id == cluster_id)
        return query.all()
