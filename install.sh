#!/bin/bash
set -euo pipefail

# ============================================================
# KubePocket Install Script
# ============================================================
#
# GENERAL
#   MODE
#     local       — local development: builds image locally, deploys
#                   test pods, installs Prometheus+Grafana automatically
#     production  — any real cluster: pulls image from registry,
#                   no test pods, no local-specific steps
#     default: local
#
# LOCAL DRIVER (local mode only)
#   LOCAL_DRIVER
#     minikube        — enables metrics-server addon, sets minikube docker env
#     docker-desktop  — installs metrics-server via kubectl, patches TLS
#     none            — skip all driver-specific steps (e.g. k3s, kind, bare metal)
#     default: auto-detected from current kubectl context
#
# KUBERNETES / CLUSTER
#   CLUSTER_NAME
#     Identifier shown in dashboards and metrics labels
#     default: minikube-local | docker-desktop | my-cluster
#
# IMAGE
#   IMAGE_REPOSITORY  Container image repository (default: kubepocket/kubepocket)
#   IMAGE_TAG         Container image tag (default: 3.0.0)
#
# MONITORING STACK
#   EXISTING_STACK        false — install kube-prometheus-stack
#                         true  — use existing Prometheus + Grafana
#                         default: false
#   MONITORING_NAMESPACE  Namespace of the existing monitoring stack (default: monitoring)
#   HELM_TIMEOUT          Helm install/upgrade timeout (default: 10m)
#
# GRAFANA DASHBOARD
#   GRAFANA_URL       default: http://localhost:3000
#   GRAFANA_USER      default: admin
#   GRAFANA_PASSWORD  default: admin123
#   DASHBOARD_FILE    default: kubepocket-dashboard.json
#   GRAFANA_IMPORT    Force import even when EXISTING_STACK=true (default: false)
#
# APPLICATION
#   ALLOWED_ORIGINS   CORS origins (default: http://localhost:3000 / *)
#   PG_PASSWORD       PostgreSQL password (default: kubepocket123)
#   LICENSE_KEY       KubePocket Pro license key (default: empty = free tier)
#
# SECURITY NOTE
#   For production use, prefer passing passwords via environment variables
#   set in a secrets manager rather than inline on the command line, to
#   avoid leaking credentials in shell history.
#
# EXAMPLES
#   # Minikube:
#   ./install.sh
#
#   # Docker Desktop:
#   LOCAL_DRIVER=docker-desktop ./install.sh
#
#   # kind / k3s / bare-metal local:
#   LOCAL_DRIVER=none ./install.sh
#
#   # Production — existing monitoring stack:
#   MODE=production \
#     EXISTING_STACK=true \
#     MONITORING_NAMESPACE=observability \
#     IMAGE_REPOSITORY=your-registry/kubepocket \
#     IMAGE_TAG=3.0.0 \
#     CLUSTER_NAME=prod-eu-west \
#     LICENSE_KEY=kp_... \
#     ./install.sh
#
#   # Production — install new Prometheus+Grafana:
#   MODE=production \
#     IMAGE_REPOSITORY=your-registry/kubepocket \
#     IMAGE_TAG=3.0.0 \
#     CLUSTER_NAME=prod-eu-west \
#     PG_PASSWORD=securepassword \
#     LICENSE_KEY=kp_... \
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
LICENSE_KEY=${LICENSE_KEY:-}
HELM_TIMEOUT=${HELM_TIMEOUT:-10m}

# ── Prerequisite checks ──────────────────────────────────────────
check_prerequisites() {
  local missing=0
  for cmd in kubectl helm curl; do
    if ! command -v "$cmd" &>/dev/null; then
      echo "❌ Required tool not found: $cmd"
      missing=1
    fi
  done
  if [ "$MODE" = "local" ] && ! command -v docker &>/dev/null; then
    echo "❌ Required tool not found: docker"
    missing=1
  fi
  if [ "$missing" = "1" ]; then
    echo ""
    echo "Please install the missing tools and try again."
    exit 1
  fi

  # Check kubectl can reach the cluster
  if ! kubectl cluster-info &>/dev/null; then
    echo "❌ Cannot reach Kubernetes cluster. Check your kubeconfig."
    exit 1
  fi
}

# ── Rollback on failure ──────────────────────────────────────────
ROLLBACK_DONE=0
rollback() {
  if [ "$ROLLBACK_DONE" = "1" ]; then return; fi
  ROLLBACK_DONE=1
  echo ""
  echo "❌ Installation failed. Rolling back..."
  helm uninstall kubepocket -n kubepocket 2>/dev/null || true
  if [ "$EXISTING_STACK" = "false" ]; then
    helm uninstall monitoring -n monitoring 2>/dev/null || true
  fi
  echo "   Rollback complete. Namespaces are preserved for debugging."
  echo "   Run 'kubectl get pods -A' to inspect the state."
}
trap rollback ERR

# ── Auto-detect LOCAL_DRIVER ─────────────────────────────────────
if [ "$MODE" = "local" ] && [ -z "${LOCAL_DRIVER:-}" ]; then
  CURRENT_CONTEXT=$(kubectl config current-context 2>/dev/null || echo "")
  if echo "$CURRENT_CONTEXT" | grep -q "minikube"; then
    LOCAL_DRIVER=minikube
  elif echo "$CURRENT_CONTEXT" | grep -q "docker-desktop"; then
    LOCAL_DRIVER=docker-desktop
  else
    LOCAL_DRIVER=none
  fi
fi
LOCAL_DRIVER=${LOCAL_DRIVER:-none}

# ── MODE DEFAULTS ────────────────────────────────────────────────
if [ "$MODE" = "local" ]; then
  case "$LOCAL_DRIVER" in
    minikube)       CLUSTER_NAME=${CLUSTER_NAME:-minikube-local} ;;
    docker-desktop) CLUSTER_NAME=${CLUSTER_NAME:-docker-desktop} ;;
    *)              CLUSTER_NAME=${CLUSTER_NAME:-local-cluster} ;;
  esac
  ALLOWED_ORIGINS=${ALLOWED_ORIGINS:-http://localhost:3000}
  PULL_POLICY=Never
else
  CLUSTER_NAME=${CLUSTER_NAME:-my-cluster}
  ALLOWED_ORIGINS=${ALLOWED_ORIGINS:-'*'}
  PULL_POLICY=IfNotPresent
fi

# ── Print config ─────────────────────────────────────────────────
echo "🚀 KubePocket installation starting..."
echo "   Mode:               $MODE"
[ "$MODE" = "local" ] && echo "   Driver:             $LOCAL_DRIVER"
echo "   Cluster Name:       $CLUSTER_NAME"
echo "   Image:              $IMAGE_REPOSITORY:$IMAGE_TAG"
echo "   Existing Stack:     $EXISTING_STACK"
echo "   Monitoring NS:      $MONITORING_NAMESPACE"
echo "   Dashboard File:     $DASHBOARD_FILE"
echo "   Helm Timeout:       $HELM_TIMEOUT"
[ -n "$LICENSE_KEY" ] && echo "   License Key:        ${LICENSE_KEY:0:20}..." || echo "   License Key:        (none — free tier)"
echo ""

# ── Run checks ───────────────────────────────────────────────────
check_prerequisites

# ── LOCAL MODE: driver-specific setup + image build ─────────────
if [ "$MODE" = "local" ]; then
  case "$LOCAL_DRIVER" in
    minikube)
      echo "📦 Enabling Metrics Server (minikube)..."
      minikube addons enable metrics-server

      echo "🐳 Setting minikube Docker env..."
      eval $(minikube docker-env)
      ;;

    docker-desktop)
      echo "📦 Installing Metrics Server (docker-desktop)..."
      kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml 2>/dev/null || true
      kubectl patch deployment metrics-server -n kube-system \
        --type='json' \
        -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]' \
        2>/dev/null || true
      ;;

    none)
      echo "📦 Skipping driver-specific setup (LOCAL_DRIVER=none)"
      echo "   Make sure Metrics Server is installed on your cluster."
      ;;
  esac

  echo "🔨 Building Docker image..."
  docker build -t kubepocket:local -f docker/Dockerfile .

  IMAGE_REPOSITORY=kubepocket
  IMAGE_TAG=local
fi

# ── Helm dependency update ────────────────────────────────────────
echo "📦 Updating Helm dependencies..."
helm dependency update ./helm/kubepocket

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

  # node-exporter requires shared host mounts — not supported on docker-desktop
  NODE_EXPORTER_FLAG=""
  if [ "$LOCAL_DRIVER" = "docker-desktop" ]; then
    NODE_EXPORTER_FLAG="--set nodeExporter.enabled=false"
  fi

  helm install monitoring prometheus-community/kube-prometheus-stack \
    --namespace monitoring \
    --create-namespace \
    --set grafana.adminPassword="$GRAFANA_PASSWORD" \
    --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
    $NODE_EXPORTER_FLAG \
    --wait --timeout "$HELM_TIMEOUT"
fi

# ── KUBEPOCKET ───────────────────────────────────────────────────
echo "🎯 Installing KubePocket..."

LICENSE_FLAG=""
[ -n "$LICENSE_KEY" ] && LICENSE_FLAG="--set licenseKey=$LICENSE_KEY"

helm install kubepocket ./helm/kubepocket \
  --namespace kubepocket \
  --create-namespace \
  --set image.repository="$IMAGE_REPOSITORY" \
  --set image.tag="$IMAGE_TAG" \
  --set image.pullPolicy="$PULL_POLICY" \
  --set clusterName="$CLUSTER_NAME" \
  --set "allowedOrigins=$ALLOWED_ORIGINS" \
  --set serviceMonitor.enabled=true \
  --set postgresql.auth.password="$PG_PASSWORD" \
  --set monitoring.existingStack="$EXISTING_STACK" \
  --set monitoring.namespace="$MONITORING_NAMESPACE" \
  $LICENSE_FLAG \
  --wait --timeout "$HELM_TIMEOUT"

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

  # Wait for port-forward to be ready
  for i in $(seq 1 10); do
    if curl -s -o /dev/null "http://localhost:3000/api/health"; then
      break
    fi
    sleep 2
  done

  if [ ! -f "$DASHBOARD_FILE" ]; then
    echo "⚠️  Dashboard file not found: $DASHBOARD_FILE — skipping import"
  else
    echo "📊 Importing KubePocket dashboard..."
    HTTP_STATUS=$(curl -s -o /tmp/gf_import_response.json -w "%{http_code}" \
      -u "$GRAFANA_USER:$GRAFANA_PASSWORD" \
      -X POST "$GRAFANA_URL/api/dashboards/import" \
      -H "Content-Type: application/json" \
      -d "{
        \"dashboard\": $(cat "$DASHBOARD_FILE"),
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
kubectl wait --namespace kubepocket \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/name=kubepocket \
  --timeout=120s

API_KEY=$(kubectl exec -n kubepocket deploy/kubepocket -- python3 -c "
import sys; sys.path.insert(0, '/app')
from db.models import SessionLocal
from api.auth import create_api_key
db = SessionLocal()
key = create_api_key(db, name='admin')
print(key)
db.close()
")

# ── Disable rollback trap — install succeeded ────────────────────
trap - ERR

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
