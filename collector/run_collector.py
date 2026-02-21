#!/usr/bin/env python3
# collector/run_collector.py
import sys
import os
import time
from datetime import datetime
import argparse

# Proje kök dizinini ekle
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector.k8s_client import K8sClient
from db.repository import MetricRepository
from db.models import init_db

def collect_once(context=None):
    """Tek seferlik metrik toplama"""
    print(f"\n{'='*50}")
    print(f"🚀 KubePocket Collector Başlıyor - {datetime.now()}")
    print('='*50)
    
    # Veritabanını başlat
    init_db()
    
    # Kubernetes client
    try:
        client = K8sClient(context=context)
    except Exception as e:
        print(f"❌ Kubernetes bağlantı hatası: {e}")
        return False
    
    # Repository
    repo = MetricRepository()
    
    # Cluster bilgisi
    cluster_name = f"minikube-{datetime.now().strftime('%Y%m%d')}"
    cluster = repo.get_or_create_cluster(cluster_name, context or 'minikube')
    
    # Metrikleri topla
    print("\n📡 Metrikler toplanıyor...")
    metrics = client.collect_all_metrics()
    
    if not metrics:
        print("❌ Hiç metrik toplanamadı!")
        return False
    
    # Veritabanına kaydet
    saved = repo.save_metrics(cluster.id, metrics)
    
    # Alert kontrolü
    problematic = client.get_high_restart_pods(threshold=5)
    for p in problematic:
        alert_msg = f"Pod {p['pod_name']} {p['restarts']} kez restart aldı!"
        repo.create_alert(cluster.id, p['namespace'], alert_msg, 'warning')
    
    # Özet
    print(f"\n{'='*50}")
    print(f"✅ İşlem Tamamlandı!")
    print(f"📊 Toplanan namespace: {len(metrics)}")
    print(f"💾 Kaydedilen kayıt: {saved}")
    print(f"🚨 Aktif alert: {len(repo.get_active_alerts(cluster.id))}")
    print(f"{'='*50}\n")
    
    repo.close()
    return True

def run_daemon(interval=300):
    """Sürekli çalışan mod - her interval saniyede bir topla"""
    print(f"🔄 Daemon mod başladı, interval: {interval} saniye")
    
    while True:
        try:
            collect_once()
            print(f"😴 {interval} saniye bekleniyor...")
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n👋 Kapatılıyor...")
            break
        except Exception as e:
            print(f"❌ Hata: {e}")
            print(f"😴 60 saniye sonra tekrar deneniyor...")
            time.sleep(60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='KubePocket Collector')
    parser.add_argument('--daemon', action='store_true', help='Daemon modunda çalış')
    parser.add_argument('--interval', type=int, default=300, help='Toplama aralığı (saniye)')
    parser.add_argument('--context', help='Kubernetes context')
    
    args = parser.parse_args()
    
    if args.daemon:
        run_daemon(args.interval)
    else:
        collect_once(args.context)
