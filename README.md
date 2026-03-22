# KubePocket — Kubernetes Cost & Resource Monitor

[![Version](https://img.shields.io/badge/version-3.0.0-blue.svg)](https://yunusolgun.github.io/kubepocket)
[![License](https://img.shields.io/badge/license-Commercial-green.svg)](LICENSE)

KubePocket is a lightweight, easy-to-install monitoring solution for Kubernetes that helps teams answer the question: **"Why is our cloud bill so high?"**

---

## 🚀 Features

- **Real-time monitoring** of CPU, memory, and pod restarts
- **Namespace-based resource tracking**
- **Cost optimization insights** and anomaly detection
- **Anomaly detection & forecasting** — z-score based alerts and 7-day CPU forecasts
- **Multi-cluster support** — monitor multiple clusters from a single Grafana dashboard
- **Prometheus metrics exporter** for Grafana integration
- **Webhook notifications** — send alerts to Slack, Microsoft Teams, or any HTTP endpoint
- **Weekly reports** — automated weekly summary delivered to Slack or Teams (waste, anomalies, alerts, trends)
- **Offline RSA license system** — no license server required
- **Zero configuration** — works out of the box with minikube, Docker Desktop, or any cluster

---

## 📦 Installation

### Automatic (recommended)

```bash
./install.sh
```

The install script auto-detects your environment (minikube, docker-desktop, or custom) and handles everything: Docker build, Helm install, Prometheus/Grafana stack, and Grafana dashboard import.

### Production install

```bash
MODE=production \
  EXISTING_STACK=true \
  MONITORING_NAMESPACE=observability \
  IMAGE_REPOSITORY=your-registry/kubepocket \
  IMAGE_TAG=3.0.0 \
  CLUSTER_NAME=prod-eu-west \
  LICENSE_KEY=kp_... \
  ./install.sh
```

See [INSTALL.md](INSTALL.md) for full documentation.

### Uninstall

```bash
./install.sh uninstall          # Remove KubePocket only
./install.sh uninstall --all    # Remove KubePocket + monitoring stack
```

---

## 🌐 Multi-Cluster

KubePocket supports multiple clusters out of the box. Each cluster runs its own KubePocket instance connected to a shared PostgreSQL database. The Grafana dashboard includes a **Cluster** dropdown to filter or compare across clusters.

```
cluster-eu  →  KubePocket (CLUSTER_NAME=prod-eu)  ┐
cluster-us  →  KubePocket (CLUSTER_NAME=prod-us)  ├──→  Shared PostgreSQL  ←──  Grafana
cluster-stg →  KubePocket (CLUSTER_NAME=staging)  ┘
```

See [INSTALL.md — Multi-Cluster Setup](INSTALL.md#multi-cluster-setup) for details.

---

## 🔔 Webhook Notifications

KubePocket can send alert notifications to Slack, Microsoft Teams, or any generic HTTP endpoint. Each provider is optional and multiple providers can be active simultaneously. Notifications are sent only once per alert — no duplicate messages.

### Supported providers

| Provider         | Environment Variable                  |
|------------------|---------------------------------------|
| Slack            | `KUBEPOCKET_SLACK_WEBHOOK_URL`        |
| Microsoft Teams  | `KUBEPOCKET_TEAMS_WEBHOOK_URL`        |
| Generic HTTP POST| `KUBEPOCKET_WEBHOOK_URL`              |

### Quick setup

```bash
helm upgrade kubepocket ./helm/kubepocket \
  --namespace kubepocket \
  --reuse-values \
  --set webhook.slackUrl="https://hooks.slack.com/services/..."
```

Set `webhook.minSeverity` to `critical` to only receive notifications for critical alerts (default: `warning`).

### Weekly report

A weekly summary is automatically sent every Monday at 09:00 UTC when a webhook is configured. The report includes cluster health, CPU/memory trends vs the previous week, top waste and anomaly pods, active alerts, PVC issues, and longest-running pods.

```bash
# Change schedule (e.g. Friday at 08:00 UTC)
helm upgrade kubepocket ./helm/kubepocket \\
  --namespace kubepocket \\
  --reuse-values \\
  --set webhook.weeklyReport.day=4 \\
  --set webhook.weeklyReport.hour=8
```

See [INSTALL.md — Webhook Notifications](INSTALL.md#webhook-notifications) for full documentation.

---

## 🔑 Licensing

KubePocket uses an **offline RSA-signed license key** system. No internet connection or license server is required for verification.

### Tiers

| Feature           | Free          | Pro                  |
|-------------------|---------------|----------------------|
| Price             | Free forever  | $99/cluster/year or $12/cluster/month |
| Clusters          | 1             | Unlimited            |
| Namespaces        | 4             | Unlimited            |
| Retention         | 30 days       | 365 days             |
| Metrics           | ✅            | ✅                   |
| Alerts            | ✅            | ✅                   |
| Anomaly Detection | ✅            | ✅                   |
| Forecast          | ✅            | ✅                   |
| Weekly Reports    | ✅            | ✅                   |
| Priority Support  | ❌            | ✅                   |

Free tier includes a **30-day community trial**. After expiry the system continues to operate with free tier limits and shows a warning in the license API response.

### Getting a Pro license

| Plan              | Price                  |
|-------------------|------------------------|
| Pro — Annual      | $99 / cluster / year   |
| Pro — Monthly     | $12 / cluster / month  |

To purchase a Pro license, contact us at [yunus.olgun@outlook.com](mailto:yunus.olgun@outlook.com) with your company name and number of clusters. You will receive a signed license key by e-mail within one business day.

### Applying a license

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

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   kubepocket pod                         │
│                                                         │
│  collector ──→ PostgreSQL ←── API (8000)                │
│                    ↑                                    │
│  stats_daemon ─────┘                                    │
│                                                         │
│  exporter (8001) ←── Prometheus ←── Grafana             │
└─────────────────────────────────────────────────────────┘

Multi-cluster:
  cluster-A: kubepocket ──→ ┐
  cluster-B: kubepocket ──→ ├──→ shared PostgreSQL ←── exporter ←── Grafana
  cluster-C: kubepocket ──→ ┘
```

---

## 🖥 Dashboard Preview

After installation, KubePocket automatically imports a pre-built Grafana dashboard. It provides a real-time overview of all your namespaces, pod resource usage, restart counts, anomaly scores, cost distribution, active alerts, and Kubernetes events — all in one place. Use the **Cluster** and **Namespace** dropdowns to filter across your entire infrastructure.

| | | |
|---|---|---|
| ![Overview](https://yunusolgun.github.io/kubepocket/preview-1-overview.png) | ![Recommendations](https://yunusolgun.github.io/kubepocket/preview-2-recomendations.png) | ![Cost](https://yunusolgun.github.io/kubepocket/preview-3-cost.png) |
| ![Waste](https://yunusolgun.github.io/kubepocket/preview-4-waste.png) | ![Pod Anomaly](https://yunusolgun.github.io/kubepocket/preview-5-podanomaly.png) | ![Pod Details](https://yunusolgun.github.io/kubepocket/preview-6-poddetails.png) |
| ![Events](https://yunusolgun.github.io/kubepocket/preview-7-events.png) | ![Real Usage](https://yunusolgun.github.io/kubepocket/preview-8-events.png) | ![Nodes](https://yunusolgun.github.io/kubepocket/preview-9-nodes.png) |
| ![Storage](https://yunusolgun.github.io/kubepocket/preview-11-storage.png) | ![Alerts](https://yunusolgun.github.io/kubepocket/preview-11-storagealerts.png) | |

> View the full interactive dashboard gallery at [yunusolgun.github.io/kubepocket](https://yunusolgun.github.io/kubepocket/#dashboard)

---

## 📊 Services

| Service             | URL                         | Description                |
|---------------------|-----------------------------|----------------------------|
| KubePocket API      | http://localhost:8000       | REST API                   |
| Swagger UI          | http://localhost:8000/docs  | API documentation          |
| Grafana             | http://localhost:3000       | Dashboard (admin/admin123) |
| Prometheus          | http://localhost:9090       | Metrics                    |
| Prometheus Exporter | (in-cluster) :8001/metrics  | Raw metrics                |

---

## 📁 Project Structure

```
kubepocket/
├── api/                       # FastAPI REST API
│   └── routes/                # Endpoints (metrics, cost, nodes, storage, license)
├── collector/                 # Kubernetes data collector
├── prometheus_exporter/       # Prometheus metrics exporter
├── licensing/                 # License verification system
├── helm/kubepocket/           # Helm chart
├── docker/                    # Dockerfile & .dockerignore
├── db/                        # SQLAlchemy models & migrations
├── testpods/                  # Test pod manifests
├── kubepocket-dashboard.json  # Grafana dashboard
└── install.sh                 # One-command installer
```
