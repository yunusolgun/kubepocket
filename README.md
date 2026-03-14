# KubePocket — Kubernetes Cost & Resource Monitor

[![Version](https://img.shields.io/badge/version-3.0.0-blue.svg)](https://kubepocket.com)
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

## 🔑 Licensing

KubePocket uses an **offline RSA-signed license key** system. No internet connection or license server is required for verification.

### Tiers

| Feature           | Free      | Pro        |
|-------------------|-----------|------------|
| Clusters          | 1         | Unlimited  |
| Namespaces        | 4         | Unlimited  |
| Retention         | 30 days   | 365 days   |
| Metrics           | ✅        | ✅         |
| Alerts            | ✅        | ✅         |
| Anomaly Detection | ✅        | ✅         |
| Forecast          | ✅        | ✅         |

Free tier includes a **30-day community trial**. After expiry the system continues to operate with free tier limits and shows a warning in the license API response.

### Applying a license

```bash
helm upgrade kubepocket ./helm/kubepocket \
  --namespace kubepocket \
  --reuse-values \
  --set licenseKey="kp_..."
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
│   ├── license.py             # Offline RSA verifier (shipped in Docker)
│   └── generate_license.py   # Key generator (NOT shipped in Docker)
├── helm/kubepocket/           # Helm chart
├── docker/                    # Dockerfile & .dockerignore
├── db/                        # SQLAlchemy models & migrations
├── testpods/                  # Test pod manifests
├── kubepocket-dashboard.json  # Grafana dashboard
└── install.sh                 # One-command installer
```
