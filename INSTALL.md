# KubePocket — Installation Guide

## Requirements

| Tool           | Version |
|----------------|---------|
| Docker Desktop | 29+     |
| Minikube       | v1.37+  |
| Helm           | v3+     |
| kubectl        | v1.28+  |

---

## Quick Install (Recommended)

```bash
./install.sh
```

The script automatically detects your local environment (minikube, docker-desktop, or other) and handles everything:
- Docker image build
- Prometheus + Grafana installation
- KubePocket Helm installation
- Grafana dashboard import

---

## Manual Installation (Step by Step)

### 1 — Start your local cluster

**Minikube:**
```bash
minikube start --cpus=2 --memory=4096 --driver=docker
```

**Docker Desktop:** Enable Kubernetes in Docker Desktop → Settings → Kubernetes → Enable Kubernetes.

### 2 — Build the image

**Minikube:**
```bash
eval $(minikube docker-env)
docker build -t kubepocket:local -f docker/Dockerfile .
```

**Docker Desktop:**
```bash
docker build --platform linux/amd64 -t kubepocket:local -f docker/Dockerfile .
```

### 3 — Update Helm dependencies

```bash
helm dependency update ./helm/kubepocket
```

### 4 — Install Prometheus + Grafana

**Minikube:**
```bash
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set grafana.adminPassword=admin123 \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
  --wait --timeout 10m
```

**Docker Desktop** (node-exporter is not supported on Docker Desktop):
```bash
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set grafana.adminPassword=admin123 \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
  --set nodeExporter.enabled=false \
  --wait --timeout 10m
```

### 5 — Install KubePocket

> ⚠️ Do not proceed before step 4 is complete — you will get a ServiceMonitor CRD error.

```bash
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
  --wait --timeout 5m
```

### 6 — Get the API key

```bash
kubectl exec -n kubepocket deploy/kubepocket -- \
  cat /var/log/kubepocket/api.log | grep "Key:"
```

### 7 — Open port-forwards

```bash
# Terminal 1 — KubePocket API
kubectl port-forward -n kubepocket svc/kubepocket 8000:8000

# Terminal 2 — Grafana
kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80

# Terminal 3 — Prometheus (optional)
kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090:9090
```

### 8 — Import Grafana dashboard

```bash
curl -s -u admin:admin123 \
  -X POST http://localhost:3000/api/dashboards/import \
  -H "Content-Type: application/json" \
  -d "{
    \"dashboard\": $(cat kubepocket-dashboard.json),
    \"overwrite\": true,
    \"folderId\": 0
  }"
```

Or via Grafana UI: **Dashboards → Import → Upload JSON file** → `kubepocket-dashboard.json`

---

## Production Install

```bash
MODE=production \
  EXISTING_STACK=true \
  MONITORING_NAMESPACE=observability \
  IMAGE_REPOSITORY=your-registry/kubepocket \
  IMAGE_TAG=3.0.0 \
  CLUSTER_NAME=prod-eu-west \
  GRAFANA_URL=http://grafana.internal \
  GRAFANA_PASSWORD=yourpassword \
  LICENSE_KEY=kp_... \
  ./install.sh
```

### install.sh Environment Variables

| Variable               | Default                     | Description                                            |
|------------------------|-----------------------------|--------------------------------------------------------|
| `MODE`                 | `local`                     | `local` or `production`                                |
| `LOCAL_DRIVER`         | auto-detected               | `minikube`, `docker-desktop`, or `none`                |
| `CLUSTER_NAME`         | `minikube-local`            | Cluster identifier shown in dashboards                 |
| `IMAGE_REPOSITORY`     | `kubepocket/kubepocket`     | Container image repository                             |
| `IMAGE_TAG`            | `3.0.0`                     | Container image tag                                    |
| `EXISTING_STACK`       | `false`                     | Use an existing Prometheus/Grafana stack               |
| `MONITORING_NAMESPACE` | `monitoring`                | Namespace of the monitoring stack                      |
| `GRAFANA_URL`          | `http://localhost:3000`     | Grafana base URL                                       |
| `GRAFANA_USER`         | `admin`                     | Grafana admin username                                 |
| `GRAFANA_PASSWORD`     | `admin123`                  | Grafana admin password                                 |
| `DASHBOARD_FILE`       | `kubepocket-dashboard.json` | Path to the dashboard JSON file                        |
| `GRAFANA_IMPORT`       | `false`                     | Force dashboard import even with existing stack        |
| `ALLOWED_ORIGINS`      | `http://localhost:3000/*`   | CORS allowed origins                                   |
| `PG_PASSWORD`          | `kubepocket123`             | PostgreSQL password                                    |
| `LICENSE_KEY`          | *(empty)*                   | KubePocket Pro license key (empty = free tier)         |
| `HELM_TIMEOUT`         | `10m`                       | Helm install/upgrade timeout (increase for slow clusters) |

---

## Multi-Cluster Setup

KubePocket supports monitoring multiple Kubernetes clusters from a single Grafana dashboard. All clusters share the same PostgreSQL database; each cluster runs its own KubePocket instance identified by a unique `CLUSTER_NAME`.

```
cluster-eu  →  KubePocket (CLUSTER_NAME=prod-eu)  ┐
cluster-us  →  KubePocket (CLUSTER_NAME=prod-us)  ├──→  Shared PostgreSQL  ←──  Grafana
cluster-stg →  KubePocket (CLUSTER_NAME=staging)  ┘
```

**Primary cluster** (hosts the database and Grafana):
```bash
MODE=production \
  CLUSTER_NAME=prod-eu \
  IMAGE_REPOSITORY=your-registry/kubepocket \
  IMAGE_TAG=3.0.0 \
  ./install.sh
```

**Additional clusters** (connect to the primary database):
```bash
MODE=production \
  CLUSTER_NAME=prod-us \
  IMAGE_REPOSITORY=your-registry/kubepocket \
  IMAGE_TAG=3.0.0 \
  EXISTING_STACK=true \
  ./install.sh
```

Set `externalDatabase` in `values.yaml` for additional clusters:
```yaml
postgresql:
  enabled: false

externalDatabase:
  host: "prod-eu-postgresql.kubepocket.svc.cluster.local"
  port: 5432
  username: kubepocket
  password: kubepocket123
  database: kubepocket
```

Once connected, the Grafana dashboard shows a **Cluster** dropdown to switch between clusters or view all at once.

---

## Webhook Notifications

KubePocket sends alert notifications to Slack, Microsoft Teams, or any generic HTTP endpoint. Notifications are deduplicated — the same alert is never sent twice.

### Slack

1. Go to https://api.slack.com/apps and create a new app.
2. Enable **Incoming Webhooks** and add a webhook to your workspace.
3. Copy the webhook URL (`https://hooks.slack.com/services/...`).

```bash
helm upgrade kubepocket ./helm/kubepocket \
  --namespace kubepocket \
  --reuse-values \
  --set webhook.slackUrl="https://hooks.slack.com/services/T.../B.../..."
```

### Microsoft Teams

1. In your Teams channel, go to **Connectors → Incoming Webhook**.
2. Create a webhook and copy the URL.

```bash
helm upgrade kubepocket ./helm/kubepocket \
  --namespace kubepocket \
  --reuse-values \
  --set webhook.teamsUrl="https://outlook.office.com/webhook/..."
```

### Generic HTTP POST

Any endpoint that accepts a JSON POST request:

```bash
helm upgrade kubepocket ./helm/kubepocket \
  --namespace kubepocket \
  --reuse-values \
  --set webhook.genericUrl="https://your-endpoint.com/alerts"
```

Payload format:
```json
{
  "cluster":    "prod-eu",
  "severity":   "critical",
  "namespace":  "payments",
  "message":    "Pod payments-api restarted 10 times",
  "created_at": "2026-03-14T12:00:00"
}
```

### Configuration

| values.yaml key          | Environment Variable                   | Default    | Description                              |
|--------------------------|----------------------------------------|------------|------------------------------------------|
| `webhook.slackUrl`       | `KUBEPOCKET_SLACK_WEBHOOK_URL`         | *(empty)*  | Slack Incoming Webhook URL               |
| `webhook.teamsUrl`       | `KUBEPOCKET_TEAMS_WEBHOOK_URL`         | *(empty)*  | Microsoft Teams Incoming Webhook URL     |
| `webhook.genericUrl`     | `KUBEPOCKET_WEBHOOK_URL`               | *(empty)*  | Generic HTTP POST endpoint               |
| `webhook.minSeverity`    | `KUBEPOCKET_WEBHOOK_MIN_SEVERITY`      | `warning`  | Minimum severity: `warning` or `critical`|

### Multiple providers

All three providers can be active simultaneously:

```bash
helm upgrade kubepocket ./helm/kubepocket \
  --namespace kubepocket \
  --reuse-values \
  --set webhook.slackUrl="https://hooks.slack.com/services/..." \
  --set webhook.teamsUrl="https://outlook.office.com/webhook/..." \
  --set webhook.minSeverity="critical"
```

---

## Licensing

### Tier Comparison

| Feature           | Free      | Pro        |
|-------------------|-----------|------------|
| Clusters          | 1         | Unlimited  |
| Namespaces        | 4         | Unlimited  |
| Retention         | 30 days   | 365 days   |
| Metrics           | ✅        | ✅         |
| Alerts            | ✅        | ✅         |
| Anomaly Detection | ✅        | ✅         |
| Forecast          | ✅        | ✅         |

### Applying a license key

```bash
helm upgrade kubepocket ./helm/kubepocket \
  --namespace kubepocket \
  --reuse-values \
  --set licenseKey="kp_..."
```

### Checking license status

```bash
curl -s http://localhost:8000/api/license | python3 -m json.tool
```

### Generating a license key (internal use only)

```bash
python3 licensing/generate_license.py \
  --tier pro \
  --customer "Acme Corp" \
  --email admin@acme.com \
  --months 12 \
  --private-key private_key.pem
```

> ⚠️ `private_key.pem` and `generate_license.py` are excluded from Docker images via `.dockerignore`.

---

## Test Pods

Simulate different failure scenarios:

```bash
kubectl apply -f testpods/01-healthy-pod.yaml         # Normal pod
kubectl apply -f testpods/02-high-cpu-pod.yaml        # CPU limit pressure
kubectl apply -f testpods/03-oom-pod.yaml             # OOMKilled
kubectl apply -f testpods/04-crash-loop-pod.yaml      # CrashLoopBackOff
kubectl apply -f testpods/05-pending-pod.yaml         # Pending (unschedulable)
kubectl apply -f testpods/06-high-memory-pod.yaml     # High memory usage
kubectl apply -f testpods/07-wrong-image-pod.yaml     # ImagePullBackOff
kubectl apply -f testpods/08-anomaly-cpu-pod.yaml     # Triggers anomaly detection
kubectl apply -f testpods/09-liveness-fail-pod.yaml   # Liveness probe failure
kubectl apply -f testpods/10-resource-hungry-pod.yaml # High CPU + memory

kubectl get pods -n default
```

---

## Upgrading

```bash
# Minikube
eval $(minikube docker-env)
docker build --no-cache -t kubepocket:local -f docker/Dockerfile .

# Docker Desktop
docker build --no-cache --platform linux/amd64 -t kubepocket:local -f docker/Dockerfile .

# Apply
kubectl rollout restart deployment/kubepocket -n kubepocket
kubectl rollout status deployment/kubepocket -n kubepocket
```

---

## Useful Commands

```bash
# Pod logs
kubectl logs -n kubepocket deploy/kubepocket
kubectl exec -n kubepocket deploy/kubepocket -- tail -f /var/log/kubepocket/api.log
kubectl exec -n kubepocket deploy/kubepocket -- tail -f /var/log/kubepocket/collector.log

# Trigger collector manually
kubectl exec -n kubepocket deploy/kubepocket -- python collector/run_collector.py

# Connect to PostgreSQL
kubectl exec -n kubepocket kubepocket-postgresql-0 -- \
  env PGPASSWORD=kubepocket123 psql -U kubepocket -d kubepocket -c "\dt"

# Helm status
helm status kubepocket -n kubepocket
helm status monitoring -n monitoring

# Remove everything
helm uninstall kubepocket -n kubepocket
helm uninstall monitoring -n monitoring
kubectl delete namespace kubepocket monitoring
```

---

## Services

| Service             | URL                          | Description                |
|---------------------|------------------------------|----------------------------|
| KubePocket API      | http://localhost:8000        | REST API                   |
| Swagger UI          | http://localhost:8000/docs   | API documentation          |
| Grafana             | http://localhost:3000        | Dashboard (admin/admin123) |
| Prometheus          | http://localhost:9090        | Metrics                    |
| Prometheus Exporter | (in-cluster) :8001/metrics   | Raw metrics                |

---

## Troubleshooting

**Cannot connect to PostgreSQL:**
```bash
kubectl get pods -n kubepocket
kubectl logs -n kubepocket kubepocket-postgresql-0
```

**API key not working after pod restart:**
```bash
kubectl exec -n kubepocket kubepocket-postgresql-0 -- \
  psql -U kubepocket -d kubepocket -c \
  "SELECT name, is_active, created_at FROM api_keys;"
```

**ServiceMonitor not visible:**
```bash
kubectl get servicemonitor -n kubepocket
kubectl get servicemonitor kubepocket -n kubepocket -o yaml | grep "release:"
```

**Collector errors:**
```bash
kubectl exec -n kubepocket deploy/kubepocket -- cat /var/log/kubepocket/collector.log
```

**node-exporter CrashLoopBackOff on Docker Desktop:**

This is a known Docker Desktop limitation. Install with `--set nodeExporter.enabled=false` or use `./install.sh` which handles this automatically.

**Duplicate series in Grafana after rollout:**

Stale series from old pods may appear for a few minutes after a deployment rollout. Values remain correct because `avg by` aggregation is active — only extra legend entries are shown briefly and disappear on their own.

**New cluster not appearing in Grafana dropdown:**

The Cluster dropdown is populated from Prometheus label values. After adding a new cluster, wait for at least one Prometheus scrape cycle (~30 seconds) for it to appear.
