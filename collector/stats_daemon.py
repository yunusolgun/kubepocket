#!/usr/bin/env python3
# collector/stats_daemon.py
import sys
import os
import time
import logging
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector.statistics import StatisticsCalculator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_stats_daemon(interval=3600):
    logger.info(f"📊 Statistics daemon started (interval: {interval}s)")

    while True:
        try:
            from db.models import SessionLocal
            db = SessionLocal()
            try:
                calc = StatisticsCalculator(db)
                calc.calculate_statistics()
                calc.detect_anomalies()
                logger.info("✅ Statistics & anomaly detection complete")
            finally:
                db.close()

            logger.info(f"😴 Sleeping {interval}s...")
            time.sleep(interval)

        except KeyboardInterrupt:
            logger.info("👋 Shutting down...")
            break
        except Exception as e:
            logger.error(f"❌ Error: {e}", exc_info=True)
            time.sleep(60)


if __name__ == "__main__":
    run_stats_daemon()
