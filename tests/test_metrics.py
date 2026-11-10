from __future__ import annotations

import pytest
from httpx import AsyncClient

from promhis.config import settings

pytestmark = pytest.mark.asyncio


def _alert(status: str) -> dict:
    return {
        "status": status,
        "labels": {"alertname": "HighCPULoad", "severity": "critical", "node": "web-01"},
        "annotations": {},
        "startsAt": "2026-01-01T00:00:00Z",
        "endsAt": None,
        "generatorURL": None,
        "fingerprint": "metrics-fp-1",
    }


async def test_metrics_endpoint_exposes_prometheus_format(client: AsyncClient) -> None:
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "promhis_alerts_by_status" in response.text


async def test_metrics_reflect_ingested_alerts(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/webhook",
        json={"receiver": "promhis", "alerts": [_alert("firing")]},
        auth=("testadmin", "testpass"),
    )
    response = await client.get("/metrics")
    body = response.text
    assert 'promhis_alerts_by_status{status="firing"} 1.0' in body
    assert 'promhis_webhook_requests_total{auth_result="success",status_code="200"}' in body
    assert "promhis_alerts_ingested_total" in body


async def test_metrics_audit_log_counts_and_noisy_alerts(client: AsyncClient) -> None:
    await client.post("/api/v1/webhook", json={"alerts": [_alert("firing")]})  # unauthenticated -> rejected
    await client.post(
        "/api/v1/webhook",
        json={"receiver": "promhis", "alerts": [_alert("firing")]},
        auth=("testadmin", "testpass"),
    )
    response = await client.get("/metrics")
    body = response.text
    assert 'promhis_audit_log_entries_total{auth_result="missing"} 1.0' in body
    assert 'promhis_audit_log_entries_total{auth_result="success"} 1.0' in body
    assert 'promhis_top_noisy_alerts_events{alertname="HighCPULoad"} 1.0' in body
    assert "promhis_mttr_seconds_avg" in body


async def test_metrics_notification_sends_total_on_failed_channel(
    client: AsyncClient, authed_client: AsyncClient
) -> None:
    created = await authed_client.post(
        "/integrations",
        data={"channel_type": "slack", "cfg_slack_webhook_url": "http://127.0.0.1:1/unreachable"},
    )
    assert created.status_code == 303

    await client.post(
        "/api/v1/webhook",
        json={"receiver": "promhis", "alerts": [_alert("firing")]},
        auth=("testadmin", "testpass"),
    )

    response = await client.get("/metrics")
    assert 'promhis_notification_sends_total{channel="slack",result="failure"}' in response.text


async def test_metrics_open_by_default(client: AsyncClient) -> None:
    response = await client.get("/metrics")
    assert response.status_code == 200


def _set_env_locked(monkeypatch: pytest.MonkeyPatch, **fields: object) -> None:
    """Simulates a real env-var-configured deployment: both the actual
    process environment (what `metrics_setting_env_locked` checks) and the
    already-parsed `Settings` object (what `effective_metrics_*` falls back
    to once locked) need to agree, since `Settings` is only ever parsed once
    at real process startup.
    """
    env_names = {
        "metrics_user": "PROMHIS_METRICS_USER",
        "metrics_password": "PROMHIS_METRICS_PASSWORD",
        "metrics_allowed_ips": "PROMHIS_METRICS_ALLOWED_IPS",
    }
    for field, value in fields.items():
        monkeypatch.setenv(env_names[field], ",".join(value) if isinstance(value, tuple) else str(value))
        monkeypatch.setattr(settings, field, value)


async def test_metrics_ip_allowlist_blocks_unlisted_ip(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env_locked(monkeypatch, metrics_allowed_ips=("10.0.0.0/8",))
    response = await client.get("/metrics")
    assert response.status_code == 403


async def test_metrics_ip_allowlist_permits_listed_ip(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # httpx's ASGITransport reports the test client as 127.0.0.1.
    _set_env_locked(monkeypatch, metrics_allowed_ips=("127.0.0.1/32",))
    response = await client.get("/metrics")
    assert response.status_code == 200


async def test_metrics_basic_auth_required_when_configured(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env_locked(monkeypatch, metrics_user="prometheus", metrics_password="scrape-me")

    rejected = await client.get("/metrics")
    assert rejected.status_code == 401

    wrong = await client.get("/metrics", auth=("prometheus", "wrong"))
    assert wrong.status_code == 401

    accepted = await client.get("/metrics", auth=("prometheus", "scrape-me"))
    assert accepted.status_code == 200


async def test_metrics_basic_auth_ignored_when_only_one_side_set(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env_locked(monkeypatch, metrics_user="prometheus")
    response = await client.get("/metrics")
    assert response.status_code == 200


async def test_metrics_auth_overridable_via_settings_page_without_env(
    client: AsyncClient, authed_client: AsyncClient
) -> None:
    """No env var set at all — the Settings page's DB-backed override is
    what gates /metrics instead (see test_settings.py for the page itself).
    """
    saved = await authed_client.post(
        "/settings/metrics/auth",
        data={"metrics_user": "prometheus", "metrics_password": "scrape-me", "metrics_allowed_ips": ""},
    )
    assert saved.status_code == 303

    rejected = await client.get("/metrics")
    assert rejected.status_code == 401

    accepted = await client.get("/metrics", auth=("prometheus", "scrape-me"))
    assert accepted.status_code == 200
