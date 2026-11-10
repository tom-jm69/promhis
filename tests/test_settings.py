from __future__ import annotations

import re

import pytest
from httpx import AsyncClient

from promhis import crud
from promhis.config import settings
from promhis.db import async_session_factory

pytestmark = pytest.mark.asyncio


async def test_settings_page_requires_login(client: AsyncClient) -> None:
    response = await client.get("/settings", follow_redirects=False)
    assert response.status_code == 303


async def test_settings_page_renders_unlocked_fields_by_default(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/settings")
    assert response.status_code == 200
    assert 'onchange="promhisToggleMetricsEnabled(this)"' in response.text
    assert 'name="metrics_user"' in response.text
    assert 'name="metrics_password"' in response.text
    assert 'name="metrics_allowed_ips"' in response.text
    assert "PROMHIS_METRICS_USER" not in response.text


async def test_settings_update_persists_and_gates_metrics(authed_client: AsyncClient, client: AsyncClient) -> None:
    update = await authed_client.post(
        "/settings/metrics/auth",
        data={"metrics_user": "prometheus", "metrics_password": "scrape-me", "metrics_allowed_ips": "10.0.0.0/8, 127.0.0.1"},
    )
    assert update.status_code == 303

    page = await authed_client.get("/settings")
    assert 'value="prometheus"' in page.text
    assert "10.0.0.0/8, 127.0.0.1" in page.text
    assert "••••" in page.text  # masked, never redisplayed in full

    # Test client's IP (127.0.0.1) is in the allowlist, so it clears the IP
    # gate and falls through to the Basic auth check.
    gated = await client.get("/metrics")
    assert gated.status_code == 401
    allowed = await client.get("/metrics", auth=("prometheus", "scrape-me"))
    assert allowed.status_code == 200


async def test_settings_username_without_password_rejected(authed_client: AsyncClient) -> None:
    rejected = await authed_client.post(
        "/settings/metrics/auth",
        data={"metrics_user": "prometheus", "metrics_password": "", "metrics_allowed_ips": ""},
    )
    assert rejected.status_code == 400

    # Not saved, either — rejecting is "both or neither," not "save the
    # half that validated."
    page = await authed_client.get("/settings")
    assert 'value="prometheus"' not in page.text


async def test_settings_username_alone_update_allowed_once_password_already_stored(
    authed_client: AsyncClient, client: AsyncClient
) -> None:
    await authed_client.post(
        "/settings/metrics/auth",
        data={"metrics_user": "prometheus", "metrics_password": "scrape-me", "metrics_allowed_ips": ""},
    )
    # Blank password here means "keep the one already stored," not "unset" —
    # updating just the username shouldn't trip the new guard.
    renamed = await authed_client.post(
        "/settings/metrics/auth",
        data={"metrics_user": "prometheus2", "metrics_password": "", "metrics_allowed_ips": ""},
    )
    assert renamed.status_code == 303
    assert (await client.get("/metrics", auth=("prometheus2", "scrape-me"))).status_code == 200


async def test_settings_password_field_required_once_username_set_without_a_password(
    authed_client: AsyncClient,
) -> None:
    # Constructed directly (bypassing the route's own guard above) to check
    # the template's client-side `required` attribute in isolation — the
    # state itself is otherwise unreachable through the real form/route.
    async with async_session_factory() as session:
        await crud.set_app_setting(session, "metrics_user", "orphaned-username")

    page = await authed_client.get("/settings")
    match = re.search(r'<input type="password" id="metrics_password"[^>]*>', page.text, re.DOTALL)
    assert match is not None
    assert "required" in match.group(0)


async def test_settings_blank_password_keeps_existing(authed_client: AsyncClient, client: AsyncClient) -> None:
    await authed_client.post(
        "/settings/metrics/auth", data={"metrics_user": "prometheus", "metrics_password": "scrape-me", "metrics_allowed_ips": ""}
    )
    # Re-submit the username with a blank password — must not clear it.
    await authed_client.post(
        "/settings/metrics/auth", data={"metrics_user": "prometheus", "metrics_password": "", "metrics_allowed_ips": ""}
    )
    still_gated = await client.get("/metrics")
    assert still_gated.status_code == 401
    still_works = await client.get("/metrics", auth=("prometheus", "scrape-me"))
    assert still_works.status_code == 200


async def test_settings_clear_password(authed_client: AsyncClient, client: AsyncClient) -> None:
    await authed_client.post(
        "/settings/metrics/auth", data={"metrics_user": "prometheus", "metrics_password": "scrape-me", "metrics_allowed_ips": ""}
    )
    cleared = await authed_client.post("/settings/metrics/clear-password")
    assert cleared.status_code == 303

    # No password configured anymore -> metrics_user alone isn't enough to gate it.
    open_again = await client.get("/metrics")
    assert open_again.status_code == 200


async def test_settings_page_renders_enabled_checked_by_default(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/settings")
    assert 'checked onchange="promhisToggleMetricsEnabled(this)"' in response.text


async def test_settings_disable_metrics_returns_404(authed_client: AsyncClient, client: AsyncClient) -> None:
    """The real control posts via a background `fetch()` (see the inline
    script in partials/metrics_enabled_panel.html), not a form submission —
    no DOM swap, no redirect, just a small JSON ack.
    """
    disabled = await authed_client.post("/settings/metrics/enabled", data={})  # unchecked: no field submitted
    assert disabled.status_code == 200
    assert disabled.json() == {"enabled": False}

    gone = await client.get("/metrics")
    assert gone.status_code == 404

    page = await authed_client.get("/settings")
    assert 'checked onchange="promhisToggleMetricsEnabled(this)"' not in page.text


async def test_settings_reenable_metrics(authed_client: AsyncClient, client: AsyncClient) -> None:
    await authed_client.post("/settings/metrics/enabled", data={})
    assert (await client.get("/metrics")).status_code == 404

    reenabled = await authed_client.post("/settings/metrics/enabled", data={"metrics_enabled": "on"})
    assert reenabled.status_code == 200
    assert reenabled.json() == {"enabled": True}
    assert (await client.get("/metrics")).status_code == 200


async def test_settings_metrics_enabled_env_locked(
    authed_client: AsyncClient, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROMHIS_METRICS_ENABLED", "false")
    monkeypatch.setattr(settings, "metrics_enabled", False)

    page = await authed_client.get("/settings")
    assert "PROMHIS_METRICS_ENABLED" in page.text
    assert 'onchange="promhisToggleMetricsEnabled(this)"' not in page.text

    # Posting "enable" is a no-op for the locked field.
    locked = await authed_client.post("/settings/metrics/enabled", data={"metrics_enabled": "on"})
    assert locked.status_code == 403
    assert (await client.get("/metrics")).status_code == 404


async def test_settings_env_locked_field_rejects_db_override(
    authed_client: AsyncClient, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROMHIS_METRICS_USER", "envuser")
    monkeypatch.setattr(settings, "metrics_user", "envuser")

    page = await authed_client.get("/settings")
    assert "PROMHIS_METRICS_USER" in page.text
    assert 'name="metrics_user"' not in page.text  # rendered disabled, not submittable

    # Posting a different username is a no-op for the locked field.
    await authed_client.post(
        "/settings/metrics/auth", data={"metrics_user": "someone-else", "metrics_password": "", "metrics_allowed_ips": ""}
    )
    page_after = await authed_client.get("/settings")
    assert "someone-else" not in page_after.text
