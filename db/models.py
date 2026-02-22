# db/models.py
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, JSON, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

Base = declarative_base()


class Cluster(Base):
    __tablename__ = 'clusters'

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    context = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


class Metric(Base):
    __tablename__ = 'metrics'

    id = Column(Integer, primary_key=True)
    cluster_id = Column(Integer, ForeignKey('clusters.id'))
    namespace = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)
    pod_data = Column(JSON)
    total_cpu = Column(Float)
    total_memory = Column(Float)
    total_restarts = Column(Integer)


class Alert(Base):
    __tablename__ = 'alerts'

    id = Column(Integer, primary_key=True)
    cluster_id = Column(Integer, ForeignKey('clusters.id'))
    namespace = Column(String)
    message = Column(String)
    severity = Column(String)  # 'warning', 'critical', 'anomaly'
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Statistics(Base):
    __tablename__ = 'statistics'

    id = Column(Integer, primary_key=True)
    cluster_id = Column(Integer, ForeignKey('clusters.id'))
    namespace = Column(String)
    metric_type = Column(String)  # 'cpu', 'memory', 'restarts'
    avg_value = Column(Float)
    std_dev = Column(Float)
    min_value = Column(Float)
    max_value = Column(Float)
    trend_slope = Column(Float)
    calculated_at = Column(DateTime, default=datetime.utcnow)


class ApiKey(Base):
    __tablename__ = 'api_keys'

    id = Column(Integer, primary_key=True)
    # Açıklayıcı isim: "prod-dashboard", "ci-pipeline"
    name = Column(String, nullable=False)
    # SHA256 hash — düz key asla saklanmaz
    key_hash = Column(String, unique=True, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # İzleme için: son ne zaman kullanıldı
    last_used_at = Column(DateTime, nullable=True)
    # Opsiyonel son kullanma tarihi
    expires_at = Column(DateTime, nullable=True)


DATABASE_PATH = os.getenv('DATABASE_PATH', '/app/data/kubepocket.db')
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)
    print(f"✅ Database initialized at {DATABASE_PATH}")


if __name__ == "__main__":
    init_db()
