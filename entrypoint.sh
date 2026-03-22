#!/bin/bash
# entrypoint.sh
set -e

echo "========================================="
echo "🚀 KubePocket v3.0.0 starting..."
echo "========================================="

mkdir -p /var/log/kubepocket
export LOG_DIR="/var/log/kubepocket"
export PYTHONPATH="/app:${PYTHONPATH}"

# DATABASE_URL zorunlu — PostgreSQL bağlantısı
if [ -z "$DATABASE_URL" ]; then
    echo "❌ DATABASE_URL env var is required!"
    echo "   Example: postgresql://user:pass@host:5432/dbname"
    exit 1
fi

echo "💾 Database: ${DATABASE_URL//:*@/://***@}"  # şifreyi gizle

# PostgreSQL'in hazır olmasını bekle
echo "⏳ Waiting for PostgreSQL..."
for i in $(seq 1 30); do
    python -c "
import os, sys
try:
    from sqlalchemy import create_engine, text
    e = create_engine(os.environ['DATABASE_URL'], pool_pre_ping=True)
    with e.connect() as c:
        c.execute(text('SELECT 1'))
    print('✅ PostgreSQL is ready!')
    sys.exit(0)
except Exception as ex:
    print(f'  Attempt $i/30: {ex}')
    sys.exit(1)
" && break || sleep 2
done

# Alembic migration çalıştır
echo "📦 Running database migrations..."
cd /app && alembic upgrade head
echo "✅ Migrations complete"

# Start main collector (every 5 minutes)
echo "🔄 Starting collector service..."
python collector/run_collector.py --daemon --interval 300 > ${LOG_DIR}/collector.log 2>&1 &
COLLECTOR_PID=$!

# Start statistics daemon (every hour)
echo "📊 Starting statistics daemon..."
python collector/stats_daemon.py > ${LOG_DIR}/stats.log 2>&1 &
STATS_PID=$!

# Start Prometheus exporter
echo "📈 Starting Prometheus exporter on port 8001..."
python prometheus_exporter/exporter.py > ${LOG_DIR}/exporter.log 2>&1 &
EXPORTER_PID=$!

# Start API server
echo "🌐 Starting API server on port 8000..."
uvicorn api.main:app --host 0.0.0.0 --port 8000 > ${LOG_DIR}/api.log 2>&1 &
API_PID=$!

sleep 5

if ! kill -0 $COLLECTOR_PID 2>/dev/null; then
    echo "❌ Collector failed to start"
    cat ${LOG_DIR}/collector.log
    exit 1
fi

if ! kill -0 $EXPORTER_PID 2>/dev/null; then
    echo "❌ Exporter failed to start"
    cat ${LOG_DIR}/exporter.log
    exit 1
fi

echo "✅ All services started successfully!"
echo "   - Collector PID: $COLLECTOR_PID"
echo "   - Statistics PID: $STATS_PID"
echo "   - Exporter PID: $EXPORTER_PID"
echo "   - API PID: $API_PID"
echo "📁 Logs: ${LOG_DIR}"
echo "========================================="

cleanup() {
    echo ""
    echo "🛑 Shutting down services..."
    kill $COLLECTOR_PID $STATS_PID $EXPORTER_PID $API_PID 2>/dev/null
    wait
    echo "✅ KubePocket stopped"
    exit 0
}

trap cleanup SIGTERM SIGINT
wait
