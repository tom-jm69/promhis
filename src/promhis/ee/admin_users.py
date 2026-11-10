"""Admin Users management — the `rbac` licensed feature (ROADMAP.md §21/§22).

Create/list/delete additional admin accounts. The Free tier stays capped at
the one bootstrap admin (`crud.sync_bootstrap_admin`, mirrored from
`PROMHIS_ADMIN_USER`/`PROMHIS_ADMIN_PASSWORD` at every startup) — creating a
second account requires `has_feature("rbac")`. Every admin account has full
access; this is about *how many people can log in*, not a permissions
system (see ROADMAP.md §21's explicit non-goals).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from promhis import crud
from promhis.auth import hash_password, require_login
from promhis.db import get_session
from promhis.licensing import has_feature
from promhis.templating import templates

ADMIN_USER_LIMIT_MESSAGE = "Free tier allows one admin user — an rbac license unlocks more."

router = APIRouter(tags=["ee-admin-users"])


@router.get("/admin-users", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def admin_users_page(request: Request, session: AsyncSession = Depends(get_session)) -> HTMLResponse:
    users = await crud.list_users(session)
    count = await crud.count_users(session)
    return templates.TemplateResponse(
        request,
        "admin_users.html",
        {
            "users": users,
            "at_free_limit": count >= 1 and not has_feature("rbac"),
            "active": "admin-users",
        },
    )


@router.post("/admin-users", response_model=None, dependencies=[Depends(require_login)])
async def create_admin_user_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    count = await crud.count_users(session)
    if count >= 1 and not has_feature("rbac"):
        raise HTTPException(status_code=402, detail=ADMIN_USER_LIMIT_MESSAGE)
    existing = await crud.get_user_by_username(session, username.strip())
    if existing is not None:
        raise HTTPException(status_code=409, detail="That username is already taken.")
    await crud.create_user(session, username=username.strip(), password_hash=hash_password(password))
    if request.headers.get("HX-Request"):
        users = await crud.list_users(session)
        new_count = await crud.count_users(session)
        return templates.TemplateResponse(
            request,
            "partials/admin_users_panel.html",
            {"users": users, "at_free_limit": new_count >= 1 and not has_feature("rbac")},
        )
    return RedirectResponse(url="/admin-users", status_code=303)


@router.post("/admin-users/{user_id}/delete", response_model=None, dependencies=[Depends(require_login)])
async def delete_admin_user_submit(
    user_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> HTMLResponse | RedirectResponse:
    deleted = await crud.delete_user(session, user_id)
    if not deleted:
        raise HTTPException(status_code=400, detail="That admin can't be deleted (unknown, or the bootstrap account).")
    if request.headers.get("HX-Request"):
        users = await crud.list_users(session)
        count = await crud.count_users(session)
        return templates.TemplateResponse(
            request,
            "partials/admin_users_panel.html",
            {"users": users, "at_free_limit": count >= 1 and not has_feature("rbac")},
        )
    return RedirectResponse(url="/admin-users", status_code=303)
