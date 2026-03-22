#!/usr/bin/env python3
# collector/weekly_report.py
"""
Weekly summary report — sent via webhook (Slack, Teams, or generic).

Content:
  - Cluster health overview (namespaces, pods, CPU, memory)
  - CPU/memory trend vs previous week (% change)
  - Top 5 waste pods
  - Top 5 anomaly pods
  - Top 5 pods by restart count
  - Active alert summary (critical / warning)
  - PVC health (unbound or near-full PVCs)
  - Longest running pods (uptime)

Schedule: controlled by KUBEPOCKET_WEEKLY_REPORT_DAY and
          KUBEPOCKET_WEEKLY_REPORT_HOUR env vars.
          Default: every Monday at 09:00 UTC.
"""

import os
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

CLUSTER_NAME  = os.getenv('CLUSTER_NAME', 'default')
REPORT_DAY    = int(os.getenv('KUBEPOCKET_WEEKLY_REPORT_DAY',  '0'))  # 0=Mon
REPORT_HOUR   = int(os.getenv('KUBEPOCKET_WEEKLY_REPORT_HOUR', '9'))  # UTC


# ── Schedule check ────────────────────────────────────────────────────────────

def should_send_report() -> bool:
    """Returns True if the current UTC time matches the configured schedule."""
    now = datetime.utcnow()
    return now.weekday() == REPORT_DAY and now.hour == REPORT_HOUR


# ── Data gathering ────────────────────────────────────────────────────────────

def _gather_report_data(db) -> dict:
    from db.models import Metric, Alert, KubeEvent
    from db.repository import MetricRepository
    from collector.cost import detect_waste
    from sqlalchemy import func

    repo    = MetricRepository(db)
    now     = datetime.utcnow()
    week_ago = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)

    # ── Current week metrics ──────────────────────────────────────────────────
    current = repo.get_latest_per_namespace()
    namespaces  = {m.namespace for m in current}
    total_pods  = sum(len(m.pod_data) for m in current)
    total_cpu   = sum(m.total_cpu    for m in current)
    total_mem   = sum(m.total_memory for m in current)
    total_rst   = sum(m.total_restarts for m in current)

    # ── Previous week avg (for trend) ────────────────────────────────────────
    prev_metrics = (
        db.query(Metric)
        .filter(Metric.timestamp.between(two_weeks_ago, week_ago))
        .all()
    )
    prev_cpu = sum(m.total_cpu    for m in prev_metrics) / max(len(prev_metrics), 1)
    prev_mem = sum(m.total_memory for m in prev_metrics) / max(len(prev_metrics), 1)

    # Only calculate trend if previous week had meaningful data (>0.1 cores/GiB)
    # Cap at ±999% to avoid misleading numbers on first run or sparse data
    if prev_cpu >= 0.1:
        cpu_trend_pct = round(max(-999, min(999, (total_cpu - prev_cpu) / prev_cpu * 100)), 1)
    else:
        cpu_trend_pct = 0.0

    if prev_mem >= 0.1:
        mem_trend_pct = round(max(-999, min(999, (total_mem - prev_mem) / prev_mem * 100)), 1)
    else:
        mem_trend_pct = 0.0

    # ── Waste ─────────────────────────────────────────────────────────────────
    waste_data  = detect_waste(current)
    waste_pods  = sorted(
        waste_data.get('waste_pods', []),
        key=lambda x: x.get('waste_score', 0), reverse=True
    )[:5]

    # ── Anomaly (top pods by restart + cpu anomaly) ───────────────────────────
    all_pods = []
    for m in current:
        ns_avg_cpu = m.total_cpu / max(len(m.pod_data), 1)
        for pod in m.pod_data:
            cpu_req  = pod.get('cpu_request', 0)
            restarts = pod.get('restart_count', 0)
            cpu_ratio  = cpu_req / max(ns_avg_cpu, 0.001)
            cpu_score  = min(100.0, max(0.0, (cpu_ratio - 1) * 30))
            rst_score  = min(100.0, restarts * 10.0)
            anom_score = (cpu_score * 0.4) + (rst_score * 0.6)
            all_pods.append({
                'pod':           pod.get('name', ''),
                'namespace':     pod.get('namespace', m.namespace),
                'anomaly_score': round(anom_score, 1),
                'restarts':      restarts,
                'cpu_request':   cpu_req,
                'age_hours':     pod.get('age_hours', 0),
                'status':        pod.get('status', 'Unknown'),
            })

    top_anomaly  = sorted(all_pods, key=lambda x: x['anomaly_score'], reverse=True)[:5]
    top_restarts = sorted(all_pods, key=lambda x: x['restarts'],      reverse=True)[:5]
    top_uptime   = sorted(
        [p for p in all_pods if p['status'] == 'Running'],
        key=lambda x: x['age_hours'], reverse=True
    )[:5]

    # ── Alerts ────────────────────────────────────────────────────────────────
    active_alerts = repo.get_active_alerts()
    critical_count = sum(1 for a in active_alerts if a.severity == 'critical')
    warning_count  = sum(1 for a in active_alerts if a.severity == 'warning')
    new_this_week  = sum(1 for a in active_alerts if a.created_at >= week_ago)

    # ── PVC health ────────────────────────────────────────────────────────────
    pvc_issues = []
    try:
        from collector.k8s_client import K8sClient
        k8s  = K8sClient()
        pvcs = k8s.collect_pvc_metrics()
        for pvc in pvcs:
            if not pvc['bound']:
                pvc_issues.append({'name': pvc['name'], 'namespace': pvc['namespace'],
                                   'issue': 'Unbound', 'pct': None})
            elif pvc.get('used_pct') is not None and pvc['used_pct'] >= 75:
                pvc_issues.append({'name': pvc['name'], 'namespace': pvc['namespace'],
                                   'issue': f"{pvc['used_pct']}% full",
                                   'pct': pvc['used_pct']})
    except Exception as e:
        logger.warning(f"PVC check failed: {e}")

    return {
        'generated_at':    now.strftime('%Y-%m-%d %H:%M UTC'),
        'cluster':         CLUSTER_NAME,
        'namespaces':      len(namespaces),
        'total_pods':      total_pods,
        'total_cpu':       round(total_cpu, 2),
        'total_memory':    round(total_mem, 2),
        'total_restarts':  total_rst,
        'cpu_trend_pct':   cpu_trend_pct,
        'mem_trend_pct':   mem_trend_pct,
        'waste_pods':      waste_pods,
        'top_anomaly':     top_anomaly,
        'top_restarts':    top_restarts,
        'top_uptime':      top_uptime,
        'critical_alerts': critical_count,
        'warning_alerts':  warning_count,
        'new_alerts_week': new_this_week,
        'pvc_issues':      pvc_issues,
    }


# ── Slack payload ─────────────────────────────────────────────────────────────

def _slack_weekly_payload(data: dict) -> dict:
    def trend_emoji(pct):
        if pct > 10:   return f"📈 +{pct}%"
        if pct < -10:  return f"📉 {pct}%"
        return f"➡️ {pct:+}%"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"📊 KubePocket Weekly Report — {data['cluster']}"}
        },
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Generated {data['generated_at']}"}]},
        {"type": "divider"},

        # Cluster overview
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*🌐 Cluster Overview*"},
            "fields": [
                {"type": "mrkdwn", "text": f"*Namespaces:*\n{data['namespaces']}"},
                {"type": "mrkdwn", "text": f"*Pods:*\n{data['total_pods']}"},
                {"type": "mrkdwn", "text": f"*CPU (cores):*\n{data['total_cpu']} {trend_emoji(data['cpu_trend_pct'])}"},
                {"type": "mrkdwn", "text": f"*Memory (GiB):*\n{data['total_memory']} {trend_emoji(data['mem_trend_pct'])}"},
                {"type": "mrkdwn", "text": f"*Total Restarts:*\n{data['total_restarts']}"},
            ]
        },
        {"type": "divider"},

        # Alerts
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*🚨 Active Alerts*\n"
                    f"🔴 Critical: {data['critical_alerts']}  |  "
                    f"🟠 Warning: {data['warning_alerts']}  |  "
                    f"New this week: {data['new_alerts_week']}"
                )
            }
        },
        {"type": "divider"},
    ]

    # Top waste pods
    if data['waste_pods']:
        lines = "\n".join(
            f"• `{p['pod']}` ({p['namespace']}) — score {p.get('waste_score', 0):.0f}"
            for p in data['waste_pods']
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*🗑️ Top Waste Pods*\n{lines}"}
        })
        blocks.append({"type": "divider"})

    # Top anomaly pods
    if data['top_anomaly']:
        lines = "\n".join(
            f"• `{p['pod']}` ({p['namespace']}) — score {p['anomaly_score']}, {p['restarts']} restarts"
            for p in data['top_anomaly']
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*🚨 Top Anomaly Pods*\n{lines}"}
        })
        blocks.append({"type": "divider"})

    # Top restart pods
    if data['top_restarts']:
        lines = "\n".join(
            f"• `{p['pod']}` ({p['namespace']}) — {p['restarts']} restarts"
            for p in data['top_restarts']
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*🔄 Most Restarted Pods*\n{lines}"}
        })
        blocks.append({"type": "divider"})

    # PVC issues
    if data['pvc_issues']:
        lines = "\n".join(
            f"• `{p['name']}` ({p['namespace']}) — {p['issue']}"
            for p in data['pvc_issues']
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*💾 PVC Issues*\n{lines}"}
        })
        blocks.append({"type": "divider"})

    # Longest running pods
    if data['top_uptime']:
        lines = "\n".join(
            f"• `{p['pod']}` ({p['namespace']}) — {p['age_hours']:.0f}h uptime"
            for p in data['top_uptime']
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*✅ Longest Running Pods*\n{lines}"}
        })

    return {"blocks": blocks}


# ── Teams payload ─────────────────────────────────────────────────────────────

def _teams_weekly_payload(data: dict) -> dict:
    def trend_str(pct):
        arrow = "↑" if pct > 0 else ("↓" if pct < 0 else "→")
        return f"{arrow} {abs(pct)}%"

    facts = [
        {"name": "Cluster",          "value": data['cluster']},
        {"name": "Namespaces",       "value": str(data['namespaces'])},
        {"name": "Pods",             "value": str(data['total_pods'])},
        {"name": "CPU (cores)",      "value": f"{data['total_cpu']} {trend_str(data['cpu_trend_pct'])}"},
        {"name": "Memory (GiB)",     "value": f"{data['total_memory']} {trend_str(data['mem_trend_pct'])}"},
        {"name": "Total Restarts",   "value": str(data['total_restarts'])},
        {"name": "Critical Alerts",  "value": str(data['critical_alerts'])},
        {"name": "Warning Alerts",   "value": str(data['warning_alerts'])},
        {"name": "New Alerts (week)","value": str(data['new_alerts_week'])},
    ]

    if data['waste_pods']:
        facts.append({"name": "Top Waste Pod",
                      "value": f"{data['waste_pods'][0]['pod']} ({data['waste_pods'][0]['namespace']})"})
    if data['top_anomaly']:
        facts.append({"name": "Top Anomaly Pod",
                      "value": f"{data['top_anomaly'][0]['pod']} ({data['top_anomaly'][0]['namespace']})"})
    if data['pvc_issues']:
        facts.append({"name": "PVC Issues",
                      "value": ", ".join(p['name'] for p in data['pvc_issues'])})

    return {
        "@type":       "MessageCard",
        "@context":    "https://schema.org/extensions",
        "themeColor":  "0076D7",
        "summary":     f"KubePocket Weekly Report — {data['cluster']}",
        "sections":    [{"activityTitle": f"📊 KubePocket Weekly Report — {data['cluster']}", "facts": facts}]
    }


# ── Generic payload ───────────────────────────────────────────────────────────

def _generic_weekly_payload(data: dict) -> dict:
    return {"type": "weekly_report", **data}


# ── Send ──────────────────────────────────────────────────────────────────────

def send_weekly_report(db) -> bool:
    """
    Gather weekly data and send to all configured webhook providers.
    Returns True if at least one provider succeeded.
    """
    from collector.webhook import (
        SLACK_WEBHOOK_URL, TEAMS_WEBHOOK_URL, GENERIC_WEBHOOK_URL, _post_json
    )

    if not any([SLACK_WEBHOOK_URL, TEAMS_WEBHOOK_URL, GENERIC_WEBHOOK_URL]):
        logger.debug("No webhook URLs configured — skipping weekly report")
        return False

    logger.info(f"📊 Generating weekly report for cluster: {CLUSTER_NAME}")

    try:
        data = _gather_report_data(db)
    except Exception as e:
        logger.error(f"Weekly report data gathering failed: {e}", exc_info=True)
        return False

    success = False

    if SLACK_WEBHOOK_URL:
        ok = _post_json(SLACK_WEBHOOK_URL, _slack_weekly_payload(data), 'Slack (weekly)')
        success = success or ok

    if TEAMS_WEBHOOK_URL:
        ok = _post_json(TEAMS_WEBHOOK_URL, _teams_weekly_payload(data), 'Teams (weekly)')
        success = success or ok

    if GENERIC_WEBHOOK_URL:
        ok = _post_json(GENERIC_WEBHOOK_URL, _generic_weekly_payload(data), 'Generic (weekly)')
        success = success or ok

    if success:
        logger.info("✅ Weekly report sent successfully")
    else:
        logger.warning("⚠️  Weekly report failed to send")

    return success
