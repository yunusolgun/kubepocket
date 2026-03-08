#!/bin/bash
set -e

# ============================================================
# KubePocket Install Script
# ============================================================
#
# GENERAL
#   MODE
#     local       — minikube: builds image locally, deploys test pods,
#                   installs Prometheus+Grafana automatically
#     production  — real cluster: pulls image from registry,
#                   no test pods, no minikube-specific steps
#     default: local
#
# KUBERNETES / CLUSTER
#   CLUSTER_NAME
#     Identifier shown in dashboards and metrics labels
#     default: minikube-local (local) | my-cluster (production)
#
# IMAGE (production mode only)
#   IMAGE_REPOSITORY
#     Container image repository
#     default: kubepocket/kubepocket
#   IMAGE_TAG
#     Container image tag
#     default: 3.0.0
#
# MONITORING STACK
#   EXISTING_STACK
#     false  — install kube-prometheus-stack (Prometheus + Grafana)
#     true   — use customer's existing Prometheus + Grafana
#     default: false
#   MONITORING_NAMESPACE
#     Namespace of the existing monitoring stack.
#     ServiceMonitor is deployed here when EXISTING_STACK=true.
#     default: monitoring
#
# GRAFANA DASHBOARD
#   GRAFANA_URL
#     Grafana base URL for dashboard import
#     default: http://localhost:3000
#   GRAFANA_USER
#     Grafana admin username
#     default: admin
#   GRAFANA_PASSWORD
#     Grafana admin password (also used when installing new Grafana)
#     default: admin123
#   DASHBOARD_FILE
#     Path to kubepocket-dashboard.json for automatic import.
#     If file is not found, import step is skipped with a warning.
#     default: kubepocket-dashboard.json
#   GRAFANA_IMPORT
#     Force dashboard import even when EXISTING_STACK=true
#     default: false
#
# APPLICATION
#   ALLOWED_ORIGINS
#     CORS allowed origins for the KubePocket API
#     default: http://localhost:3000 (local) | * (production)
#   PG_PASSWORD
#     PostgreSQL database password
#     default: kubepocket123
#
# EXAMPLES
#   # Local minikube (default):
#   ./install.sh
#
#   # Production with existing monitoring stack:
#   MODE=production \
#     EXISTING_STACK=true \
#     MONITORING_NAMESPACE=observability \
#     IMAGE_REPOSITORY=your-registry/kubepocket \
#     IMAGE_TAG=3.0.0 \
#     CLUSTER_NAME=prod-eu-west \
#     ./install.sh
#
#   # Production, install new Prometheus+Grafana:
#   MODE=production \
#     IMAGE_REPOSITORY=your-registry/kubepocket \
#     IMAGE_TAG=3.0.0 \
#     CLUSTER_NAME=prod-eu-west \
#     PG_PASSWORD=securepassword \
#     ./install.sh
# ============================================================

MODE=${MODE:-local}
CLUSTER_NAME=${CLUSTER_NAME:-}
IMAGE_REPOSITORY=${IMAGE_REPOSITORY:-kubepocket/kubepocket}
IMAGE_TAG=${IMAGE_TAG:-3.0.0}
EXISTING_STACK=${EXISTING_STACK:-false}
MONITORING_NAMESPACE=${MONITORING_NAMESPACE:-monitoring}
GRAFANA_URL=${GRAFANA_URL:-http://localhost:3000}
GRAFANA_USER=${GRAFANA_USER:-admin}
GRAFANA_PASSWORD=${GRAFANA_PASSWORD:-admin123}
DASHBOARD_FILE=${DASHBOARD_FILE:-kubepocket-dashboard.json}
GRAFANA_IMPORT=${GRAFANA_IMPORT:-false}
ALLOWED_ORIGINS=${ALLOWED_ORIGINS:-}
PG_PASSWORD=${PG_PASSWORD:-kubepocket123}

# ── MODE DEFAULTS ────────────────────────────────────────────────
if [ "$MODE" = "local" ]; then
  CLUSTER_NAME=${CLUSTER_NAME:-minikube-local}
  ALLOWED_ORIGINS=${ALLOWED_ORIGINS:-http://localhost:3000}
  PULL_POLICY=Never
else
  CLUSTER_NAME=${CLUSTER_NAME:-my-cluster}
  ALLOWED_ORIGINS=${ALLOWED_ORIGINS:-'*'}
  PULL_POLICY=IfNotPresent
fi

echo "🚀 KubePocket installation starting..."
echo "   Mode:               $MODE"
echo "   Cluster Name:       $CLUSTER_NAME"
echo "   Image:              $IMAGE_REPOSITORY:$IMAGE_TAG"
echo "   Existing Stack:     $EXISTING_STACK"
echo "   Monitoring NS:      $MONITORING_NAMESPACE"
echo "   Dashboard File:     $DASHBOARD_FILE"
echo ""

# ── LOCAL MODE: minikube setup + local image build ───────────────
if [ "$MODE" = "local" ]; then
  echo "📦 Enabling Metrics Server (minikube)..."
  minikube addons enable metrics-server

  echo "🐳 Setting minikube Docker env..."
  eval $(minikube docker-env)

  echo "🔨 Building Docker image..."
  docker build -t kubepocket:local -f docker/Dockerfile .

  IMAGE_REPOSITORY=kubepocket
  IMAGE_TAG=local
fi

# ── HELM REPOS ───────────────────────────────────────────────────
echo "📡 Adding Helm repos..."
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update || echo "⚠️  Repo update failed, continuing with cached charts..."

# ── MONITORING STACK ─────────────────────────────────────────────
if [ "$EXISTING_STACK" = "true" ]; then
  echo "📊 Using existing monitoring stack (namespace: $MONITORING_NAMESPACE)"
  echo "   ServiceMonitor will be deployed to '$MONITORING_NAMESPACE'."
else
  echo "📊 Installing Prometheus + Grafana..."
  helm install monitoring prometheus-community/kube-prometheus-stack \
    --namespace monitoring \
    --create-namespace \
    --set grafana.adminPassword=$GRAFANA_PASSWORD \
    --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
    --wait --timeout 5m
fi

# ── KUBEPOCKET ───────────────────────────────────────────────────
echo "🎯 Installing KubePocket..."
helm install kubepocket ./helm/kubepocket \
  --namespace kubepocket \
  --create-namespace \
  --set image.repository=$IMAGE_REPOSITORY \
  --set image.tag=$IMAGE_TAG \
  --set image.pullPolicy=$PULL_POLICY \
  --set clusterName=$CLUSTER_NAME \
  --set "allowedOrigins=$ALLOWED_ORIGINS" \
  --set serviceMonitor.enabled=true \
  --set postgresql.auth.password=$PG_PASSWORD \
  --set monitoring.existingStack=$EXISTING_STACK \
  --set monitoring.namespace=$MONITORING_NAMESPACE \
  --wait --timeout 5m

# ── TEST PODS (local only) ────────────────────────────────────────
if [ "$MODE" = "local" ]; then
  echo "🧪 Deploying test pods..."
  kubectl apply -f testpods/03-oom-pod.yaml
  kubectl apply -f testpods/04-crash-loop-pod.yaml
  kubectl apply -f testpods/08-anomaly-cpu-pod.yaml
  kubectl apply -f testpods/09-liveness-fail-pod.yaml
fi

# ── GRAFANA DASHBOARD ────────────────────────────────────────────
if [ "$EXISTING_STACK" = "false" ] || [ "$GRAFANA_IMPORT" = "true" ]; then
  echo "📊 Waiting for Grafana to be ready..."
  kubectl wait --namespace monitoring \
    --for=condition=ready pod \
    --selector=app.kubernetes.io/name=grafana \
    --timeout=120s

  echo "📊 Setting up Grafana port-forward..."
  kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80 &
  GF_PF_PID=$!
  sleep 5

  if [ ! -f "$DASHBOARD_FILE" ]; then
    echo "⚠️  Dashboard file not found: $DASHBOARD_FILE — skipping import"
  else
    echo "📊 Importing KubePocket dashboard..."
    HTTP_STATUS=$(curl -s -o /tmp/gf_import_response.json -w "%{http_code}" \
      -u "$GRAFANA_USER:$GRAFANA_PASSWORD" \
      -X POST "$GRAFANA_URL/api/dashboards/import" \
      -H "Content-Type: application/json" \
      -d "{
        \"dashboard\": $(cat $DASHBOARD_FILE),
        \"overwrite\": true,
        \"folderId\": 0,
        \"inputs\": [{
          \"name\": \"DS_PROMETHEUS\",
          \"type\": \"datasource\",
          \"pluginId\": \"prometheus\",
          \"value\": \"prometheus\"
        }]
      }")

    if [ "$HTTP_STATUS" = "200" ]; then
      echo "✅ Dashboard imported successfully"
    else
      echo "⚠️  Dashboard import failed (HTTP $HTTP_STATUS):"
      cat /tmp/gf_import_response.json
    fi
  fi

  kill $GF_PF_PID 2>/dev/null || true
fi

# ── API KEY ──────────────────────────────────────────────────────
echo "🔑 Creating API key..."
sleep 10
API_KEY=$(kubectl exec -n kubepocket deploy/kubepocket -- python3 -c "
import sys; sys.path.insert(0, '/app')
from db.models import SessionLocal
from api.auth import create_api_key
db = SessionLocal()
key = create_api_key(db, name='admin')
print(key)
db.close()
")

# ── DONE ─────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo "✅ Installation complete!"
echo "=========================================="
echo "🔑 API Key: $API_KEY"
echo ""
if [ "$MODE" = "local" ]; then
  echo "Run these port-forwards to access the services:"
  echo ""
  echo "  # KubePocket API:"
  echo "  kubectl port-forward -n kubepocket svc/kubepocket 8000:8000 &"
  echo ""
  echo "  # Grafana (required to view dashboards):"
  echo "  kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80 &"
  echo "  open http://localhost:3000  →  admin / $GRAFANA_PASSWORD"
  echo ""
  echo "  # Prometheus (optional):"
  echo "  kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090:9090 &"
else
  echo "KubePocket API is available via service/ingress in namespace 'kubepocket'."
  echo "Grafana is available via service/ingress in namespace '$MONITORING_NAMESPACE'."
fi
echo ""
echo "Run first collector:"
echo "  kubectl exec -n kubepocket deploy/kubepocket -- python collector/run_collector.py"
echo "=========================================="