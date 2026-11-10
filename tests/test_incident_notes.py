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

FINGERPRINT = "fp-notes-1"
_UNSET_LICENSE_PATH = "/nonexistent/no-license-here.json"


@pytest.fixture
def licensed_for_annotations(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Not autouse — creating a note requires this; viewing/deleting an
    already-existing one does not (docs/licensing.md's "existing data stays
    viewable" expiry behavior).
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
        "features": ["annotations"],
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


async def _seed_alert(client: AsyncClient, fingerprint: str = FINGERPRINT) -> None:
    response = await client.post(
        "/api/v1/webhook",
        json={
            "receiver": "promhis",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "NotesTest", "severity": "critical", "node": "n1"},
                    "annotations": {},
                    "startsAt": "2026-01-01T00:00:00Z",
                    "endsAt": None,
                    "generatorURL": None,
                    "fingerprint": fingerprint,
                }
            ],
        },
        auth=("testadmin", "testpass"),
    )
    assert response.status_code == 200


async def test_notes_panel_shows_locked_message_on_free_tier(authed_client: AsyncClient) -> None:
    await _seed_alert(authed_client)
    page = await authed_client.get(f"/alerts/{FINGERPRINT}")
    assert page.status_code == 200
    assert "annotations" in page.text
    assert "No incident notes yet." in page.text


async def test_create_note_blocked_on_free_tier(authed_client: AsyncClient) -> None:
    await _seed_alert(authed_client)
    response = await authed_client.post(f"/alerts/{FINGERPRINT}/annotations", data={"body": "postmortem draft"})
    assert response.status_code == 402

    page = await authed_client.get(f"/alerts/{FINGERPRINT}")
    assert "postmortem draft" not in page.text


async def test_create_note_allowed_with_annotations_license(
    authed_client: AsyncClient, licensed_for_annotations: None
) -> None:
    await _seed_alert(authed_client)
    response = await authed_client.post(f"/alerts/{FINGERPRINT}/annotations", data={"body": "root cause: disk full"})
    assert response.status_code == 303

    page = await authed_client.get(f"/alerts/{FINGERPRINT}")
    assert "root cause: disk full" in page.text
    assert "testadmin" in page.text


async def test_create_note_via_htmx_returns_panel_fragment(
    authed_client: AsyncClient, licensed_for_annotations: None
) -> None:
    await _seed_alert(authed_client)
    response = await authed_client.post(
        f"/alerts/{FINGERPRINT}/annotations", data={"body": "htmx note"}, headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    assert 'id="incident-notes-panel"' in response.text
    assert "htmx note" in response.text
    assert "<nav" not in response.text


async def test_blank_note_body_is_not_saved(authed_client: AsyncClient, licensed_for_annotations: None) -> None:
    await _seed_alert(authed_client)
    response = await authed_client.post(f"/alerts/{FINGERPRINT}/annotations", data={"body": "   "})
    assert response.status_code == 303

    page = await authed_client.get(f"/alerts/{FINGERPRINT}")
    assert "No incident notes yet." in page.text


async def test_unknown_alert_404s_on_create(authed_client: AsyncClient, licensed_for_annotations: None) -> None:
    response = await authed_client.post("/alerts/does-not-exist/annotations", data={"body": "note"})
    assert response.status_code == 404


async def test_delete_note_works_without_a_license(
    authed_client: AsyncClient, licensed_for_annotations: None
) -> None:
    # Deletion is cleanup, not the licensed capability — creating the note
    # still needs the license, but removing it afterwards doesn't require
    # keeping (or even still holding) one.
    await _seed_alert(authed_client)
    await authed_client.post(f"/alerts/{FINGERPRINT}/annotations", data={"body": "to be deleted"})
    page = await authed_client.get(f"/alerts/{FINGERPRINT}")
    note_id = page.text.split(f"/alerts/{FINGERPRINT}/annotations/")[1].split("/delete")[0]

    response = await authed_client.post(f"/alerts/{FINGERPRINT}/annotations/{note_id}/delete")
    assert response.status_code == 303

    page_after = await authed_client.get(f"/alerts/{FINGERPRINT}")
    assert "to be deleted" not in page_after.text


async def test_delete_unknown_note_404s(authed_client: AsyncClient) -> None:
    await _seed_alert(authed_client)
    response = await authed_client.post(f"/alerts/{FINGERPRINT}/annotations/999999/delete")
    assert response.status_code == 404


async def test_existing_notes_stay_visible_after_license_removed(
    authed_client: AsyncClient, licensed_for_annotations: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_alert(authed_client)
    await authed_client.post(f"/alerts/{FINGERPRINT}/annotations", data={"body": "written while licensed"})

    # Simulate the license going away (file removed/unreadable) rather than
    # relying on the fixture's teardown, so this test can assert on the
    # unlicensed-but-still-viewable state before the fixture cleans up.
    monkeypatch.setattr(settings, "license_file", str(_UNSET_LICENSE_PATH))
    licensing_module.refresh_license_status()
    assert not licensing_module.has_feature("annotations")

    page = await authed_client.get(f"/alerts/{FINGERPRINT}")
    assert "written while licensed" in page.text
    assert "annotations" in page.text  # the locked create-form message is back
