from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient

from promhis.config import settings

pytestmark = pytest.mark.asyncio


async def test_default_branding(authed_client: AsyncClient) -> None:
    page = await authed_client.get("/")
    assert "<title>Overview — Promhis</title>" in page.text
    assert '<span class="flame">' in page.text


async def test_custom_name_applied(authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "brand_name", "Acme Alerts")
    page = await authed_client.get("/")
    assert "<title>Overview — Acme Alerts</title>" in page.text
    assert '<span class="plate-text">' in page.text
    assert "Acme Alerts" in page.text.split('<nav class="rail-nav">')[0]  # branded navbar plate


async def test_logo_endpoint_404s_when_unconfigured(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/brand/logo")
    assert response.status_code == 404


async def test_logo_endpoint_serves_configured_file(
    authed_client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"not a real png but good enough for a 200 check")
    monkeypatch.setattr(settings, "brand_logo_path", str(logo))
    response = await authed_client.get("/brand/logo")
    assert response.status_code == 200

    page = await authed_client.get("/")
    assert '<img class="brand-logo" src="/brand/logo"' in page.text


async def test_logo_endpoint_404s_when_configured_path_missing(
    authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "brand_logo_path", "/nonexistent/logo.png")
    response = await authed_client.get("/brand/logo")
    assert response.status_code == 404
