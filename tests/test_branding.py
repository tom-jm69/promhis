from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from httpx import AsyncClient

from promhis import licensing as licensing_module
from promhis.config import settings

pytestmark = pytest.mark.asyncio


@pytest.fixture
def licensed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    private_key = Ed25519PrivateKey.generate()
    public_b64 = base64.b64encode(
        private_key.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    ).decode()
    monkeypatch.setattr(licensing_module, "PUBLIC_KEY_B64", public_b64)
    payload = {
        "customer": "Branding Test",
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": None,
        "features": ["branding"],
        "max_users": None,
    }
    payload_bytes = json.dumps(payload).encode()
    envelope = {
        "payload": base64.b64encode(payload_bytes).decode(),
        "signature": base64.b64encode(private_key.sign(payload_bytes)).decode(),
    }
    path = tmp_path / "license.json"
    path.write_text(json.dumps(envelope))
    monkeypatch.setattr(settings, "license_file", str(path))
    licensing_module.refresh_license_status()
    yield
    licensing_module._cached_status.cache_clear()  # pyright: ignore[reportPrivateUsage]


async def test_default_branding_unlicensed(authed_client: AsyncClient) -> None:
    page = await authed_client.get("/")
    assert "<title>Overview — Promhis</title>" in page.text
    assert '<span class="flame">' in page.text


async def test_custom_name_ignored_without_license(authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "brand_name", "Acme Alerts")
    page = await authed_client.get("/")
    assert "Acme Alerts" not in page.text
    assert "Promhis" in page.text


async def test_custom_name_applied_with_license(
    authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, licensed: None
) -> None:
    # Scope per ROADMAP.md §19: the navbar brand mark and page <title> are
    # branded. Body copy elsewhere (e.g. "Every alert Promhis has recorded")
    # is out of scope for this pass, not a bug this test should chase.
    monkeypatch.setattr(settings, "brand_name", "Acme Alerts")
    page = await authed_client.get("/")
    assert "<title>Overview — Acme Alerts</title>" in page.text
    assert '<span class="plate-text">' in page.text
    assert "Acme Alerts" in page.text.split('<nav class="rail-nav">')[0]  # branded navbar plate


async def test_logo_endpoint_404s_without_license(authed_client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"not a real png but good enough for a 200 check")
    monkeypatch.setattr(settings, "brand_logo_path", str(logo))
    response = await authed_client.get("/brand/logo")
    assert response.status_code == 404


async def test_logo_endpoint_serves_file_with_license(
    authed_client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, licensed: None
) -> None:
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"not a real png but good enough for a 200 check")
    monkeypatch.setattr(settings, "brand_logo_path", str(logo))
    response = await authed_client.get("/brand/logo")
    assert response.status_code == 200

    page = await authed_client.get("/")
    assert '<img class="brand-logo" src="/brand/logo"' in page.text


async def test_logo_endpoint_404s_when_configured_path_missing(
    authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, licensed: None
) -> None:
    monkeypatch.setattr(settings, "brand_logo_path", "/nonexistent/logo.png")
    response = await authed_client.get("/brand/logo")
    assert response.status_code == 404
