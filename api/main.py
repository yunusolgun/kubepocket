# api/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import init_db, SessionLocal
from api.auth import create_api_key

app = FastAPI(
    title="KubePocket API",
    description="Kubernetes maliyet ve kaynak monitor API'si",
    version="3.0.0"
)

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()

    from db.models import ApiKey
    db = SessionLocal()
    try:
        key_count = db.query(ApiKey).count()
        if key_count == 0:
            raw_key = create_api_key(db, name="initial-admin-key")
            print("=" * 60)
            print("🔑 İLK API KEY OLUŞTURULDU")
            print(f"   Key: {raw_key}")
            print("   Bu key bir daha gösterilmeyecek!")
            print("   Hemen kopyala ve güvenli bir yerde sakla.")
            print("=" * 60)
    finally:
        db.close()


from api.routes import metrics, alerts, clusters, apikeys, cost

app.include_router(metrics.router, prefix="/api/metrics", tags=["metrics"])
app.include_router(alerts.router, prefix="/api/alerts", tags=["alerts"])
app.include_router(clusters.router, prefix="/api/clusters", tags=["clusters"])
app.include_router(apikeys.router, prefix="/api/keys", tags=["api-keys"])
app.include_router(cost.router, prefix="/api/cost", tags=["cost"])


@app.get("/")
async def root():
    return {
        "service": "KubePocket API",
        "version": "3.0.0",
        "status": "running",
        "timestamp": datetime.now().isoformat()
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
