"""Prometheus metrics exporter — scraped at ``GET /metrics``
(``routers/metrics.py``).

Two kinds of series live here:

- Live counters, incremented as requests happen (``WEBHOOK_REQUESTS_TOTAL``,
  ``ALERTS_INGESTED_TOTAL``) — incremented inline from
  ``routers/webhook.py``, right alongside the existing audit log write.
- Point-in-time gauges reflecting current DB state (alert counts by
  status/severity, node count, last successful ingest) — these aren't kept
  updated on every write; ``routers/metrics.py`` refreshes them from the DB
  on every scrape instead, reusing ``crud.dashboard_stats``.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge

WEBHOOK_REQUESTS_TOTAL = Counter(
    "promhis_webhook_requests_total",
    "Alertmanager webhook requests received, by auth result and HTTP status code.",
    ["auth_result", "status_code"],
)

ALERTS_INGESTED_TOTAL = Counter(
    "promhis_alerts_ingested_total",
    "Alert events ingested from Alertmanager webhook deliveries.",
)

ALERTS_BY_STATUS = Gauge(
    "promhis_alerts_by_status",
    "Current alerts (latest known state per fingerprint) by status.",
    ["status"],
)

ALERTS_BY_SEVERITY = Gauge(
    "promhis_alerts_by_severity",
    "Current alerts (latest known state per fingerprint) by severity.",
    ["severity"],
)

NODES_TOTAL = Gauge(
    "promhis_nodes_total",
    "Distinct nodes with at least one known alert.",
)

LAST_SUCCESSFUL_INGEST_TIMESTAMP = Gauge(
    "promhis_last_successful_ingest_timestamp_seconds",
    "Unix timestamp of the last webhook delivery Promhis accepted.",
)

MTTR_SECONDS_AVG = Gauge(
    "promhis_mttr_seconds_avg",
    "Average time-to-resolution (seconds) across alerts resolved in the last 14 days.",
)

TOP_NOISY_ALERTS_EVENTS = Gauge(
    "promhis_top_noisy_alerts_events",
    "Event count in the last 14 days for the top 10 noisiest alertnames.",
    ["alertname"],
)

AUDIT_LOG_ENTRIES_TOTAL = Gauge(
    "promhis_audit_log_entries_total",
    "Total webhook ingest requests recorded in the audit log (all-time, survives restarts), by auth result.",
    ["auth_result"],
)

NOTIFICATION_SENDS_TOTAL = Counter(
    "promhis_notification_sends_total",
    "Outbound notification channel sends, by channel and result.",
    ["channel", "result"],
)
