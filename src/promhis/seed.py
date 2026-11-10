"""Demo data: synthesize a realistic alert history for trying out the dashboard
without wiring up a real Alertmanager first.
"""

from __future__ import annotations

import asyncio
import random
import uuid
from datetime import datetime, timedelta, timezone

from promhis import crud
from promhis.db import async_session_factory, init_db
from promhis.models import Alert
from promhis.schemas import AlertmanagerAlert

NODES = ["web-01", "web-02", "db-primary", "db-replica-1", "cache-01", "worker-03"]
ALERTS = [
    ("HighCPULoad", "warning", "CPU load above 85% for 10m"),
    ("DiskSpaceLow", "critical", "Disk usage above 90%"),
    ("InstanceDown", "critical", "Target has been unreachable for 5m"),
    ("HighMemoryUsage", "warning", "Memory usage above 90%"),
    ("TooManyRestarts", "warning", "Container restarted more than 3 times in 15m"),
    ("CertificateExpiringSoon", "info", "TLS certificate expires in under 14 days"),
    ("HighRequestLatency", "warning", "p99 latency above 500ms"),
]


def _random_alert(now: datetime) -> AlertmanagerAlert:
    node = random.choice(NODES)
    name, severity, summary = random.choice(ALERTS)
    starts_at = now - timedelta(hours=random.uniform(0, 24 * 90))
    resolved = random.random() < 0.7
    ends_at = starts_at + timedelta(minutes=random.uniform(2, 240)) if resolved else None
    return AlertmanagerAlert(
        status="resolved" if resolved else "firing",
        labels={"alertname": name, "severity": severity, "node": node, "job": "node-exporter"},
        annotations={"summary": summary},
        startsAt=starts_at,
        endsAt=ends_at,
        generatorURL=f"http://prometheus.example.internal/graph?g0.expr={name}",
        fingerprint=uuid.uuid4().hex,
    )


async def seed(count: int = 800) -> int:
    await init_db()
    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        for _ in range(count):
            alert = _random_alert(now)
            event = await crud.ingest_alert(session, alert, receiver="demo-seed")
            # The Stats page's day-bucketed charts (volume/severity over
            # time) group by `received_at` (when Promhis ingested it), not
            # `starts_at` (the alert's own synthetic start time) — left at
            # its default of "now" from `ingest_alert`, every seeded row
            # would land on today's date regardless of how far back
            # `starts_at` is backdated. Overriding it here spreads the
            # history across the same synthetic window instead.
            event.received_at = alert.startsAt
            current = await session.get(Alert, alert.fingerprint)
            if current is not None:
                current.first_seen = alert.startsAt
                current.last_seen = alert.endsAt or alert.startsAt
        await session.commit()
    return count


def main() -> None:
    created = asyncio.run(seed())
    print(f"Seeded {created} demo alert events.")


if __name__ == "__main__":
    main()
