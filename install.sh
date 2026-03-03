#!/bin/bash
set -e

echo "🚀 KubePocket kurulumu başlıyor..."

# 1. Metrics Server
echo "📦 Metrics Server etkinleştiriliyor..."
minikube addons enable metrics-server

# 2. Docker env
echo "🐳 Minikube Docker env ayarlanıyor..."
eval $(minikube docker-env)

# 3. Image build
echo "🔨 Docker image build ediliyor..."
docker build -t kubepocket:local -f docker/Dockerfile .

# 4. Helm repo ekle
echo "📡 Helm repoları ekleniyor..."
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# 5. Prometheus + Grafana kur
echo "📊 Prometheus + Grafana kuruluyor..."
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set grafana.adminPassword=admin123 \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
  --wait --timeout 3m

# 6. KubePocket kur
echo "🎯 KubePocket kuruluyor..."
helm install kubepocket ./helm/kubepocket \
  --namespace kubepocket \
  --create-namespace \
  --set image.repository=kubepocket \
  --set image.tag=local \
  --set image.pullPolicy=Never \
  --set clusterName=minikube-local \
  --set allowedOrigins=http://localhost:3000 \
  --set serviceMonitor.enabled=true \
  --set postgresql.auth.password=kubepocket123 \
  --wait --timeout 3m

# 7. Test pod'ları
echo "🧪 Test pod'ları kuruluyor..."
kubectl apply -f testpods/03-oom-pod.yaml
kubectl apply -f testpods/04-crash-loop-pod.yaml
kubectl apply -f testpods/08-anomaly-cpu-pod.yaml
kubectl apply -f testpods/09-liveness-fail-pod.yaml

# 8. API key oluştur
echo "🔑 API key oluşturuluyor..."
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
echo ""
echo "=========================================="
echo "✅ Kurulum tamamlandı!"
echo "=========================================="
echo "🔑 API Key: $API_KEY"
echo ""
echo "Port-forward için:"
echo "  kubectl port-forward -n kubepocket svc/kubepocket 8000:8000 &"
echo "  kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80 &"
echo "  kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090:9090 &"
echo ""
echo "İlk collector çalıştırmak için:"
echo "  kubectl exec -n kubepocket deploy/kubepocket -- python collector/run_collector.py"
echo "=========================================="