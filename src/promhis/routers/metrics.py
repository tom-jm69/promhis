"""``GET /metrics`` — Prometheus scrape endpoint.

Open by default, same posture as ``/healthz``, unless
`PROMHIS_METRICS_ALLOWED_IPS` and/or `PROMHIS_METRICS_USER`+
`PROMHIS_METRICS_PASSWORD` are configured (see `auth.require_metrics_auth`)
— independent of the dashboard session cookie and the webhook's own
Basic/Bearer scheme.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.ext.asyncio import AsyncSession

from promhis import crud
from promhis.auth import require_metrics_auth
from promhis.db import get_session
from promhis.metrics import (
    ALERTS_BY_SEVERITY,
    ALERTS_BY_STATUS,
    AUDIT_LOG_ENTRIES_TOTAL,
    LAST_SUCCESSFUL_INGEST_TIMESTAMP,
    MTTR_SECONDS_AVG,
    NODES_TOTAL,
    TOP_NOISY_ALERTS_EVENTS,
)

router = APIRouter(tags=["meta"])

# How many days back the MTTR/noisy-alert gauges below look, matching the
# dashboard's own default window (crud.dashboard_stats/mttr_seconds/
# top_noisy_alerts all default to 14 days).
_WINDOW_DAYS = 14


@router.get("/metrics", dependencies=[Depends(require_metrics_auth)])
async def metrics(session: AsyncSession = Depends(get_session)) -> Response:
    stats = await crud.dashboard_stats(session)
    ALERTS_BY_STATUS.labels(status="firing").set(stats.firing)
    ALERTS_BY_STATUS.labels(status="resolved").set(stats.resolved)

    # Cleared first: a severity/alertname/auth_result no longer present this
    # scrape must not keep reporting its last-seen value forever.
    ALERTS_BY_SEVERITY.clear()
    for entry in stats.by_severity:
        ALERTS_BY_SEVERITY.labels(severity=entry.severity).set(entry.count)
    NODES_TOTAL.set(stats.nodes)

    last_ingest = await crud.last_successful_ingest(session)
    if last_ingest is not None:
        LAST_SUCCESSFUL_INGEST_TIMESTAMP.set(last_ingest.timestamp())

    mttr = await crud.mttr_seconds(session, days=_WINDOW_DAYS)
    MTTR_SECONDS_AVG.set(mttr if mttr is not None else 0)

    TOP_NOISY_ALERTS_EVENTS.clear()
    for alertname, event_count in await crud.top_noisy_alerts(session, days=_WINDOW_DAYS):
        TOP_NOISY_ALERTS_EVENTS.labels(alertname=alertname).set(event_count)

    AUDIT_LOG_ENTRIES_TOTAL.clear()
    for auth_result, count in (await crud.audit_result_counts(session)).items():
        AUDIT_LOG_ENTRIES_TOTAL.labels(auth_result=auth_result).set(count)

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
