"""Database access layer: ingesting webhook payloads and querying history."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import cast

from sqlalchemy import case, delete, func
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from promhis.config import settings
from promhis.models import (
    Alert,
    AlertAnnotation,
    AlertEvent,
    ApiToken,
    AppSetting,
    AuditLogEntry,
    NotificationIntegration,
    User,
    utcnow,
)
from promhis.schemas import (
    AlertmanagerAlert,
    AlertmanagerWebhook,
    DailyCount,
    NodeSummary,
    SeverityCount,
    Stats,
)


def extract_node(labels: dict[str, str]) -> str | None:
    for key in settings.node_labels:
        value = labels.get(key)
        if value:
            return value
    return None


async def ingest_alert(
    session: AsyncSession, alert: AlertmanagerAlert, receiver: str | None, group_key: str | None = None
) -> AlertEvent:
    labels = alert.labels
    annotations = alert.annotations
    alertname = labels.get("alertname", "unknown")
    severity = labels.get("severity")
    node = extract_node(labels)

    event = AlertEvent(
        fingerprint=alert.fingerprint,
        alertname=alertname,
        status=alert.status,
        severity=severity,
        node=node,
        labels=labels,
        annotations=annotations,
        starts_at=alert.startsAt,
        ends_at=alert.endsAt,
        receiver=receiver,
        group_key=group_key,
    )
    session.add(event)

    current = await session.get(Alert, alert.fingerprint)
    now = utcnow()
    if current is None:
        current = Alert(
            fingerprint=alert.fingerprint,
            alertname=alertname,
            status=alert.status,
            severity=severity,
            node=node,
            labels=labels,
            annotations=annotations,
            starts_at=alert.startsAt,
            ends_at=alert.endsAt,
            generator_url=alert.generatorURL,
            receiver=receiver,
            group_key=group_key,
            first_seen=now,
            last_seen=now,
        )
    else:
        current.alertname = alertname
        current.status = alert.status
        current.severity = severity
        current.node = node
        current.labels = labels
        current.annotations = annotations
        current.ends_at = alert.endsAt
        current.generator_url = alert.generatorURL or current.generator_url
        current.receiver = receiver
        current.group_key = group_key or current.group_key
        current.last_seen = now
    session.add(current)
    return event


async def ingest_webhook(session: AsyncSession, payload: AlertmanagerWebhook) -> list[AlertEvent]:
    """Ingests every alert in the payload, returns the AlertEvent created for
    each — the webhook route uses these to dispatch notification channels.
    """
    events = [
        await ingest_alert(session, alert, payload.receiver, payload.groupKey) for alert in payload.alerts
    ]
    await session.commit()
    return events


async def group_siblings_count(session: AsyncSession, group_key: str, exclude_fingerprint: str) -> int:
    """How many other current alerts share this group_key — surfaced on the
    alert detail page as "N other alerts fired in this group."
    """
    query = (
        select(func.count())
        .select_from(Alert)
        .where(Alert.group_key == group_key, Alert.fingerprint != exclude_fingerprint)
    )
    result = await session.execute(query)
    return result.scalar_one()


ALERT_SORT_FIELDS = {
    "alertname": col(Alert.alertname),
    "severity": col(Alert.severity),
    "node": col(Alert.node),
    "status": col(Alert.status),
    "starts_at": col(Alert.starts_at),
    "last_seen": col(Alert.last_seen),
}


async def list_alerts(
    session: AsyncSession,
    *,
    status: str | None = None,
    severity: str | None = None,
    node: str | None = None,
    alertname: str | None = None,
    search: str | None = None,
    group: str | None = None,
    sort: str = "-last_seen",
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[Alert], int]:
    query = select(Alert)
    if status:
        query = query.where(Alert.status == status)
    if severity:
        query = query.where(Alert.severity == severity)
    if node:
        query = query.where(Alert.node == node)
    if alertname:
        query = query.where(Alert.alertname == alertname)
    if group:
        query = query.where(Alert.group_key == group)
    if search:
        like = f"%{search}%"
        query = query.where(col(Alert.alertname).ilike(like) | col(Alert.node).ilike(like))

    count_result = await session.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    descending = sort.startswith("-")
    field = ALERT_SORT_FIELDS.get(sort.lstrip("-"), ALERT_SORT_FIELDS["last_seen"])
    order = field.desc() if descending else field.asc()
    query = query.order_by(order).offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    items = list(result.scalars().all())
    return items, total


async def get_alert(session: AsyncSession, fingerprint: str) -> Alert | None:
    return await session.get(Alert, fingerprint)


async def set_alert_ack(session: AsyncSession, fingerprint: str, *, note: str, by: str) -> Alert | None:
    """Set or clear an alert's acknowledgment note. An empty/blank `note`
    clears it (all three ack_* fields reset to None) rather than requiring a
    separate "unacknowledge" action.
    """
    alert = await session.get(Alert, fingerprint)
    if alert is None:
        return None
    note = note.strip()
    if note:
        alert.ack_note = note
        alert.ack_by = by
        alert.ack_at = utcnow()
    else:
        alert.ack_note = None
        alert.ack_by = None
        alert.ack_at = None
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert


async def list_annotations(session: AsyncSession, fingerprint: str) -> list[AlertAnnotation]:
    """Incident notes for an alert, newest first — always readable regardless
    of license state (docs/licensing.md: existing data stays viewable past
    expiry, only *creating new* notes is gated). See `create_annotation`.
    """
    query = (
        select(AlertAnnotation)
        .where(AlertAnnotation.fingerprint == fingerprint)
        .order_by(col(AlertAnnotation.created_at).desc())
    )
    result = await session.execute(query)
    return list(result.scalars().all())


async def create_annotation(session: AsyncSession, *, fingerprint: str, author: str, body: str) -> AlertAnnotation:
    annotation = AlertAnnotation(fingerprint=fingerprint, author=author, body=body)
    session.add(annotation)
    await session.commit()
    await session.refresh(annotation)
    return annotation


async def delete_annotation(session: AsyncSession, annotation_id: int) -> bool:
    """Deletion is cleanup, not the licensed capability itself — unlike
    creation, it's never gated on `has_feature("annotations")` (see
    `ee/annotations.py`), same way revoking an API token is always free even
    though creating a *second* one isn't.
    """
    annotation = await session.get(AlertAnnotation, annotation_id)
    if annotation is None:
        return False
    await session.delete(annotation)
    await session.commit()
    return True


async def get_alert_events(session: AsyncSession, fingerprint: str) -> list[AlertEvent]:
    """Every event for this fingerprint — backs the JSON API's documented
    "full event history" contract (`GET /api/v1/alerts/{fingerprint}`,
    docs/api.md). Deliberately unbounded: that's the documented behavior for
    programmatic consumers. The HTML dashboard's ledger uses the paginated
    `get_alert_events_page` below instead, since a long-lived flapping alert
    can accumulate thousands of events and that page renders them.
    """
    query = select(AlertEvent).where(AlertEvent.fingerprint == fingerprint).order_by(col(AlertEvent.received_at).desc())
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_alert_events_page(
    session: AsyncSession, fingerprint: str, *, page: int = 1, page_size: int = 50
) -> tuple[list[AlertEvent], int]:
    """Paginated version of `get_alert_events`, for the dashboard's one-alert
    history ledger page rather than the JSON API.
    """
    query = select(AlertEvent).where(AlertEvent.fingerprint == fingerprint)
    count_result = await session.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()
    query = query.order_by(col(AlertEvent.received_at).desc()).offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    return list(result.scalars().all()), total


NODE_SORT_KEYS: dict[str, Callable[[NodeSummary], str | int | datetime]] = {
    "node": lambda s: s.node.lower(),
    "firing": lambda s: s.firing,
    "total": lambda s: s.total,
    "last_seen": lambda s: s.last_seen,
}


async def list_nodes(session: AsyncSession, *, sort: str = "-last_seen") -> list[NodeSummary]:
    # Aggregated in Python rather than SQL: node counts are small enough
    # that there's no real cost to it, and it keeps the aggregation logic
    # in one place alongside NodeSummary's other derived fields.
    result = await session.execute(select(Alert).where(col(Alert.node).is_not(None)))
    alerts = result.scalars().all()
    summaries: dict[str, NodeSummary] = {}
    for a in alerts:
        assert a.node is not None
        s = summaries.get(a.node)
        if s is None:
            s = NodeSummary(
                node=a.node,
                firing=0,
                resolved=0,
                total=0,
                last_seen=a.last_seen,
                last_alertname=a.alertname,
                last_severity=a.severity,
            )
            summaries[a.node] = s
        s.total += 1
        if a.status == "firing":
            s.firing += 1
        elif a.status == "resolved":
            s.resolved += 1
        # "silenced" (poll-path only) counts toward total but neither
        # bucket — NodeSummary stays a two-state summary deliberately (see
        # ROADMAP.md §7's scope note), this just avoids miscounting it as
        # resolved via an `else` that assumed only two statuses existed.
        if a.last_seen >= s.last_seen:
            s.last_seen = a.last_seen
            s.last_alertname = a.alertname
            s.last_severity = a.severity
    descending = sort.startswith("-")
    key = NODE_SORT_KEYS.get(sort.lstrip("-"), NODE_SORT_KEYS["last_seen"])
    return sorted(summaries.values(), key=key, reverse=descending)


async def list_node_names(session: AsyncSession) -> list[str]:
    result = await session.execute(
        select(Alert.node).where(col(Alert.node).is_not(None)).distinct().order_by(col(Alert.node))
    )
    return list(result.scalars().all())


async def node_alert_history(session: AsyncSession, node: str, *, limit: int = 500) -> list[AlertEvent]:
    query = (
        select(AlertEvent)
        .where(AlertEvent.node == node)
        .order_by(col(AlertEvent.received_at).desc())
        .limit(limit)
    )
    result = await session.execute(query)
    return list(result.scalars().all())


async def dashboard_stats(session: AsyncSession, *, days: int = 14) -> Stats:
    alerts = (await session.execute(select(Alert))).scalars().all()
    total = len(alerts)
    firing = sum(1 for a in alerts if a.status == "firing")
    # Computed explicitly, not as `total - firing` — a third status value
    # ("silenced", poll-path only) exists, so that subtraction would silently
    # miscount silenced alerts as resolved.
    resolved = sum(1 for a in alerts if a.status == "resolved")
    nodes = len({a.node for a in alerts if a.node})

    severity_counts: dict[str, int] = {}
    for a in alerts:
        key = a.severity or "none"
        severity_counts[key] = severity_counts.get(key, 0) + 1
    by_severity = [
        SeverityCount(severity=k, count=v) for k, v in sorted(severity_counts.items(), key=lambda kv: -kv[1])
    ]

    since = datetime.now(timezone.utc) - timedelta(days=days)
    events = (await session.execute(select(AlertEvent).where(AlertEvent.received_at >= since))).scalars().all()
    day_counts: dict[str, int] = {}
    for e in events:
        day = e.received_at.date().isoformat()
        day_counts[day] = day_counts.get(day, 0) + 1
    by_day = [DailyCount(day=k, count=v) for k, v in sorted(day_counts.items())]

    return Stats(
        total_alerts=total,
        firing=firing,
        resolved=resolved,
        nodes=nodes,
        by_severity=by_severity,
        by_day=by_day,
    )


async def prune_old_events(session: AsyncSession, *, retention_days: int) -> int:
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    result = await session.execute(delete(AlertEvent).where(col(AlertEvent.received_at) < cutoff))
    await session.commit()
    return cast(CursorResult, result).rowcount


async def record_audit_entry(
    session: AsyncSession,
    *,
    source_ip: str | None,
    user_agent: str | None,
    auth_mode: str,
    auth_result: str,
    status_code: int,
    alert_count: int | None = None,
    receiver: str | None = None,
    error_detail: str | None = None,
) -> None:
    entry = AuditLogEntry(
        source_ip=source_ip,
        user_agent=user_agent,
        auth_mode=auth_mode,
        auth_result=auth_result,
        status_code=status_code,
        alert_count=alert_count,
        receiver=receiver,
        error_detail=error_detail,
    )
    session.add(entry)
    await session.commit()


async def list_audit_log(
    session: AsyncSession,
    *,
    outcome: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[AuditLogEntry], int]:
    query = select(AuditLogEntry)
    if outcome:
        query = query.where(AuditLogEntry.auth_result == outcome)

    count_result = await session.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    query = query.order_by(col(AuditLogEntry.received_at).desc()).offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    return list(result.scalars().all()), total


async def audit_result_counts(session: AsyncSession) -> dict[str, int]:
    """All-time audit log row counts grouped by auth_result — unlike the
    Prometheus exporter's live request counters, this survives process
    restarts since it's read straight off the (pruned-but-persistent) table.
    """
    query = select(AuditLogEntry.auth_result, func.count()).group_by(AuditLogEntry.auth_result)
    result = await session.execute(query)
    return {row[0]: row[1] for row in result.all()}


async def prune_old_audit_entries(session: AsyncSession, *, retention_days: int) -> int:
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    result = await session.execute(delete(AuditLogEntry).where(col(AuditLogEntry.received_at) < cutoff))
    await session.commit()
    return cast(CursorResult, result).rowcount


async def last_successful_ingest(session: AsyncSession) -> datetime | None:
    """When the webhook endpoint last accepted a payload — the "is the
    pipeline even working" indicator on the overview, built directly on the
    audit log rather than a separate tracking mechanism.
    """
    query = (
        select(AuditLogEntry.received_at)
        .where(AuditLogEntry.auth_result == "success")
        .order_by(col(AuditLogEntry.received_at).desc())
        .limit(1)
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def flap_count(session: AsyncSession, fingerprint: str, *, window_hours: int = 1) -> int:
    """How many events this fingerprint has logged in the last `window_hours`
    — a cheap, honest proxy for "is this alert flapping," read straight off
    the existing AlertEvent history. No ingest-side changes needed.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    query = (
        select(func.count())
        .select_from(AlertEvent)
        .where(AlertEvent.fingerprint == fingerprint, AlertEvent.received_at >= since)
    )
    result = await session.execute(query)
    return result.scalar_one()


async def mttr_seconds(session: AsyncSession, *, days: int = 14) -> float | None:
    """Average time-to-resolution across every alert resolved in the last
    `days`, in seconds. None when nothing resolved in that window.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = select(AlertEvent).where(
        AlertEvent.status == "resolved",
        col(AlertEvent.ends_at).is_not(None),
        AlertEvent.received_at >= since,
    )
    events = (await session.execute(query)).scalars().all()
    durations = [(e.ends_at - e.starts_at).total_seconds() for e in events if e.ends_at]
    if not durations:
        return None
    return sum(durations) / len(durations)


async def top_noisy_alerts(session: AsyncSession, *, days: int = 14, limit: int = 10) -> list[tuple[str, int]]:
    """Most frequent alertnames by event count in the last `days` — an
    alert-fatigue cleanup aid (which rules are worth tuning or deleting).
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = (
        select(AlertEvent.alertname, func.count().label("event_count"))
        .where(AlertEvent.received_at >= since)
        .group_by(AlertEvent.alertname)
        .order_by(func.count().desc())
        .limit(limit)
    )
    result = await session.execute(query)
    return [(row[0], row[1]) for row in result.all()]


async def create_api_token(session: AsyncSession, *, name: str, token_hash: str) -> ApiToken:
    token = ApiToken(name=name, token_hash=token_hash)
    session.add(token)
    await session.commit()
    await session.refresh(token)
    return token


async def list_api_tokens(session: AsyncSession) -> list[ApiToken]:
    query = select(ApiToken).order_by(col(ApiToken.created_at).desc())
    result = await session.execute(query)
    return list(result.scalars().all())


async def count_active_api_tokens(session: AsyncSession) -> int:
    """One active (non-revoked) token is free (docs/licensing.md); creating
    beyond that requires the `service_tokens` feature.
    """
    query = select(func.count()).select_from(ApiToken).where(col(ApiToken.revoked).is_(False))
    result = await session.execute(query)
    return result.scalar_one()


async def revoke_api_token(session: AsyncSession, token_id: int) -> bool:
    token = await session.get(ApiToken, token_id)
    if token is None:
        return False
    token.revoked = True
    session.add(token)
    await session.commit()
    return True


async def verify_api_token(session: AsyncSession, token_hash: str) -> ApiToken | None:
    """Looks up a non-revoked token by its hash and bumps last_used_at.
    Returns None for an unknown or revoked token.
    """
    query = select(ApiToken).where(ApiToken.token_hash == token_hash, col(ApiToken.revoked).is_(False))
    result = await session.execute(query)
    token = result.scalar_one_or_none()
    if token is None:
        return None
    token.last_used_at = utcnow()
    session.add(token)
    await session.commit()
    return token


async def digest_events(session: AsyncSession, *, since: datetime) -> list[AlertEvent]:
    """Every event received since `since` — the raw material for the daily
    digest email. Grouping/formatting happens in digest.py, not here.
    """
    query = select(AlertEvent).where(AlertEvent.received_at >= since).order_by(col(AlertEvent.received_at).desc())
    result = await session.execute(query)
    return list(result.scalars().all())


async def event_count_in_range(session: AsyncSession, *, since: datetime | None) -> int:
    """Total event count for the Statistics page's "N events in range"
    header — a plain `COUNT(*)`, not `len()` on a fully-fetched list.
    """
    query = select(func.count()).select_from(AlertEvent)
    if since is not None:
        query = query.where(AlertEvent.received_at >= since)
    result = await session.execute(query)
    return result.scalar_one()


async def recent_events_in_range(
    session: AsyncSession, *, since: datetime | None, limit: int = 200
) -> list[AlertEvent]:
    """Newest `limit` events in range — backs the Statistics page's raw
    event browser. A `LIMIT`, not a Python-side slice of everything in
    range, so "All time" doesn't mean fetching the whole table to look at
    the first 200 rows of it.
    """
    query = select(AlertEvent).order_by(col(AlertEvent.received_at).desc()).limit(limit)
    if since is not None:
        query = query.where(AlertEvent.received_at >= since)
    result = await session.execute(query)
    return list(result.scalars().all())


async def daily_status_counts(session: AsyncSession, *, since: datetime | None) -> list[dict]:
    """[{day, firing, resolved}, ...] sorted by day — aggregated in SQL
    (one row per day, not one row per event) so "All time" on a long-lived
    install stays a small result set regardless of total event volume.
    """
    day = func.date(AlertEvent.received_at)
    firing = func.sum(case((col(AlertEvent.status) == "firing", 1), else_=0))
    resolved = func.sum(case((col(AlertEvent.status) == "resolved", 1), else_=0))
    query = select(day.label("day"), firing.label("firing"), resolved.label("resolved")).group_by(day).order_by(day)
    if since is not None:
        query = query.where(AlertEvent.received_at >= since)
    result = await session.execute(query)
    return [{"day": str(row.day), "firing": int(row.firing), "resolved": int(row.resolved)} for row in result.all()]


def _severity_case():
    # Mirrors the synonym mapping the dashboard uses elsewhere for a
    # severity label (critical/page/disaster -> critical, etc.) — done here
    # in SQL so grouping by normalized severity doesn't require fetching
    # every raw event into Python first. `lower(NULL)` is NULL in both
    # SQLite and Postgres, so an absent severity falls through to "none"
    # exactly like the equivalent Python helper does for `None`.
    return case(
        (func.lower(AlertEvent.severity).in_(["critical", "page", "disaster"]), "critical"),
        (func.lower(AlertEvent.severity).in_(["warning", "warn", "degraded"]), "warning"),
        (func.lower(AlertEvent.severity).in_(["info", "informational", "notice"]), "info"),
        else_="none",
    )


async def severity_by_day(session: AsyncSession, *, since: datetime | None) -> list[dict]:
    """[{day, critical, warning, info, none}, ...] sorted by day — same
    SQL-aggregation reasoning as `daily_status_counts`.
    """
    day = func.date(AlertEvent.received_at)
    sev = _severity_case()
    query = select(day.label("day"), sev.label("sev"), func.count().label("n")).group_by(day, sev).order_by(day)
    if since is not None:
        query = query.where(AlertEvent.received_at >= since)
    result = await session.execute(query)
    buckets: dict[str, dict[str, int]] = {}
    for row in result.all():
        bucket = buckets.setdefault(str(row.day), {"critical": 0, "warning": 0, "info": 0, "none": 0})
        bucket[row.sev] = row.n
    return [{"day": day_key, **counts} for day_key, counts in sorted(buckets.items())]


async def top_nodes_by_volume(
    session: AsyncSession, *, since: datetime | None, limit: int = 10
) -> list[tuple[str, int]]:
    """Most frequent nodes by event count in range — the node-equivalent of
    `top_noisy_alerts`, same SQL `GROUP BY`/`LIMIT` shape.
    """
    query = (
        select(AlertEvent.node, func.count().label("event_count"))
        .where(col(AlertEvent.node).is_not(None))
        .group_by(AlertEvent.node)
        .order_by(func.count().desc())
        .limit(limit)
    )
    if since is not None:
        query = query.where(AlertEvent.received_at >= since)
    result = await session.execute(query)
    return [(row[0], row[1]) for row in result.all()]


async def resolved_events_for_mttr_trend(session: AsyncSession, *, since: datetime | None) -> list[AlertEvent]:
    """Resolved-with-duration events in range, SQL-filtered down before
    reaching Python — `insights.mttr_weekly_trend`'s ISO-week bucketing
    stays a pure function over this (much smaller) list rather than every
    raw event, since ISO-week grouping isn't expressible identically across
    SQLite and Postgres without dialect-specific SQL.
    """
    query = select(AlertEvent).where(AlertEvent.status == "resolved", col(AlertEvent.ends_at).is_not(None))
    if since is not None:
        query = query.where(AlertEvent.received_at >= since)
    result = await session.execute(query)
    return list(result.scalars().all())


async def list_integrations(session: AsyncSession) -> list[NotificationIntegration]:
    query = select(NotificationIntegration).order_by(col(NotificationIntegration.created_at).desc())
    result = await session.execute(query)
    return list(result.scalars().all())


async def list_enabled_integrations(session: AsyncSession) -> list[NotificationIntegration]:
    query = select(NotificationIntegration).where(col(NotificationIntegration.enabled).is_(True))
    result = await session.execute(query)
    return list(result.scalars().all())


async def create_integration(
    session: AsyncSession, *, channel_type: str, config: dict
) -> NotificationIntegration:
    integration = NotificationIntegration(channel_type=channel_type, config=config)
    session.add(integration)
    await session.commit()
    await session.refresh(integration)
    return integration


async def distinct_label_keys(session: AsyncSession, *, sample: int = 1000) -> list[str]:
    """Distinct label keys seen across the most recent `sample` alert events —
    powers the routing-rules label autocomplete on the Integrations page.
    JSON keys aren't queryable generically across SQLite/Postgres, so this
    reads labels Python-side rather than via SQL.
    """
    query = select(AlertEvent.labels).order_by(col(AlertEvent.received_at).desc()).limit(sample)
    result = await session.execute(query)
    keys: set[str] = set()
    for labels in result.scalars().all():
        keys.update(labels.keys())
    return sorted(keys)


async def get_integration(session: AsyncSession, integration_id: int) -> NotificationIntegration | None:
    return await session.get(NotificationIntegration, integration_id)


async def update_integration(
    session: AsyncSession,
    integration_id: int,
    *,
    config_updates: dict | None = None,
    enabled: bool | None = None,
    routing_rules: list[dict] | None = None,
) -> NotificationIntegration | None:
    """`config_updates` is merged into the existing config (not replaced) so
    updating one field doesn't require resending every field — in
    particular, leaving a secret field out of `config_updates` keeps the
    existing secret rather than clearing it.

    `routing_rules`, unlike `config_updates`, *replaces* the existing list
    outright rather than merging — the edit form always submits its whole
    rule set, so `None` means "don't touch routing rules" and `[]` means
    "clear them all," both distinguishable from a real rule list.
    """
    integration = await session.get(NotificationIntegration, integration_id)
    if integration is None:
        return None
    if config_updates:
        integration.config = {**integration.config, **config_updates}
    if enabled is not None:
        integration.enabled = enabled
    if routing_rules is not None:
        integration.routing_rules = routing_rules
    integration.updated_at = utcnow()
    session.add(integration)
    await session.commit()
    await session.refresh(integration)
    return integration


async def delete_integration(session: AsyncSession, integration_id: int) -> bool:
    integration = await session.get(NotificationIntegration, integration_id)
    if integration is None:
        return False
    await session.delete(integration)
    await session.commit()
    return True


async def get_app_setting(session: AsyncSession, key: str) -> str | None:
    setting = await session.get(AppSetting, key)
    return setting.value if setting else None


async def set_app_setting(session: AsyncSession, key: str, value: str | None) -> None:
    setting = await session.get(AppSetting, key)
    if setting is None:
        setting = AppSetting(key=key, value=value)
    else:
        setting.value = value
        setting.updated_at = utcnow()
    session.add(setting)
    await session.commit()


# ---------------------------------------------------------------- users (§21)


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    query = select(User).where(User.username == username)
    result = await session.execute(query)
    return result.scalars().first()


async def count_users(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(User))
    return result.scalar_one()


async def list_users(session: AsyncSession) -> list[User]:
    query = select(User).order_by(col(User.created_at).asc())
    result = await session.execute(query)
    return list(result.scalars().all())


async def create_user(session: AsyncSession, *, username: str, password_hash: str) -> User:
    user = User(username=username, password_hash=password_hash)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def delete_user(session: AsyncSession, user_id: int) -> bool:
    user = await session.get(User, user_id)
    if user is None or user.is_bootstrap:
        # The bootstrap admin can't be deleted through this path — it's
        # mirrored from env vars at every startup and would just come back,
        # and deleting it would mean the instance's documented env-var login
        # silently stops working.
        return False
    await session.delete(user)
    await session.commit()
    return True


async def record_login(session: AsyncSession, user: User) -> None:
    user.last_login_at = utcnow()
    session.add(user)
    await session.commit()


async def sync_bootstrap_admin(session: AsyncSession, *, username: str, password_hash: str) -> User:
    """Keeps exactly one `is_bootstrap=True` row matching the current
    `PROMHIS_ADMIN_USER`/`PROMHIS_ADMIN_PASSWORD`, run once at startup
    (`main.py`'s lifespan). A username change renames the existing bootstrap
    row rather than creating a second one, so the admin-user count stays
    stable across a `PROMHIS_ADMIN_USER` rename; a password change always
    re-hashes into it, so rotating the password via env var + restart keeps
    working exactly as documented today.
    """
    query = select(User).where(col(User.is_bootstrap).is_(True))
    result = await session.execute(query)
    bootstrap = result.scalars().first()
    if bootstrap is None:
        # A non-bootstrap row might already occupy this username (shouldn't
        # normally happen without an `rbac` license enabling multi-admin,
        # but handled cleanly rather than crashing on a unique-constraint
        # violation).
        existing = await get_user_by_username(session, username)
        if existing is not None:
            existing.is_bootstrap = True
            existing.password_hash = password_hash
            bootstrap = existing
        else:
            bootstrap = User(username=username, password_hash=password_hash, is_bootstrap=True)
    else:
        bootstrap.username = username
        bootstrap.password_hash = password_hash
    session.add(bootstrap)
    await session.commit()
    await session.refresh(bootstrap)
    return bootstrap
