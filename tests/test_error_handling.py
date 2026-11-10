from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from promhis import crud

pytestmark = pytest.mark.asyncio


async def test_database_error_on_dashboard_route_returns_branded_503(
    authed_client_no_raise: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _broken(*args, **kwargs):
        raise SQLAlchemyError("simulated connection failure")

    monkeypatch.setattr(crud, "dashboard_stats", _broken)
    response = await authed_client_no_raise.get("/")
    assert response.status_code == 503
    assert "Database unavailable" in response.text
    assert "rail-nav" not in response.text  # standalone error page, not the full dashboard shell


async def test_database_error_on_api_route_returns_json_503(
    authed_client_no_raise: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _broken(*args, **kwargs):
        raise SQLAlchemyError("simulated connection failure")

    monkeypatch.setattr(crud, "list_alerts", _broken)
    response = await authed_client_no_raise.get("/api/v1/alerts")
    assert response.status_code == 503
    assert response.json() == {"error": "database_unavailable"}


async def test_unexpected_error_on_dashboard_route_returns_branded_500(
    authed_client_no_raise: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _broken(*args, **kwargs):
        raise RuntimeError("something genuinely unexpected")

    monkeypatch.setattr(crud, "dashboard_stats", _broken)
    response = await authed_client_no_raise.get("/")
    assert response.status_code == 500
    assert "Something went wrong" in response.text


async def test_unexpected_error_on_api_route_returns_json_500(
    authed_client_no_raise: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _broken(*args, **kwargs):
        raise RuntimeError("something genuinely unexpected")

    monkeypatch.setattr(crud, "list_alerts", _broken)
    response = await authed_client_no_raise.get("/api/v1/alerts")
    assert response.status_code == 500
    assert response.json() == {"error": "internal_error"}
