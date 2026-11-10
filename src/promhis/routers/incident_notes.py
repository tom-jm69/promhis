"""Incident notes — timestamped postmortem notes on an alert.

Distinct from `Alert.ack_note` (a single overwritable "someone's looking at
this" flag) and from Alertmanager's own `Alert.annotations` payload dict
(read-only, unrelated).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from promhis import crud
from promhis.auth import SESSION_KEY, require_login
from promhis.db import get_session
from promhis.templating import templates

router = APIRouter(tags=["incident-notes"])


@router.post("/alerts/{fingerprint}/annotations", response_model=None, dependencies=[Depends(require_login)])
async def create_annotation_submit(
    request: Request,
    fingerprint: str,
    body: str = Form(...),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    alert = await crud.get_alert(session, fingerprint)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    body = body.strip()
    if body:
        author = request.session.get(SESSION_KEY, "unknown")
        await crud.create_annotation(session, fingerprint=fingerprint, author=author, body=body)
    if request.headers.get("HX-Request"):
        notes = await crud.list_annotations(session, fingerprint)
        return templates.TemplateResponse(
            request, "partials/incident_notes_panel.html", {"fingerprint": fingerprint, "notes": notes}
        )
    return RedirectResponse(url=f"/alerts/{fingerprint}", status_code=303)


@router.post(
    "/alerts/{fingerprint}/annotations/{annotation_id}/delete",
    response_model=None,
    dependencies=[Depends(require_login)],
)
async def delete_annotation_submit(
    request: Request,
    fingerprint: str,
    annotation_id: int,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    deleted = await crud.delete_annotation(session, annotation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Note not found")
    if request.headers.get("HX-Request"):
        notes = await crud.list_annotations(session, fingerprint)
        return templates.TemplateResponse(
            request, "partials/incident_notes_panel.html", {"fingerprint": fingerprint, "notes": notes}
        )
    return RedirectResponse(url=f"/alerts/{fingerprint}", status_code=303)
