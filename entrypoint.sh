#!/bin/bash
# entrypoint.sh
set -e

echo "========================================="
echo "🚀 KubePocket v2.0.0 starting..."
echo "========================================="

# Create necessary directories
mkdir -p /data /var/log/kubepocket

# Set database path
export DB_PATH="/data/kubepocket.db"
export LOG_DIR="/var/log/kubepocket"
export PYTHONPATH="/app:${PYTHONPATH}"

# Initialize database with new schema
echo "📦 Initializing database with new schema..."
python -c "from db.models import init_db; init_db()"

# Start main collector (every 5 minutes)
echo "🔄 Starting collector service (interval: 5m)..."
python collector/run_collector.py --daemon --interval 300 > ${LOG_DIR}/collector.log 2>&1 &
COLLECTOR_PID=$!

# Start statistics daemon (every hour)
echo "📊 Starting statistics daemon (interval: 1h)..."
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

# Wait for services to start
sleep 5

# Check if services are running
if ! kill -0 $COLLECTOR_PID 2>/dev/null; then
    echo "❌ Collector failed to start"
    exit 1
fi

if ! kill -0 $EXPORTER_PID 2>/dev/null; then
    echo "❌ Exporter failed to start"
    exit 1
fi

echo "✅ All services started successfully!"
echo "   - Collector PID: $COLLECTOR_PID"
echo "   - Statistics PID: $STATS_PID"
echo "   - Exporter PID: $EXPORTER_PID"
echo "   - API PID: $API_PID"
echo ""
echo "📊 New features active:"
echo "   - Anomaly detection (Z-score based)"
echo "   - Resource forecasting (7-day prediction)"
echo "   - Trend analysis"
echo ""
echo "📁 Logs: ${LOG_DIR}"
echo "💾 Database: ${DB_PATH}"
echo "========================================="

# Graceful shutdown handler
cleanup() {
    echo ""
    echo "🛑 Shutting down services..."
    kill $COLLECTOR_PID $STATS_PID $EXPORTER_PID $API_PID 2>/dev/null
    wait
    echo "✅ KubePocket stopped"
    exit 0
}

trap cleanup SIGTERM SIGINT

# Wait for all background processes
wait