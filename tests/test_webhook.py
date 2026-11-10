from __future__ import annotations

import pytest
from httpx import AsyncClient

from promhis.config import settings

pytestmark = pytest.mark.asyncio


def _alert(status: str, ends_at: str | None) -> dict:
    return {
        "status": status,
        "labels": {"alertname": "HighCPULoad", "severity": "critical", "node": "web-01"},
        "annotations": {"summary": "CPU above 90%"},
        "startsAt": "2026-01-01T00:00:00Z",
        "endsAt": ends_at,
        "generatorURL": "http://prom/graph",
        "fingerprint": "fp-1",
    }


async def test_webhook_rejects_missing_credentials(client: AsyncClient) -> None:
    response = await client.post("/api/v1/webhook", json={"alerts": [_alert("firing", None)]})
    assert response.status_code == 401


async def test_webhook_rejects_bad_credentials(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/webhook",
        json={"alerts": [_alert("firing", None)]},
        auth=("testadmin", "wrong"),
    )
    assert response.status_code == 401


async def test_webhook_ingest_builds_history(client: AsyncClient, authed_client: AsyncClient) -> None:
    firing = await client.post(
        "/api/v1/webhook",
        json={"receiver": "promhis", "alerts": [_alert("firing", None)]},
        auth=("testadmin", "testpass"),
    )
    assert firing.status_code == 200
    assert firing.json() == {"ingested": 1}

    resolved = await client.post(
        "/api/v1/webhook",
        json={"receiver": "promhis", "alerts": [_alert("resolved", "2026-01-01T00:10:00Z")]},
        auth=("testadmin", "testpass"),
    )
    assert resolved.status_code == 200

    detail = await authed_client.get("/api/v1/alerts/fp-1")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "resolved"
    assert len(body["events"]) == 2
    assert {e["status"] for e in body["events"]} == {"firing", "resolved"}


async def test_stats_reflect_ingested_alerts(client: AsyncClient, authed_client: AsyncClient) -> None:
    await client.post(
        "/api/v1/webhook",
        json={"receiver": "promhis", "alerts": [_alert("firing", None)]},
        auth=("testadmin", "testpass"),
    )
    stats = await authed_client.get("/api/v1/stats")
    assert stats.status_code == 200
    body = stats.json()
    assert body["total_alerts"] == 1
    assert body["firing"] == 1
    assert body["nodes"] == 1


async def test_webhook_rejects_malformed_payload(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/webhook",
        content=b"not json",
        headers={"content-type": "application/json"},
        auth=("testadmin", "testpass"),
    )
    assert response.status_code == 400


async def test_webhook_bearer_auth_mode(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "webhook_auth_mode", "bearer")
    monkeypatch.setattr(settings, "webhook_token", "supersecrettoken")

    rejected = await client.post(
        "/api/v1/webhook",
        json={"alerts": [_alert("firing", None)]},
        auth=("testadmin", "testpass"),  # Basic creds no longer valid in bearer mode
    )
    assert rejected.status_code == 401

    accepted = await client.post(
        "/api/v1/webhook",
        json={"alerts": [_alert("firing", None)]},
        headers={"Authorization": "Bearer supersecrettoken"},
    )
    assert accepted.status_code == 200


async def test_group_key_stored_and_filterable(client: AsyncClient, authed_client: AsyncClient) -> None:
    def grouped_alert(fingerprint: str) -> dict:
        return {
            "status": "firing",
            "labels": {"alertname": "RackDown", "severity": "critical", "node": f"node-{fingerprint}"},
            "annotations": {},
            "startsAt": "2026-01-01T00:00:00Z",
            "endsAt": None,
            "generatorURL": None,
            "fingerprint": fingerprint,
        }

    response = await client.post(
        "/api/v1/webhook",
        json={
            "receiver": "promhis",
            "groupKey": "{}:{alertname=\"RackDown\"}",
            "alerts": [grouped_alert("grp-1"), grouped_alert("grp-2")],
        },
        auth=("testadmin", "testpass"),
    )
    assert response.status_code == 200

    detail = await authed_client.get("/api/v1/alerts/grp-1")
    assert detail.status_code == 200
    assert detail.json()["group_key"] == '{}:{alertname="RackDown"}'

    grouped = await authed_client.get("/api/v1/alerts", params={"group": '{}:{alertname="RackDown"}'})
    assert grouped.status_code == 200
    assert grouped.json()["total"] == 2
