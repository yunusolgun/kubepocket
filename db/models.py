# db/models.py
import os
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, JSON, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

# PostgreSQL bağlantısı — env var'dan al
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://kubepocket:kubepocket@localhost:5432/kubepocket'
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,       # bağlantı kopuksa otomatik yeniden bağlan
    pool_size=5,              # connection pool boyutu
    max_overflow=10,          # pool dolunca max ekstra bağlantı
    pool_recycle=300          # 5 dakikada bir bağlantıyı yenile
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Cluster(Base):
    __tablename__ = 'clusters'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    context = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Metric(Base):
    __tablename__ = 'metrics'

    id = Column(Integer, primary_key=True)
    cluster_id = Column(Integer, nullable=False)
    namespace = Column(String(255), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    pod_data = Column(JSON)
    total_cpu = Column(Float, default=0.0)
    total_memory = Column(Float, default=0.0)
    total_restarts = Column(Integer, default=0)


class Alert(Base):
    __tablename__ = 'alerts'

    id = Column(Integer, primary_key=True)
    cluster_id = Column(Integer, nullable=True)
    namespace = Column(String(255))
    message = Column(Text)
    severity = Column(String(50), default='warning')
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Statistics(Base):
    __tablename__ = 'statistics'

    id = Column(Integer, primary_key=True)
    cluster_id = Column(Integer, nullable=True)
    namespace = Column(String(255), nullable=False)
    metric_type = Column(String(50), nullable=False)
    avg_value = Column(Float)
    std_dev = Column(Float)
    min_value = Column(Float)
    max_value = Column(Float)
    trend_slope = Column(Float, default=0.0)
    calculated_at = Column(DateTime, default=datetime.utcnow, index=True)


class ApiKey(Base):
    __tablename__ = 'api_keys'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    key_hash = Column(String(64), unique=True, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)


def init_db():
    Base.metadata.create_all(bind=engine)
    print(f"✅ Database initialized at {DATABASE_URL.split('@')[-1]}")
