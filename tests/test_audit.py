from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


def _alert() -> dict:
    return {
        "status": "firing",
        "labels": {"alertname": "HighCPULoad", "severity": "critical", "node": "web-01"},
        "annotations": {},
        "startsAt": "2026-01-01T00:00:00Z",
        "endsAt": None,
        "generatorURL": None,
        "fingerprint": "audit-fp-1",
    }


async def test_audit_log_requires_login(client: AsyncClient) -> None:
    response = await client.get("/api/v1/audit-log")
    assert response.status_code == 401


async def test_audit_log_records_every_outcome(client: AsyncClient, authed_client: AsyncClient) -> None:
    await client.post("/api/v1/webhook", json={"alerts": [_alert()]})  # missing creds
    await client.post(
        "/api/v1/webhook", json={"alerts": [_alert()]}, auth=("testadmin", "wrong")
    )  # bad creds
    await client.post(
        "/api/v1/webhook", json={"receiver": "promhis", "alerts": [_alert()]}, auth=("testadmin", "testpass")
    )  # success

    log = await authed_client.get("/api/v1/audit-log")
    assert log.status_code == 200
    body = log.json()
    assert body["total"] >= 3
    outcomes = {e["auth_result"] for e in body["items"]}
    assert "missing" in outcomes
    assert "failure" in outcomes
    assert "success" in outcomes

    success_entry = next(e for e in body["items"] if e["auth_result"] == "success")
    assert success_entry["alert_count"] == 1
    assert success_entry["status_code"] == 200
    assert success_entry["source_ip"] is not None


async def test_audit_log_filters_by_outcome(client: AsyncClient, authed_client: AsyncClient) -> None:
    await client.post("/api/v1/webhook", json={"alerts": [_alert()]})  # missing creds

    log = await authed_client.get("/api/v1/audit-log", params={"outcome": "missing"})
    assert log.status_code == 200
    body = log.json()
    assert all(e["auth_result"] == "missing" for e in body["items"])


async def test_audit_log_page_renders(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/audit-log")
    assert response.status_code == 200
