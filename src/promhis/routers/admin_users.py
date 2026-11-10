"""Admin Users management.

Create/list/delete additional admin accounts. Every admin account has full
access; this is about *how many people can log in*, not a permissions
system.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from promhis import crud
from promhis.auth import hash_password, require_login
from promhis.db import get_session
from promhis.templating import templates

router = APIRouter(tags=["admin-users"])


@router.get("/admin-users", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def admin_users_page(request: Request, session: AsyncSession = Depends(get_session)) -> HTMLResponse:
    users = await crud.list_users(session)
    return templates.TemplateResponse(
        request,
        "admin_users.html",
        {
            "users": users,
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
    existing = await crud.get_user_by_username(session, username.strip())
    if existing is not None:
        raise HTTPException(status_code=409, detail="That username is already taken.")
    await crud.create_user(session, username=username.strip(), password_hash=hash_password(password))
    if request.headers.get("HX-Request"):
        users = await crud.list_users(session)
        return templates.TemplateResponse(request, "partials/admin_users_panel.html", {"users": users})
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
        return templates.TemplateResponse(request, "partials/admin_users_panel.html", {"users": users})
    return RedirectResponse(url="/admin-users", status_code=303)
