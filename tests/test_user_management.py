from __future__ import annotations

import pytest
import pytest_asyncio
from sqlmodel import delete

from promhis import crud
from promhis.auth import hash_password, verify_password
from promhis.db import async_session_factory, init_db
from promhis.models import User


@pytest_asyncio.fixture(autouse=True)
async def _clean_users():
    # Don't depend on another test file's `client` fixture having already
    # run `init_db()` first — this file never requests `client`.
    await init_db()
    async with async_session_factory() as session:
        await session.execute(delete(User))
        await session.commit()
    yield


def test_hash_and_verify_password_round_trip() -> None:
    stored = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", stored) is True
    assert verify_password("wrong password", stored) is False


def test_verify_password_rejects_malformed_stored_hash() -> None:
    assert verify_password("anything", "not-a-valid-hash-format") is False


def test_hash_password_uses_a_random_salt_per_call() -> None:
    # Same password, different stored hashes — a rainbow-table attacker can't
    # precompute one hash and match it against every user.
    assert hash_password("same password") != hash_password("same password")


@pytest.mark.asyncio
async def test_sync_bootstrap_admin_creates_on_first_call() -> None:
    async with async_session_factory() as session:
        user = await crud.sync_bootstrap_admin(session, username="admin", password_hash=hash_password("pw1"))
        assert user.username == "admin"
        assert user.is_bootstrap is True
        assert await crud.count_users(session) == 1


@pytest.mark.asyncio
async def test_sync_bootstrap_admin_is_idempotent() -> None:
    async with async_session_factory() as session:
        await crud.sync_bootstrap_admin(session, username="admin", password_hash=hash_password("pw1"))
        await crud.sync_bootstrap_admin(session, username="admin", password_hash=hash_password("pw1"))
        assert await crud.count_users(session) == 1


@pytest.mark.asyncio
async def test_sync_bootstrap_admin_renames_on_username_change() -> None:
    async with async_session_factory() as session:
        await crud.sync_bootstrap_admin(session, username="admin", password_hash=hash_password("pw1"))
        renamed = await crud.sync_bootstrap_admin(session, username="root", password_hash=hash_password("pw1"))
        assert renamed.username == "root"
        assert await crud.count_users(session) == 1  # renamed in place, not duplicated
        assert await crud.get_user_by_username(session, "admin") is None


@pytest.mark.asyncio
async def test_sync_bootstrap_admin_rotates_password() -> None:
    async with async_session_factory() as session:
        await crud.sync_bootstrap_admin(session, username="admin", password_hash=hash_password("old-password"))
        await crud.sync_bootstrap_admin(session, username="admin", password_hash=hash_password("new-password"))
        user = await crud.get_user_by_username(session, "admin")
        assert user is not None
        assert verify_password("new-password", user.password_hash) is True
        assert verify_password("old-password", user.password_hash) is False


@pytest.mark.asyncio
async def test_delete_user_refuses_to_delete_bootstrap_admin() -> None:
    async with async_session_factory() as session:
        bootstrap = await crud.sync_bootstrap_admin(session, username="admin", password_hash=hash_password("pw1"))
        assert bootstrap.id is not None
        deleted = await crud.delete_user(session, bootstrap.id)
        assert deleted is False
        assert await crud.count_users(session) == 1


@pytest.mark.asyncio
async def test_delete_user_removes_a_non_bootstrap_user() -> None:
    async with async_session_factory() as session:
        await crud.sync_bootstrap_admin(session, username="admin", password_hash=hash_password("pw1"))
        extra = await crud.create_user(session, username="second-admin", password_hash=hash_password("pw2"))
        assert extra.id is not None
        deleted = await crud.delete_user(session, extra.id)
        assert deleted is True
        assert await crud.count_users(session) == 1


@pytest.mark.asyncio
async def test_list_users_returns_all_in_creation_order() -> None:
    async with async_session_factory() as session:
        await crud.sync_bootstrap_admin(session, username="admin", password_hash=hash_password("pw1"))
        await crud.create_user(session, username="second-admin", password_hash=hash_password("pw2"))
        users = await crud.list_users(session)
        assert [u.username for u in users] == ["admin", "second-admin"]
