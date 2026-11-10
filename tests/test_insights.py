from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from promhis import crud
from promhis.db import async_session_factory
from promhis.models import AlertEvent
from promhis.schemas import AlertmanagerAlert

pytestmark = pytest.mark.asyncio


def _raw_event(
    fingerprint: str,
    status: str,
    *,
    severity: str | None = "critical",
    node: str | None = "web-01",
    received_at: datetime,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> AlertEvent:
    # Inserted directly (not via crud.ingest_alert) so `received_at` can be
    # backdated across days/weeks — ingest always stamps "now".
    return AlertEvent(
        fingerprint=fingerprint,
        alertname="SqlAggTest",
        status=status,
        severity=severity,
        node=node,
        labels={},
        annotations={},
        starts_at=starts_at or received_at,
        ends_at=ends_at,
        received_at=received_at,
    )


def _alert(fingerprint: str, status: str = "firing", ends_at: str | None = None) -> dict:
    return {
        "status": status,
        "labels": {"alertname": "HighCPULoad", "severity": "critical", "node": "web-01"},
        "annotations": {},
        "startsAt": "2026-01-01T00:00:00Z",
        "endsAt": ends_at,
        "generatorURL": None,
        "fingerprint": fingerprint,
    }


async def test_csv_export_contains_ingested_alert(client: AsyncClient, authed_client: AsyncClient) -> None:
    await client.post(
        "/api/v1/webhook",
        json={"receiver": "promhis", "alerts": [_alert("csv-fp-1")]},
        auth=("testadmin", "testpass"),
    )

    response = await authed_client.get("/api/v1/alerts/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")

    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0] == [
        "fingerprint",
        "alertname",
        "status",
        "severity",
        "node",
        "starts_at",
        "ends_at",
        "receiver",
        "group_key",
        "first_seen",
        "last_seen",
    ]
    fingerprints = [row[0] for row in rows[1:]]
    assert "csv-fp-1" in fingerprints


async def test_csv_export_respects_filters(client: AsyncClient, authed_client: AsyncClient) -> None:
    await client.post(
        "/api/v1/webhook",
        json={"receiver": "promhis", "alerts": [_alert("csv-fp-2", status="resolved", ends_at="2026-01-01T00:10:00Z")]},
        auth=("testadmin", "testpass"),
    )

    response = await authed_client.get("/api/v1/alerts/export.csv", params={"status": "firing"})
    rows = list(csv.reader(io.StringIO(response.text)))
    fingerprints = [row[0] for row in rows[1:]]
    assert "csv-fp-2" not in fingerprints


async def test_overview_page_renders_with_seeded_data(client: AsyncClient, authed_client: AsyncClient) -> None:
    # Regression test for a real bug caught in a running container: an
    # invalid col(func.count()) call crashed GET / whenever top_noisy_alerts
    # was reached with a real query. The existing minimal-data smoke test
    # didn't reach that code path meaningfully; this one does.
    await client.post(
        "/api/v1/webhook",
        json={
            "receiver": "promhis",
            "alerts": [_alert("mttr-fp-1", status="resolved", ends_at="2026-01-01T00:05:00Z")],
        },
        auth=("testadmin", "testpass"),
    )
    response = await authed_client.get("/")
    assert response.status_code == 200
    assert "Top noisy alerts" in response.text
    assert "Mean time to resolution" in response.text


async def test_alert_detail_shows_flapping_badge_past_threshold(
    client: AsyncClient, authed_client: AsyncClient
) -> None:
    for i in range(4):
        await client.post(
            "/api/v1/webhook",
            json={"receiver": "promhis", "alerts": [_alert("flap-fp-1", status="firing" if i % 2 == 0 else "resolved")]},
            auth=("testadmin", "testpass"),
        )

    response = await authed_client.get("/alerts/flap-fp-1")
    assert response.status_code == 200
    assert "flapping" in response.text


async def test_silenced_status_not_miscounted_as_resolved(client: AsyncClient, authed_client: AsyncClient) -> None:
    async with async_session_factory() as session:
        await crud.ingest_alert(
            session,
            AlertmanagerAlert(
                status="silenced",
                labels={"alertname": "Silenced", "severity": "warning", "node": "web-02"},
                annotations={},
                startsAt="2026-01-01T00:00:00Z",
                endsAt=None,
                generatorURL=None,
                fingerprint="silenced-fp-1",
            ),
            receiver="alertmanager-poll",
        )
        await session.commit()

    stats = await authed_client.get("/api/v1/stats")
    body = stats.json()
    assert body["firing"] == 0
    assert body["resolved"] == 0  # must not be miscounted via a `total - firing` complement

    alert = await authed_client.get("/api/v1/alerts/silenced-fp-1")
    assert alert.json()["status"] == "silenced"

    page = await authed_client.get("/alerts/silenced-fp-1")
    assert page.status_code == 200
    assert "state-silenced" in page.text


async def test_alert_acknowledgment_set_and_clear(client: AsyncClient, authed_client: AsyncClient) -> None:
    await client.post(
        "/api/v1/webhook",
        json={"receiver": "promhis", "alerts": [_alert("ack-fp-1")]},
        auth=("testadmin", "testpass"),
    )

    ack = await authed_client.post(
        "/alerts/ack-fp-1/ack", data={"note": "Investigating, looks like a noisy neighbor VM."}
    )
    assert ack.status_code == 303

    detail = await authed_client.get("/api/v1/alerts/ack-fp-1")
    body = detail.json()
    assert body["ack_note"] == "Investigating, looks like a noisy neighbor VM."
    assert body["ack_by"] == "testadmin"
    assert body["ack_at"] is not None

    page = await authed_client.get("/alerts/ack-fp-1")
    assert "Investigating, looks like a noisy neighbor VM." in page.text

    clear = await authed_client.post("/alerts/ack-fp-1/ack", data={"note": ""})
    assert clear.status_code == 303
    cleared = await authed_client.get("/api/v1/alerts/ack-fp-1")
    assert cleared.json()["ack_note"] is None


async def test_ack_unknown_fingerprint_404s(authed_client: AsyncClient) -> None:
    response = await authed_client.post("/alerts/does-not-exist/ack", data={"note": "x"})
    assert response.status_code == 404


async def test_stats_page_renders_with_default_range(client: AsyncClient, authed_client: AsyncClient) -> None:
    await client.post(
        "/api/v1/webhook",
        json={"receiver": "promhis", "alerts": [_alert("stats-fp-1", status="resolved", ends_at="2026-01-01T00:10:00Z")]},
        auth=("testadmin", "testpass"),
    )
    response = await authed_client.get("/stats")
    assert response.status_code == 200
    assert "Statistics" in response.text
    assert "Firing vs. resolved" in response.text
    assert "Top nodes by volume" in response.text


async def test_stats_page_respects_range_param(client: AsyncClient, authed_client: AsyncClient) -> None:
    response = await authed_client.get("/stats", params={"range": "30d"})
    assert response.status_code == 200

    bogus = await authed_client.get("/stats", params={"range": "not-a-real-range"})
    assert bogus.status_code == 200  # falls back to the 7d default rather than erroring


async def test_stats_page_requires_login(client: AsyncClient) -> None:
    response = await client.get("/stats", follow_redirects=False)
    assert response.status_code == 303


async def test_daily_status_counts_splits_and_sorts_in_sql(client: AsyncClient) -> None:
    d1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    d2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    async with async_session_factory() as session:
        session.add(_raw_event("sql-daily-1", "firing", received_at=d1))
        session.add(_raw_event("sql-daily-2", "firing", received_at=d1))
        session.add(_raw_event("sql-daily-3", "resolved", received_at=d1))
        session.add(_raw_event("sql-daily-4", "firing", received_at=d2))
        await session.commit()

        result = await crud.daily_status_counts(session, since=d1)
    by_day = {row["day"]: row for row in result}
    assert by_day["2026-01-01"] == {"day": "2026-01-01", "firing": 2, "resolved": 1}
    assert by_day["2026-01-02"]["firing"] == 1
    assert [row["day"] for row in result] == sorted(by_day.keys())


async def test_severity_by_day_normalizes_synonyms_in_sql(client: AsyncClient) -> None:
    day = datetime(2026, 2, 1, tzinfo=timezone.utc)
    async with async_session_factory() as session:
        session.add(_raw_event("sql-sev-1", "firing", severity="critical", received_at=day))
        session.add(_raw_event("sql-sev-2", "firing", severity="warn", received_at=day))  # -> warning
        session.add(_raw_event("sql-sev-3", "firing", severity=None, received_at=day))  # -> none
        await session.commit()

        result = await crud.severity_by_day(session, since=day)
    row = next(r for r in result if r["day"] == "2026-02-01")
    assert row["critical"] == 1
    assert row["warning"] == 1
    assert row["none"] == 1
    assert row["info"] == 0


async def test_top_nodes_by_volume_ranks_and_skips_null_node(client: AsyncClient) -> None:
    now = datetime(2026, 3, 1, tzinfo=timezone.utc)
    async with async_session_factory() as session:
        for i in range(3):
            session.add(_raw_event(f"sql-node-noisy-{i}", "firing", node="noisy", received_at=now))
        session.add(_raw_event("sql-node-quiet-1", "firing", node="quiet", received_at=now))
        session.add(_raw_event("sql-node-none-1", "firing", node=None, received_at=now))
        await session.commit()

        result = await crud.top_nodes_by_volume(session, since=now, limit=1)
    assert result == [("noisy", 3)]


async def test_recent_events_in_range_is_newest_first_and_bounded(client: AsyncClient) -> None:
    base = datetime(2026, 4, 1, tzinfo=timezone.utc)
    async with async_session_factory() as session:
        for i in range(5):
            session.add(_raw_event(f"sql-recent-{i}", "firing", received_at=base.replace(hour=i)))
        await session.commit()

        recent = await crud.recent_events_in_range(session, since=base, limit=2)
        total = await crud.event_count_in_range(session, since=base)
    assert total == 5
    assert len(recent) == 2
    # Newest first — hour=4 then hour=3 — not a slice of the oldest rows.
    assert [e.fingerprint for e in recent] == ["sql-recent-4", "sql-recent-3"]


async def test_get_alert_events_page_paginates_in_sql(client: AsyncClient) -> None:
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    async with async_session_factory() as session:
        for i in range(3):
            session.add(_raw_event("ledger-crud-fp-1", "firing", received_at=base.replace(hour=i)))
        await session.commit()

        page1, total = await crud.get_alert_events_page(session, "ledger-crud-fp-1", page=1, page_size=2)
        page2, _ = await crud.get_alert_events_page(session, "ledger-crud-fp-1", page=2, page_size=2)
    assert total == 3
    assert len(page1) == 2
    assert len(page2) == 1
    # Newest first, no overlap between pages.
    assert {e.id for e in page1}.isdisjoint({e.id for e in page2})


async def test_alert_ledger_via_htmx_returns_fragment_without_pagination_below_page_size(
    client: AsyncClient, authed_client: AsyncClient
) -> None:
    # crud.get_alert (checked by the route before it even looks at events)
    # needs a current-state Alert row, not just AlertEvent history rows —
    # ingest once for real, then backdate extra raw events onto it.
    await client.post(
        "/api/v1/webhook",
        json={"receiver": "promhis", "alerts": [_alert("ledger-fp-small")]},
        auth=("testadmin", "testpass"),
    )
    base = datetime(2026, 5, 2, tzinfo=timezone.utc)
    async with async_session_factory() as session:
        for i in range(3):
            session.add(_raw_event("ledger-fp-small", "firing", received_at=base.replace(hour=i)))
        await session.commit()

    fragment = await authed_client.get(
        "/alerts/ledger-fp-small", params={"page": 1}, headers={"HX-Request": "true"}
    )
    assert fragment.status_code == 200
    assert 'id="ledger-panel"' in fragment.text
    assert "<nav" not in fragment.text
    assert "page-btn" not in fragment.text  # 3 events, page_size 50 — no pagination needed


async def test_alert_ledger_shows_pagination_past_page_size(
    client: AsyncClient, authed_client: AsyncClient
) -> None:
    await client.post(
        "/api/v1/webhook",
        json={"receiver": "promhis", "alerts": [_alert("ledger-fp-big")]},
        auth=("testadmin", "testpass"),
    )
    base = datetime(2026, 5, 3, tzinfo=timezone.utc)
    async with async_session_factory() as session:
        for i in range(54):
            session.add(_raw_event("ledger-fp-big", "firing", received_at=base.replace(microsecond=i)))
        await session.commit()

    page1 = await authed_client.get("/alerts/ledger-fp-big")
    assert page1.status_code == 200
    assert "55 events" in page1.text  # 54 backdated + 1 from the real ingest
    assert 'disabled">‹ Prev' in page1.text  # first page, Prev disabled
    assert "Next ›</a>" in page1.text  # Next is a live link, 5 events remain

    page2 = await authed_client.get(
        "/alerts/ledger-fp-big", params={"page": 2}, headers={"HX-Request": "true"}
    )
    assert page2.status_code == 200
    assert 'disabled">Next ›' in page2.text  # second (last) page, Next disabled
