# KubePocket - Kubernetes Cost & Resource Monitor

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](https://kubepocket.com)
[![License](https://img.shields.io/badge/license-Commercial-green.svg)](LICENSE)

KubePocket is a lightweight, easy-to-install monitoring solution for Kubernetes that helps teams answer the question: **"Why is our cloud bill so high?"**

## 🚀 Features

- **Real-time monitoring** of CPU, memory, and pod restarts
- **Namespace-based resource tracking**
- **Cost optimization insights** and anomaly detection
- **Prometheus metrics exporter** for Grafana integration
- **Daily/weekly email reports**
- **Zero configuration** - works out of the box

## 📦 Installation

### One-line installation

```bash
curl -sSL https://get.kubepocket.com | bash
```

### Manual installation with Helm

```bash
helm repo add kubepocket https://charts.kubepocket.com
helm install kubepocket kubepocket/kubepocket \
  --namespace kubepocket \
  --create-namespace
```

### Manual installation with kubectl

```bash
kubectl create namespace kubepocket
kubectl apply -f https://kubepocket.com/latest.yaml
```
