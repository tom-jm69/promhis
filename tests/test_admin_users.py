from __future__ import annotations

import pytest
from httpx import AsyncClient

from promhis import crud
from promhis.db import async_session_factory

pytestmark = pytest.mark.asyncio


async def test_admin_users_page_requires_login(client: AsyncClient) -> None:
    response = await client.get("/admin-users", follow_redirects=False)
    assert response.status_code == 303


async def test_admin_users_page_shows_bootstrap_admin(authed_client: AsyncClient) -> None:
    page = await authed_client.get("/admin-users")
    assert page.status_code == 200
    assert "testadmin" in page.text
    assert "bootstrap" in page.text


async def test_second_admin_can_be_created(authed_client: AsyncClient) -> None:
    response = await authed_client.post("/admin-users", data={"username": "second", "password": "pw12345"})
    assert response.status_code == 303

    page = await authed_client.get("/admin-users")
    assert "testadmin" in page.text
    assert "second" in page.text


async def test_duplicate_username_rejected(authed_client: AsyncClient) -> None:
    await authed_client.post("/admin-users", data={"username": "second", "password": "pw12345"})
    response = await authed_client.post("/admin-users", data={"username": "second", "password": "different"})
    assert response.status_code == 409


async def test_bootstrap_admin_cannot_be_deleted(authed_client: AsyncClient) -> None:
    # The UI itself never renders a delete button for the bootstrap admin
    # (see partials/admin_user_row.html) — this confirms the route-level
    # refusal too (crud.delete_user), defense in depth, not just a hidden button.
    async with async_session_factory() as session:
        bootstrap = await crud.get_user_by_username(session, "testadmin")
    assert bootstrap is not None

    page = await authed_client.get("/admin-users")
    assert f'action="/admin-users/{bootstrap.id}/delete"' not in page.text

    response = await authed_client.post(f"/admin-users/{bootstrap.id}/delete")
    assert response.status_code == 400

    page_after = await authed_client.get("/admin-users")
    assert "testadmin" in page_after.text


async def test_non_bootstrap_admin_can_be_deleted(authed_client: AsyncClient) -> None:
    await authed_client.post("/admin-users", data={"username": "second", "password": "pw12345"})
    page = await authed_client.get("/admin-users")
    # The non-bootstrap row is the only one with a delete form.
    user_id = page.text.split('action="/admin-users/')[1].split("/delete")[0]

    delete = await authed_client.post(f"/admin-users/{user_id}/delete")
    assert delete.status_code == 303

    page_after = await authed_client.get("/admin-users")
    assert "second" not in page_after.text


async def test_create_admin_via_htmx_returns_panel_fragment(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/admin-users", data={"username": "htmx-admin", "password": "pw12345"}, headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    assert 'id="admin-users-panel"' in response.text
    assert "htmx-admin" in response.text
    assert "<nav" not in response.text


async def test_onboarding_checklist_offers_teammate_invite(authed_client: AsyncClient) -> None:
    page = await authed_client.get("/")
    assert 'id="onboarding-checklist"' in page.text
    assert "Invite a teammate" in page.text


async def test_new_admin_can_log_in(authed_client: AsyncClient, anon_client: AsyncClient) -> None:
    await authed_client.post("/admin-users", data={"username": "second-admin", "password": "second-pw"})

    login = await anon_client.post("/login", data={"username": "second-admin", "password": "second-pw", "next": "/"})
    assert login.status_code == 303
    overview = await anon_client.get("/")
    assert overview.status_code == 200
