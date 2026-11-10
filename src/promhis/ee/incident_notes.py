"""Incident notes — the `annotations` licensed feature (ROADMAP.md §22/§23).

Module deliberately named `incident_notes`, not `annotations` — a module in
this package literally named `annotations` collides with every file's
`from __future__ import annotations` (which binds the name `annotations` in
`promhis.ee`'s own namespace via `ee/__init__.py`), confusing static
analysis (`from promhis.ee import annotations` resolved to the `__future__`
feature object, not the submodule, under basedpyright) even though it works
at runtime. Not worth relying on the runtime-only distinction.

Timestamped postmortem notes on an alert, distinct from the free-tier
`ack_note` (a single overwritable "someone's looking at this" flag) and from
Alertmanager's own `Alert.annotations` payload dict (read-only, unrelated).
Creating a note requires `has_feature("annotations")`; existing notes stay
visible regardless of license state (docs/licensing.md's documented
expiry/grace behavior — data already created is never hidden), and deleting
one is never gated, same as revoking an API token.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from promhis import crud
from promhis.auth import SESSION_KEY, require_login
from promhis.db import get_session
from promhis.licensing import has_feature
from promhis.templating import templates

ANNOTATIONS_LOCKED_MESSAGE = "Incident notes require an annotations license."

router = APIRouter(tags=["ee-annotations"])


@router.post("/alerts/{fingerprint}/annotations", response_model=None, dependencies=[Depends(require_login)])
async def create_annotation_submit(
    request: Request,
    fingerprint: str,
    body: str = Form(...),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    if not has_feature("annotations"):
        raise HTTPException(status_code=402, detail=ANNOTATIONS_LOCKED_MESSAGE)
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
            request,
            "partials/incident_notes_panel.html",
            {"fingerprint": fingerprint, "notes": notes, "can_annotate": True},
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
            request,
            "partials/incident_notes_panel.html",
            {"fingerprint": fingerprint, "notes": notes, "can_annotate": has_feature("annotations")},
        )
    return RedirectResponse(url=f"/alerts/{fingerprint}", status_code=303)
