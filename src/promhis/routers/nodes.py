"""JSON API for node-centric alert history."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from promhis import crud
from promhis.auth import require_token_or_login
from promhis.db import get_session
from promhis.schemas import AlertEventRead, NodeSummary

router = APIRouter(prefix="/api/v1/nodes", tags=["nodes"], dependencies=[Depends(require_token_or_login)])


@router.get("", response_model=list[NodeSummary])
async def api_list_nodes(sort: str = "-last_seen", session: AsyncSession = Depends(get_session)) -> list[NodeSummary]:
    return await crud.list_nodes(session, sort=sort)


@router.get("/{node}/history", response_model=list[AlertEventRead])
async def api_node_history(node: str, session: AsyncSession = Depends(get_session)) -> list[AlertEventRead]:
    events = await crud.node_alert_history(session, node)
    return [AlertEventRead.model_validate(e) for e in events]
