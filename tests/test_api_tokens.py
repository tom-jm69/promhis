from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from httpx import AsyncClient

from promhis import licensing as licensing_module
from promhis.config import settings

pytestmark = pytest.mark.asyncio


@pytest.fixture
def licensed_for_service_tokens(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Not autouse — one free personal API token needs no license at all
    (docs/licensing.md); only tests exercising the `service_tokens` feature
    (more than one active token) need this.
    """
    private_key = Ed25519PrivateKey.generate()
    public_b64 = base64.b64encode(
        private_key.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    ).decode()
    monkeypatch.setattr(licensing_module, "PUBLIC_KEY_B64", public_b64)

    payload = {
        "customer": "Test Suite",
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": None,
        "features": ["service_tokens"],
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


def _extract_new_token(page_html: str) -> str:
    marker = 'class="label-pill new-token-display">'
    start = page_html.index(marker) + len(marker)
    end = page_html.index("</div>", start)
    return page_html[start:end].strip()


async def test_api_tokens_page_requires_login(client: AsyncClient) -> None:
    response = await client.get("/api-tokens", follow_redirects=False)
    assert response.status_code == 303


async def test_create_list_and_use_token(
    authed_client: AsyncClient, anon_client: AsyncClient
) -> None:
    # One personal read-only token is free (docs/licensing.md) — no license
    # needed for this, unlike the old "whole feature is Enterprise" model.
    create = await authed_client.post("/api-tokens", data={"name": "Grafana"})
    assert create.status_code == 303

    page = await authed_client.get("/api-tokens")
    assert page.status_code == 200
    assert "Grafana" in page.text
    assert "Copy it now" in page.text  # the raw token is shown exactly once

    raw_token = _extract_new_token(page.text)
    assert raw_token.startswith("promhis_")

    # A genuinely separate, unauthenticated caller (see anon_client's
    # docstring — `client` would still be carrying authed_client's session
    # cookie here, which isn't the scenario this is testing) using only the
    # token — this is the actual point of the feature.
    via_token = await anon_client.get("/api/v1/stats", headers={"Authorization": f"Bearer {raw_token}"})
    assert via_token.status_code == 200

    # The raw token is genuinely gone on a second view of the page.
    page_again = await authed_client.get("/api-tokens")
    assert "Copy it now" not in page_again.text


async def test_webhook_credentials_do_not_work_as_api_tokens(client: AsyncClient) -> None:
    # The read routes' Bearer check is against stored API token hashes only
    # — it must not accidentally accept the webhook's Basic/Bearer scheme.
    response = await client.get("/api/v1/stats", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


async def test_revoked_token_rejected(authed_client: AsyncClient, anon_client: AsyncClient) -> None:
    await authed_client.post("/api-tokens", data={"name": "Temp"})
    page = await authed_client.get("/api-tokens")
    raw_token = _extract_new_token(page.text)

    list_page = await authed_client.get("/api-tokens")
    token_id = list_page.text.split('action="/api-tokens/')[1].split("/revoke")[0]

    revoke = await authed_client.post(f"/api-tokens/{token_id}/revoke")
    assert revoke.status_code == 303

    via_token = await anon_client.get("/api/v1/stats", headers={"Authorization": f"Bearer {raw_token}"})
    assert via_token.status_code == 401


async def test_second_token_blocked_on_free_tier(authed_client: AsyncClient) -> None:
    first = await authed_client.post("/api-tokens", data={"name": "First"})
    assert first.status_code == 303

    second = await authed_client.post("/api-tokens", data={"name": "Second"})
    assert second.status_code == 402

    page = await authed_client.get("/api-tokens")
    assert "service_tokens" in page.text
    assert "First" in page.text
    assert "Second" not in page.text


async def test_second_token_allowed_with_service_tokens_license(
    authed_client: AsyncClient, licensed_for_service_tokens: None
) -> None:
    first = await authed_client.post("/api-tokens", data={"name": "First"})
    assert first.status_code == 303

    second = await authed_client.post("/api-tokens", data={"name": "Second"})
    assert second.status_code == 303

    page = await authed_client.get("/api-tokens")
    assert "First" in page.text
    assert "Second" in page.text


async def test_revoking_frees_the_slot_back_up_on_free_tier(authed_client: AsyncClient) -> None:
    await authed_client.post("/api-tokens", data={"name": "First"})
    page = await authed_client.get("/api-tokens")
    token_id = page.text.split('action="/api-tokens/')[1].split("/revoke")[0]
    await authed_client.post(f"/api-tokens/{token_id}/revoke")

    second = await authed_client.post("/api-tokens", data={"name": "Second"})
    assert second.status_code == 303


async def test_create_token_via_htmx_returns_panel_fragment(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api-tokens", data={"name": "HtmxToken"}, headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    assert 'id="tokens-panel"' in response.text
    assert "HtmxToken" in response.text
    assert "Copy it now" in response.text  # the new token is rendered inline, not via session-flash
    assert "<nav" not in response.text


async def test_revoke_token_via_htmx_returns_row_fragment(authed_client: AsyncClient) -> None:
    await authed_client.post("/api-tokens", data={"name": "ToRevoke"})
    page = await authed_client.get("/api-tokens")
    token_id = page.text.split('action="/api-tokens/')[1].split("/revoke")[0]

    response = await authed_client.post(
        f"/api-tokens/{token_id}/revoke", headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    assert f'id="token-row-{token_id}"' in response.text
    assert "revoked" in response.text
    assert "<nav" not in response.text


async def test_audit_log_not_accessible_via_api_token(
    authed_client: AsyncClient, anon_client: AsyncClient
) -> None:
    await authed_client.post("/api-tokens", data={"name": "Grafana"})
    page = await authed_client.get("/api-tokens")
    raw_token = _extract_new_token(page.text)

    response = await anon_client.get("/api/v1/audit-log", headers={"Authorization": f"Bearer {raw_token}"})
    assert response.status_code == 401
