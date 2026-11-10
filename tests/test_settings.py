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


async def test_settings_page_renders_db_dump_disabled_by_default(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/settings")
    assert response.status_code == 200
    assert 'onchange="promhisToggleDbDumpEnabled(this)"' in response.text
    assert 'checked onchange="promhisToggleDbDumpEnabled(this)"' not in response.text


async def test_settings_enable_and_disable_db_dump(authed_client: AsyncClient) -> None:
    enabled = await authed_client.post("/settings/db-dump/enabled", data={"db_dump_enabled": "on"})
    assert enabled.status_code == 200
    assert enabled.json() == {"enabled": True}

    page = await authed_client.get("/settings")
    assert 'checked onchange="promhisToggleDbDumpEnabled(this)"' in page.text

    disabled = await authed_client.post("/settings/db-dump/enabled", data={})
    assert disabled.status_code == 200
    assert disabled.json() == {"enabled": False}

    page_after = await authed_client.get("/settings")
    assert 'checked onchange="promhisToggleDbDumpEnabled(this)"' not in page_after.text


async def test_settings_db_dump_enabled_env_locked(
    authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROMHIS_DB_DUMP_ENABLED", "true")
    monkeypatch.setattr(settings, "db_dump_enabled", True)

    page = await authed_client.get("/settings")
    assert "PROMHIS_DB_DUMP_ENABLED" in page.text
    assert 'onchange="promhisToggleDbDumpEnabled(this)"' not in page.text

    locked = await authed_client.post("/settings/db-dump/enabled", data={})
    assert locked.status_code == 403


async def test_settings_db_dump_config_persists(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/settings/db-dump/config",
        data={"db_dump_path": "/custom/dumps", "db_dump_interval_hours": "6", "db_dump_min_free_mb": "1000"},
    )
    assert response.status_code == 303

    page = await authed_client.get("/settings")
    assert 'value="/custom/dumps"' in page.text
    assert 'value="6"' in page.text
    assert 'value="1000"' in page.text


async def test_settings_db_dump_path_env_locked(authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMHIS_DB_DUMP_PATH", "/env/dumps")
    monkeypatch.setattr(settings, "db_dump_path", "/env/dumps")

    page = await authed_client.get("/settings")
    assert "PROMHIS_DB_DUMP_PATH" in page.text
    assert 'name="db_dump_path"' not in page.text

    # The locked field is a no-op; other fields in the same form still save.
    await authed_client.post(
        "/settings/db-dump/config",
        data={"db_dump_path": "/ignored", "db_dump_interval_hours": "12", "db_dump_min_free_mb": "250"},
    )
    page_after = await authed_client.get("/settings")
    assert 'value="12"' in page_after.text
    assert "/ignored" not in page_after.text


async def test_settings_digest_config_persists_and_reports_configured(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/settings/digest/config",
        data={
            "digest_to": "oncall@example.com",
            "digest_hour_utc": "9",
            "smtp_host": "smtp.example.com",
            "smtp_port": "587",
            "smtp_user": "notifier",
            "smtp_password": "hunter2",
            "smtp_from": "promhis@example.com",
            "smtp_use_tls": "on",
        },
    )
    assert response.status_code == 303

    page = await authed_client.get("/settings")
    assert 'value="oncall@example.com"' in page.text
    assert 'value="smtp.example.com"' in page.text
    assert "Sends a daily rollup" in page.text  # digest_configured is now true


async def test_settings_digest_smtp_password_blank_keeps_existing(authed_client: AsyncClient) -> None:
    await authed_client.post(
        "/settings/digest/config",
        data={
            "digest_to": "oncall@example.com",
            "digest_hour_utc": "8",
            "smtp_host": "smtp.example.com",
            "smtp_port": "587",
            "smtp_user": "",
            "smtp_password": "hunter2",
            "smtp_from": "promhis@localhost",
        },
    )
    # Blank password on a second save keeps the stored one rather than clearing it.
    await authed_client.post(
        "/settings/digest/config",
        data={
            "digest_to": "oncall@example.com",
            "digest_hour_utc": "8",
            "smtp_host": "smtp.example.com",
            "smtp_port": "587",
            "smtp_user": "",
            "smtp_password": "",
            "smtp_from": "promhis@localhost",
        },
    )
    page = await authed_client.get("/settings")
    assert "Currently set" in page.text


async def test_settings_digest_clear_password(authed_client: AsyncClient) -> None:
    await authed_client.post(
        "/settings/digest/config",
        data={
            "digest_to": "oncall@example.com",
            "digest_hour_utc": "8",
            "smtp_host": "smtp.example.com",
            "smtp_port": "587",
            "smtp_user": "",
            "smtp_password": "hunter2",
            "smtp_from": "promhis@localhost",
        },
    )
    await authed_client.post("/settings/digest/clear-password")
    page = await authed_client.get("/settings")
    assert "Currently set" not in page.text


async def test_settings_digest_smtp_host_env_locked(
    authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROMHIS_SMTP_HOST", "env-smtp.example.com")
    monkeypatch.setattr(settings, "smtp_host", "env-smtp.example.com")

    page = await authed_client.get("/settings")
    assert "PROMHIS_SMTP_HOST" in page.text
    assert 'name="smtp_host"' not in page.text

    await authed_client.post(
        "/settings/digest/config",
        data={
            "digest_to": "oncall@example.com",
            "digest_hour_utc": "8",
            "smtp_host": "ignored.example.com",
            "smtp_port": "587",
            "smtp_user": "",
            "smtp_password": "",
            "smtp_from": "promhis@localhost",
        },
    )
    page_after = await authed_client.get("/settings")
    assert "ignored.example.com" not in page_after.text
    assert "env-smtp.example.com" in page_after.text
