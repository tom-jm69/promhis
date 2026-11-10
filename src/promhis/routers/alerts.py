"""JSON API for alert history — backs the dashboard's own fetches."""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from promhis import crud
from promhis.auth import require_token_or_login
from promhis.db import get_session
from promhis.schemas import AlertDetail, AlertEventRead, AlertRead, Page

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"], dependencies=[Depends(require_token_or_login)])

# A safety cap, not a real-world limit — this is a low-volume webhook
# receiver (see PRICING.md's tiers), so a single export realistically never
# gets close to this.
EXPORT_ROW_LIMIT = 50_000

# Alertmanager labels (alertname, node, receiver, group_key) are free text an
# attacker with webhook credentials fully controls. A value starting with one
# of these characters is interpreted as a formula by Excel/Sheets/LibreOffice
# when the exported CSV is opened — prefix with a quote to force text.
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: str) -> str:
    return f"'{value}" if value.startswith(_CSV_FORMULA_PREFIXES) else value

CSV_COLUMNS = [
    "fingerprint",
    "alertname",
    "status",
    "severity",
    "node",
    "starts_at",
    "ends_at",
    "receiver",
    "group_key",
    "first_seen",
    "last_seen",
]


# Registered before "/{fingerprint}" — FastAPI matches path routes in
# registration order, so a dynamic param route defined first would swallow
# "export.csv" as a fingerprint value.
@router.get("/export.csv")
async def api_export_alerts_csv(
    status: str | None = None,
    severity: str | None = None,
    node: str | None = None,
    alertname: str | None = None,
    search: str | None = None,
    group: str | None = None,
    sort: str = "-last_seen",
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    items, _ = await crud.list_alerts(
        session,
        status=status,
        severity=severity,
        node=node,
        alertname=alertname,
        search=search,
        group=group,
        sort=sort,
        page=1,
        page_size=EXPORT_ROW_LIMIT,
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for a in items:
        writer.writerow(
            [
                a.fingerprint,
                _csv_safe(a.alertname),
                a.status,
                _csv_safe(a.severity or ""),
                _csv_safe(a.node or ""),
                a.starts_at.isoformat(),
                a.ends_at.isoformat() if a.ends_at else "",
                _csv_safe(a.receiver or ""),
                _csv_safe(a.group_key or ""),
                a.first_seen.isoformat(),
                a.last_seen.isoformat(),
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=promhis-alerts.csv"},
    )


@router.get("", response_model=Page)
async def api_list_alerts(
    status: str | None = None,
    severity: str | None = None,
    node: str | None = None,
    alertname: str | None = None,
    search: str | None = None,
    group: str | None = None,
    sort: str = "-last_seen",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> Page:
    items, total = await crud.list_alerts(
        session,
        status=status,
        severity=severity,
        node=node,
        alertname=alertname,
        search=search,
        group=group,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[AlertRead.model_validate(a) for a in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{fingerprint}", response_model=AlertDetail)
async def api_get_alert(fingerprint: str, session: AsyncSession = Depends(get_session)) -> AlertDetail:
    alert = await crud.get_alert(session, fingerprint)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    events = await crud.get_alert_events(session, fingerprint)
    return AlertDetail(
        **AlertRead.model_validate(alert).model_dump(),
        events=[AlertEventRead.model_validate(e) for e in events],
    )
