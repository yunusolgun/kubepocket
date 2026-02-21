#!/bin/bash
# install.sh - One-line KubePocket installation script

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================${NC}"
echo -e "${GREEN}🚀 KubePocket Installation${NC}"
echo -e "${BLUE}================================${NC}"

# Check prerequisites
command -v kubectl >/dev/null 2>&1 || { echo -e "${RED}❌ kubectl is required but not installed${NC}" >&2; exit 1; }

# Get license key (for paid versions)
read -p "Enter your license key (press Enter for free tier): " LICENSE_KEY

# Create namespace
echo "📁 Creating namespace..."
kubectl create namespace kubepocket 2>/dev/null || true

# Store license key
if [ ! -z "$LICENSE_KEY" ]; then
  echo "🔑 Storing license key..."
  kubectl create secret generic kubepocket-license \
    --namespace kubepocket \
    --from-literal=key=$LICENSE_KEY \
    --dry-run=client -o yaml | kubectl apply -f -
fi

# Store kubeconfig for cluster access
echo "🔐 Storing kubeconfig..."
kubectl create secret generic kubepocket-kubeconfig \
  --namespace kubepocket \
  --from-file=config=${KUBECONFIG:-$HOME/.kube/config} \
  --dry-run=client -o yaml | kubectl apply -f -

# Apply RBAC
echo "🔒 Applying RBAC rules..."
kubectl apply -f https://raw.githubusercontent.com/kubepocket/kubepocket/main/k8s/rbac.yaml

# Apply ConfigMap
echo "⚙️ Applying configuration..."
kubectl apply -f https://raw.githubusercontent.com/kubepocket/kubepocket/main/k8s/configmap.yaml

# Apply PVC
echo "💾 Creating persistent volume..."
kubectl apply -f https://raw.githubusercontent.com/kubepocket/kubepocket/main/k8s/pvc.yaml

# Apply Deployment
echo "🚀 Deploying KubePocket..."
kubectl apply -f https://raw.githubusercontent.com/kubepocket/kubepocket/main/k8s/deployment.yaml

# Apply Service
echo "🌐 Exposing services..."
kubectl apply -f https://raw.githubusercontent.com/kubepocket/kubepocket/main/k8s/service.yaml

# Wait for deployment
echo "⏳ Waiting for deployment to be ready..."
kubectl wait --namespace kubepocket \
  --for=condition=available \
  --timeout=120s \
  deployment/kubepocket

# Show status
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}✅ KubePocket installed successfully!${NC}"
echo -e "${GREEN}================================${NC}"
echo ""
echo "📊 Access the API:"
echo "  kubectl port-forward -n kubepocket svc/kubepocket 8000:8000"
echo "  curl http://localhost:8000/health"
echo ""
echo "📈 Access metrics:"
echo "  kubectl port-forward -n kubepocket svc/kubepocket-metrics 8001:8001"
echo "  curl http://localhost:8001/metrics"
echo ""
echo "📚 Documentation: https://docs.kubepocket.com"
echo "💬 Support: support@kubepocket.com"