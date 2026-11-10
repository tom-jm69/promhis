"""JSON API for dashboard-wide summary stats."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from promhis import crud
from promhis.auth import require_token_or_login
from promhis.db import get_session
from promhis.schemas import Stats

router = APIRouter(prefix="/api/v1/stats", tags=["stats"], dependencies=[Depends(require_token_or_login)])


@router.get("", response_model=Stats)
async def api_stats(session: AsyncSession = Depends(get_session)) -> Stats:
    return await crud.dashboard_stats(session)
