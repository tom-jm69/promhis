from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

FINGERPRINT = "fp-notes-1"


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


async def test_notes_panel_shows_empty_state(authed_client: AsyncClient) -> None:
    await _seed_alert(authed_client)
    page = await authed_client.get(f"/alerts/{FINGERPRINT}")
    assert page.status_code == 200
    assert "No incident notes yet." in page.text


async def test_create_note(authed_client: AsyncClient) -> None:
    await _seed_alert(authed_client)
    response = await authed_client.post(f"/alerts/{FINGERPRINT}/annotations", data={"body": "root cause: disk full"})
    assert response.status_code == 303

    page = await authed_client.get(f"/alerts/{FINGERPRINT}")
    assert "root cause: disk full" in page.text
    assert "testadmin" in page.text


async def test_create_note_via_htmx_returns_panel_fragment(authed_client: AsyncClient) -> None:
    await _seed_alert(authed_client)
    response = await authed_client.post(
        f"/alerts/{FINGERPRINT}/annotations", data={"body": "htmx note"}, headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    assert 'id="incident-notes-panel"' in response.text
    assert "htmx note" in response.text
    assert "<nav" not in response.text


async def test_blank_note_body_is_not_saved(authed_client: AsyncClient) -> None:
    await _seed_alert(authed_client)
    response = await authed_client.post(f"/alerts/{FINGERPRINT}/annotations", data={"body": "   "})
    assert response.status_code == 303

    page = await authed_client.get(f"/alerts/{FINGERPRINT}")
    assert "No incident notes yet." in page.text


async def test_unknown_alert_404s_on_create(authed_client: AsyncClient) -> None:
    response = await authed_client.post("/alerts/does-not-exist/annotations", data={"body": "note"})
    assert response.status_code == 404


async def test_delete_note(authed_client: AsyncClient) -> None:
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
