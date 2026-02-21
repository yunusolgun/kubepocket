# api/main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
from typing import List, Optional
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.repository import MetricRepository
from db.models import init_db

# FastAPI uygulaması
app = FastAPI(
    title="KubePocket API",
    description="Kubernetes maliyet ve kaynak monitor API'si",
    version="1.0.0"
)

# CORS ayarları (React'ten erişim için)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # React dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Veritabanını başlat
init_db()

# API durum kontrolü
@app.get("/")
async def root():
    return {
        "service": "KubePocket API",
        "version": "1.0.0",
        "status": "running",
        "timestamp": datetime.now().isoformat()
    }

# Health check
@app.get("/health")
async def health():
    return {"status": "healthy"}

# Router'ları import et
from api.routes import metrics, alerts, clusters

app.include_router(metrics.router, prefix="/api/metrics", tags=["metrics"])
app.include_router(alerts.router, prefix="/api/alerts", tags=["alerts"])
app.include_router(clusters.router, prefix="/api/clusters", tags=["clusters"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
