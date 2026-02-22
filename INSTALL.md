# KubePocket — Kurulum Rehberi

## Gereksinimler

| Araç           | Versiyon |
| -------------- | -------- |
| Docker Desktop | 29+      |
| Minikube       | v1.37+   |
| Helm           | v3+      |
| kubectl        | v1.28+   |

---

## Sıfırdan Kurulum

### 1 — Minikube başlat

```bash
minikube start --cpus=2 --memory=4096 --driver=docker
```

---

### 2 — Image'ları hazırla

```bash
# Minikube'un Docker daemon'ını kullan
eval $(minikube docker-env)

# KubePocket image'ı build et
cd /Users/yunusolgun/Desktop/STUDY/python-works/DS/kubepocket
docker build -t kubepocket:local -f docker/Dockerfile .

# PostgreSQL image'ını çek (internet yokken offline kullanım için)
docker pull bitnami/postgresql:latest
```

---

### 3 — Helm dependency güncelle

```bash
helm dependency update ./helm/kubepocket
```

---

### 4 — Prometheus + Grafana kur

```bash
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set grafana.adminPassword=admin123 \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false
```

Pod'ların hazır olmasını bekle:

```bash
kubectl get pods -n monitoring -w
# Hepsi Running olunca Ctrl+C
```

---

### 5 — KubePocket kur

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
  --set postgresql.auth.password=kubepocket123
```

Pod'ların hazır olmasını bekle:

```bash
kubectl get pods -n kubepocket -w
# Her iki pod da Running olunca Ctrl+C
```

Beklenen çıktı:

```
kubepocket-xxxx           1/1     Running   0
kubepocket-postgresql-0   1/1     Running   0
```

---

### 6 — API key'i al

```bash
kubectl exec -n kubepocket deploy/kubepocket -- \
  cat /var/log/kubepocket/api.log | grep "Key:"
```

Çıktı:

```
Key: kp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Bu key'i güvenli bir yere kaydet.

---

### 7 — Port-forward'ları aç

**3 ayrı terminal** aç:

```bash
# Terminal 1 — KubePocket API
kubectl port-forward -n kubepocket svc/kubepocket 8000:8000

# Terminal 2 — Grafana
kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80

# Terminal 3 — Prometheus (isteğe bağlı)
kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090:9090
```

---

### 8 — API testi

```bash
# Summary
curl -s \
  -H "X-API-Key: <key>" \
  http://localhost:8000/api/metrics/summary | python3 -m json.tool

# Swagger UI
open http://localhost:8000/docs
```

---

### 9 — İlk veri topla

Collector otomatik çalışır (5 dakikada bir). Manuel tetiklemek için:

```bash
kubectl exec -n kubepocket deploy/kubepocket -- python collector/run_collector.py
```

---

### 10 — Grafana kurulumu

1. `http://localhost:3000` → kullanıcı: `admin`, şifre: `admin123`
2. **Dashboards → Import → Upload JSON file**
3. `kubepocket-dashboard.json` dosyasını seç
4. Datasource olarak **Prometheus** seç
5. **Import**

---

## Test Pod'larını Çalıştır

Farklı senaryoları simüle eden pod'lar:

```bash
kubectl apply -f testpods/01-healthy-pod.yaml       # Normal pod
kubectl apply -f testpods/02-high-cpu-pod.yaml      # CPU limitini zorlayan
kubectl apply -f testpods/03-oom-pod.yaml           # OOMKilled
kubectl apply -f testpods/04-crash-loop-pod.yaml    # CrashLoopBackOff
kubectl apply -f testpods/05-pending-pod.yaml       # Pending (schedule edilemez)
kubectl apply -f testpods/06-high-memory-pod.yaml   # Yüksek memory
kubectl apply -f testpods/07-wrong-image-pod.yaml   # ImagePullBackOff
kubectl apply -f testpods/08-anomaly-cpu-pod.yaml   # Anomaly tetikleyen
kubectl apply -f testpods/09-liveness-fail-pod.yaml # Liveness probe fail
kubectl apply -f testpods/10-resource-hungry-pod.yaml # Yüksek CPU + memory
```

Durumlarını kontrol et:

```bash
kubectl get pods -n default
```

---

## Güncelleme (Helm Upgrade)

Kod değişikliği sonrası:

```bash
eval $(minikube docker-env)
docker build -t kubepocket:local -f docker/Dockerfile .
kubectl rollout restart deployment/kubepocket -n kubepocket
kubectl rollout status deployment/kubepocket -n kubepocket
```

---

## Yararlı Komutlar

```bash
# Pod logları
kubectl logs -n kubepocket deploy/kubepocket
kubectl exec -n kubepocket deploy/kubepocket -- tail -f /var/log/kubepocket/api.log
kubectl exec -n kubepocket deploy/kubepocket -- tail -f /var/log/kubepocket/collector.log

# PostgreSQL'e bağlan
kubectl exec -n kubepocket kubepocket-postgresql-0 -- \
  env PGPASSWORD=kubepocket123 psql -U kubepocket -d kubepocket -c "\dt"

# Tüm podları listele
kubectl get pods -A

# Helm release durumu
helm status kubepocket -n kubepocket
helm status monitoring -n monitoring

# Her şeyi sil
helm uninstall kubepocket -n kubepocket
helm uninstall monitoring -n monitoring
minikube delete
```

---

## Servisler

| Servis              | URL                         | Açıklama                   |
| ------------------- | --------------------------- | -------------------------- |
| KubePocket API      | http://localhost:8000       | REST API                   |
| Swagger UI          | http://localhost:8000/docs  | API dokümantasyonu         |
| Grafana             | http://localhost:3000       | Dashboard (admin/admin123) |
| Prometheus          | http://localhost:9090       | Metrikler                  |
| Prometheus Exporter | (cluster içi) :8001/metrics | Raw metrikler              |

---

## Mimari

```
┌─────────────────────────────────────────────┐
│              kubepocket pod                  │
│                                             │
│  collector → PostgreSQL ← API (8000)        │
│                  ↑                          │
│  stats_daemon ───┘                          │
│                                             │
│  exporter (8001) ← Prometheus ← Grafana     │
└─────────────────────────────────────────────┘
```

---

## Sorun Giderme

**PostgreSQL bağlanamıyor:**

```bash
kubectl get pods -n kubepocket
kubectl logs -n kubepocket kubepocket-postgresql-0
```

**API key çalışmıyor (pod restart sonrası):**

```bash
# DB'deki aktif key'i kontrol et
kubectl exec -n kubepocket kubepocket-postgresql-0 -- \
  psql -U kubepocket -d kubepocket -c \
  "SELECT name, is_active, created_at FROM api_keys;"
```

**ServiceMonitor görünmüyor:**

```bash
kubectl get servicemonitor -n kubepocket
# Label kontrolü
kubectl get servicemonitor kubepocket -n kubepocket -o yaml | grep "release:"
```

**Collector hata veriyor:**

```bash
kubectl exec -n kubepocket deploy/kubepocket -- cat /var/log/kubepocket/collector.log
```
