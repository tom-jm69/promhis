"""Pure aggregation functions for the Statistics page.

`daily_status_counts`, `severity_by_day`, and `top_nodes_by_volume` are SQL
`GROUP BY` aggregations in `crud.py` now, not pure functions here — doing
that bucketing in the database means the "All time" range returns one row
per day/node instead of one row per event, so it stays fast and
low-memory regardless of how much history has accumulated. ISO-week
grouping for MTTR isn't expressible identically across SQLite and Postgres
without dialect-specific SQL, so `mttr_weekly_trend` stays a pure function
here — `crud.resolved_events_for_mttr_trend` narrows the query to
resolved-with-duration events first, so this still only crunches a small
list, not every raw event ever ingested.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from promhis.models import AlertEvent


def mttr_weekly_trend(events: list[AlertEvent]) -> list[dict]:
    """[{week, avg_seconds}, ...] sorted by week — turns a single current-MTTR
    number into a trend. `week` is the ISO year-week of the resolution event.
    """
    buckets: dict[str, list[float]] = defaultdict(list)
    for e in events:
        if e.status != "resolved" or e.ends_at is None:
            continue
        iso = e.received_at.isocalendar()
        week_label = f"{iso.year}-W{iso.week:02d}"
        buckets[week_label].append((e.ends_at - e.starts_at).total_seconds())
    return [
        {"week": week, "avg_seconds": sum(durations) / len(durations)}
        for week, durations in sorted(buckets.items())
    ]


RANGE_PRESETS: dict[str, timedelta | None] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
    "all": None,
}


def resolve_range(range_key: str) -> timedelta | None:
    return RANGE_PRESETS.get(range_key, RANGE_PRESETS["7d"])
