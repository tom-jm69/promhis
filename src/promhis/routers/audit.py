"""JSON API for the webhook ingest audit log."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from promhis import crud
from promhis.auth import require_login_api
from promhis.db import get_session
from promhis.schemas import AuditLogEntryRead, AuditLogPage

router = APIRouter(prefix="/api/v1/audit-log", tags=["audit"], dependencies=[Depends(require_login_api)])


@router.get("", response_model=AuditLogPage)
async def api_list_audit_log(
    outcome: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> AuditLogPage:
    items, total = await crud.list_audit_log(session, outcome=outcome, page=page, page_size=page_size)
    return AuditLogPage(
        items=[AuditLogEntryRead.model_validate(e) for e in items],
        total=total,
        page=page,
        page_size=page_size,
    )
