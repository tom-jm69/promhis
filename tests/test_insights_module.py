"""Pure-function tests for insights.py. `daily_status_counts`, `severity_by_day`,
and `top_nodes_by_volume` moved to SQL-aggregated `crud.py` functions (see
tests/test_insights.py for their DB-backed coverage) — only `mttr_weekly_trend`
and `resolve_range` are still pure functions over a plain list.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from promhis import insights
from promhis.models import AlertEvent


def _event(
    status: str,
    *,
    severity: str | None = "critical",
    node: str | None = "web-01",
    received_at: datetime,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> AlertEvent:
    return AlertEvent(
        fingerprint="fp",
        alertname="X",
        status=status,
        severity=severity,
        node=node,
        labels={},
        annotations={},
        starts_at=starts_at or received_at,
        ends_at=ends_at,
        received_at=received_at,
    )


def test_mttr_weekly_trend_only_counts_resolved_with_ends_at() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    resolved = _event(
        "resolved",
        received_at=now,
        starts_at=now - timedelta(minutes=10),
        ends_at=now,
    )
    firing = _event("firing", received_at=now)  # no ends_at — must be excluded
    result = insights.mttr_weekly_trend([resolved, firing])
    assert len(result) == 1
    assert result[0]["avg_seconds"] == 600.0


def test_resolve_range_known_and_unknown_keys() -> None:
    assert insights.resolve_range("24h") == timedelta(hours=24)
    assert insights.resolve_range("all") is None
    assert insights.resolve_range("bogus") == timedelta(days=7)  # falls back to the 7d default
