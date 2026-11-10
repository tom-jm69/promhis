from __future__ import annotations

import pytest
from httpx import AsyncClient

from promhis import crud
from promhis.auth import hash_password
from promhis.db import async_session_factory

pytestmark = pytest.mark.asyncio


async def test_overview_requires_login(client: AsyncClient) -> None:
    response = await client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


async def test_login_rejects_bad_password(client: AsyncClient) -> None:
    response = await client.post("/login", data={"username": "testadmin", "password": "wrong", "next": "/"})
    assert response.status_code == 401


async def test_login_rejects_unknown_username(client: AsyncClient) -> None:
    response = await client.post("/login", data={"username": "nobody", "password": "testpass", "next": "/"})
    assert response.status_code == 401


async def test_login_succeeds_with_bootstrap_credentials_and_records_login(client: AsyncClient) -> None:
    # The bootstrap admin (ROADMAP.md §21) is a real User-table row now, not
    # just a live env-var comparison — login goes through crud.get_user_by_username
    # + verify_password, and a successful login updates last_login_at.
    async with async_session_factory() as session:
        before = await crud.get_user_by_username(session, "testadmin")
        assert before is not None
        assert before.last_login_at is None

    response = await client.post("/login", data={"username": "testadmin", "password": "testpass", "next": "/"})
    assert response.status_code == 303

    async with async_session_factory() as session:
        after = await crud.get_user_by_username(session, "testadmin")
        assert after is not None
        assert after.last_login_at is not None


async def test_login_rejects_inactive_user(client: AsyncClient, anon_client: AsyncClient) -> None:
    # `client` isn't used directly — just needed for its fixture side effect
    # (init_db + truncation + bootstrap-admin sync) before `anon_client`
    # (its own separate, un-initialized-by-default connection) is used.
    async with async_session_factory() as session:
        user = await crud.create_user(session, username="disabled-admin", password_hash=hash_password("pw"))
        user.is_active = False
        session.add(user)
        await session.commit()

    response = await anon_client.post("/login", data={"username": "disabled-admin", "password": "pw", "next": "/"})
    assert response.status_code == 401


async def test_pages_render_after_login(authed_client: AsyncClient) -> None:
    for path in ("/", "/alerts", "/nodes"):
        response = await authed_client.get(path)
        assert response.status_code == 200, path


async def test_unknown_alert_detail_404s(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/alerts/does-not-exist")
    assert response.status_code == 404


async def test_nodes_sort_via_htmx_returns_panel_fragment(authed_client: AsyncClient) -> None:
    full_page = await authed_client.get("/nodes")
    assert full_page.status_code == 200
    assert "Configured integrations" not in full_page.text  # sanity: it's actually the Nodes page

    fragment = await authed_client.get("/nodes?sort=node", headers={"HX-Request": "true"})
    assert fragment.status_code == 200
    assert 'id="nodes-panel"' in fragment.text
    # A fragment response is just the panel, not the surrounding page chrome.
    assert "<nav" not in fragment.text


async def test_audit_log_filter_via_htmx_returns_panel_fragment(authed_client: AsyncClient) -> None:
    fragment = await authed_client.get("/audit-log?outcome=success", headers={"HX-Request": "true"})
    assert fragment.status_code == 200
    assert 'id="audit-panel"' in fragment.text
    assert "<nav" not in fragment.text


async def test_stats_range_via_htmx_returns_panel_fragment(authed_client: AsyncClient) -> None:
    fragment = await authed_client.get("/stats?range=30d", headers={"HX-Request": "true"})
    assert fragment.status_code == 200
    assert 'id="stats-panel"' in fragment.text
    assert 'id="range-stats-data"' in fragment.text  # fresh chart payload travels with the fragment
    assert "<nav" not in fragment.text


async def test_alert_ack_via_htmx_returns_ack_panel_fragment(authed_client: AsyncClient) -> None:
    await authed_client.post(
        "/api/v1/webhook",
        json={
            "receiver": "promhis",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "AckHtmxTest", "severity": "critical", "node": "n1"},
                    "annotations": {},
                    "startsAt": "2026-01-01T00:00:00Z",
                    "endsAt": None,
                    "generatorURL": None,
                    "fingerprint": "fp-ack-htmx-1",
                }
            ],
        },
        auth=("testadmin", "testpass"),
    )

    response = await authed_client.post(
        "/alerts/fp-ack-htmx-1/ack", data={"note": "looking into it"}, headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    assert 'id="ack-panel"' in response.text
    assert "looking into it" in response.text
    assert "<nav" not in response.text


async def test_onboarding_checklist_shown_on_fresh_instance(authed_client: AsyncClient) -> None:
    page = await authed_client.get("/")
    assert page.status_code == 200
    assert 'id="onboarding-checklist"' in page.text
    # Free tier's one admin slot is always the bootstrap admin, so the
    # teammate-invite step (a dead end without rbac) must not render.
    assert "Invite a teammate" not in page.text


async def test_onboarding_checklist_hidden_once_a_webhook_has_been_received(authed_client: AsyncClient) -> None:
    await authed_client.post(
        "/api/v1/webhook",
        json={
            "receiver": "promhis",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "OnboardingTest", "severity": "critical", "node": "n1"},
                    "annotations": {},
                    "startsAt": "2026-01-01T00:00:00Z",
                    "endsAt": None,
                    "generatorURL": None,
                    "fingerprint": "fp-onboarding-1",
                }
            ],
        },
        auth=("testadmin", "testpass"),
    )

    page = await authed_client.get("/")
    assert "onboarding-checklist" not in page.text
