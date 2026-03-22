#!/usr/bin/env python3
# collector/webhook.py
"""
Webhook notifications for KubePocket alerts.

Supported providers:
  - Slack  (KUBEPOCKET_SLACK_WEBHOOK_URL)
  - Teams  (KUBEPOCKET_TEAMS_WEBHOOK_URL)
  - Generic JSON POST (KUBEPOCKET_WEBHOOK_URL)

Each provider is optional. Multiple providers can be active simultaneously.
Notifications are only sent once per alert (tracked via Alert.webhook_sent).
"""

import os
import json
import logging
import urllib.request
import urllib.error
from datetime import datetime

logger = logging.getLogger(__name__)

CLUSTER_NAME        = os.getenv('CLUSTER_NAME', 'default')
SLACK_WEBHOOK_URL   = os.getenv('KUBEPOCKET_SLACK_WEBHOOK_URL', '')
TEAMS_WEBHOOK_URL   = os.getenv('KUBEPOCKET_TEAMS_WEBHOOK_URL', '')
GENERIC_WEBHOOK_URL = os.getenv('KUBEPOCKET_WEBHOOK_URL', '')

# Minimum severity to notify. Options: warning, critical
# Set KUBEPOCKET_WEBHOOK_MIN_SEVERITY=critical to only notify on critical alerts.
MIN_SEVERITY = os.getenv('KUBEPOCKET_WEBHOOK_MIN_SEVERITY', 'warning')
SEVERITY_ORDER = {'warning': 0, 'critical': 1}


def _should_notify(severity: str) -> bool:
    return SEVERITY_ORDER.get(severity, 0) >= SEVERITY_ORDER.get(MIN_SEVERITY, 0)


def _post_json(url: str, payload: dict, provider: str) -> bool:
    try:
        data = json.dumps(payload).encode('utf-8')
        req  = urllib.request.Request(
            url,
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 201, 202, 204):
                logger.info(f"  📣 Webhook sent ({provider}): {resp.status}")
                return True
            else:
                logger.warning(f"  ⚠️  Webhook {provider} returned {resp.status}")
                return False
    except urllib.error.URLError as e:
        logger.warning(f"  ⚠️  Webhook {provider} failed: {e}")
        return False
    except Exception as e:
        logger.warning(f"  ⚠️  Webhook {provider} error: {e}")
        return False


def _slack_payload(alert) -> dict:
    emoji = "🔴" if alert.severity == 'critical' else "🟠"
    color = "#FF0000" if alert.severity == 'critical' else "#FFA500"
    return {
        "attachments": [{
            "color": color,
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{emoji} *KubePocket Alert* — `{CLUSTER_NAME}`"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Severity:*\n{alert.severity.upper()}"},
                        {"type": "mrkdwn", "text": f"*Namespace:*\n{alert.namespace or '—'}"},
                        {"type": "mrkdwn", "text": f"*Message:*\n{alert.message}"},
                        {"type": "mrkdwn", "text": f"*Time:*\n{alert.created_at.strftime('%Y-%m-%d %H:%M UTC')}"},
                    ]
                }
            ]
        }]
    }


def _teams_payload(alert) -> dict:
    color = "FF0000" if alert.severity == 'critical' else "FFA500"
    return {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "themeColor": color,
        "summary": f"KubePocket Alert — {alert.severity.upper()}",
        "sections": [{
            "activityTitle": f"🚨 KubePocket Alert — `{CLUSTER_NAME}`",
            "facts": [
                {"name": "Severity",  "value": alert.severity.upper()},
                {"name": "Namespace", "value": alert.namespace or "—"},
                {"name": "Message",   "value": alert.message},
                {"name": "Time",      "value": alert.created_at.strftime('%Y-%m-%d %H:%M UTC')},
            ]
        }]
    }


def _generic_payload(alert) -> dict:
    return {
        "cluster":   CLUSTER_NAME,
        "severity":  alert.severity,
        "namespace": alert.namespace,
        "message":   alert.message,
        "created_at": alert.created_at.isoformat(),
    }


def send_alert_notification(alert) -> bool:
    """
    Send webhook notifications for a single alert.
    Returns True if at least one provider succeeded.
    Skips if below MIN_SEVERITY.
    """
    if not _should_notify(alert.severity):
        return False

    if not any([SLACK_WEBHOOK_URL, TEAMS_WEBHOOK_URL, GENERIC_WEBHOOK_URL]):
        return False

    success = False

    if SLACK_WEBHOOK_URL:
        ok = _post_json(SLACK_WEBHOOK_URL, _slack_payload(alert), 'Slack')
        success = success or ok

    if TEAMS_WEBHOOK_URL:
        ok = _post_json(TEAMS_WEBHOOK_URL, _teams_payload(alert), 'Teams')
        success = success or ok

    if GENERIC_WEBHOOK_URL:
        ok = _post_json(GENERIC_WEBHOOK_URL, _generic_payload(alert), 'Generic')
        success = success or ok

    return success


def notify_new_alerts(db, new_alert_ids: list[int]) -> int:
    """
    Send notifications for alerts that haven't been notified yet.
    Marks them as notified after a successful send.
    Returns the number of notifications sent.
    """
    if not new_alert_ids:
        return 0
    if not any([SLACK_WEBHOOK_URL, TEAMS_WEBHOOK_URL, GENERIC_WEBHOOK_URL]):
        return 0

    from db.models import Alert

    alerts = (
        db.query(Alert)
        .filter(
            Alert.id.in_(new_alert_ids),
            Alert.webhook_sent == False,
        )
        .all()
    )

    sent = 0
    for alert in alerts:
        ok = send_alert_notification(alert)
        if ok:
            alert.webhook_sent = True
            sent += 1

    if sent:
        db.commit()
        print(f"  📣 Webhook notifications sent: {sent}")

    return sent
