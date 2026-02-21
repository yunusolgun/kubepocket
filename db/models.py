# db/models.py - Updated version with Statistics table
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
    avg_value = Column(Float)     # 7-day average
    std_dev = Column(Float)       # Standard deviation
    min_value = Column(Float)     # Minimum value
    max_value = Column(Float)     # Maximum value
    trend_slope = Column(Float)   # Trend slope (positive/negative)
    calculated_at = Column(DateTime, default=datetime.utcnow)

DATABASE_URL = "sqlite:///./kubepocket.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)
    print("✅ Database initialized successfully!")

if __name__ == "__main__":
    init_db()
