"""Settings page (`GET/POST /settings`) — a small set of operational knobs
editable at runtime without a restart. Currently just the `/metrics` scrape
endpoint: whether it's enabled at all, plus its IP allowlist/HTTP Basic auth
(see `auth.py`).

Each field is shown read-only whenever its matching `PROMHIS_METRICS_*` env
var is set in the real process environment — an env var always wins (see
`auth.metrics_setting_env_locked`), so this page can never silently
contradict what's in `.env`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from promhis import crud
from promhis.auth import (
    db_dump_setting_env_locked,
    effective_db_dump_enabled,
    effective_metrics_allowed_ips,
    effective_metrics_enabled,
    effective_metrics_user,
    metrics_setting_env_locked,
    require_login,
)
from promhis.config import settings
from promhis.db import get_session
from promhis.notifications.base import mask_secret
from promhis.templating import templates

router = APIRouter(tags=["dashboard"])


async def _settings_context(session: AsyncSession) -> dict:
    stored_password = await crud.get_app_setting(session, "metrics_password")
    return {
        "metrics_enabled": await effective_metrics_enabled(session),
        "metrics_enabled_locked": metrics_setting_env_locked("metrics_enabled"),
        "metrics_user": await effective_metrics_user(session),
        "metrics_user_locked": metrics_setting_env_locked("metrics_user"),
        "metrics_password_masked": mask_secret(stored_password) if stored_password else None,
        "metrics_password_locked": metrics_setting_env_locked("metrics_password"),
        "metrics_allowed_ips": ", ".join(await effective_metrics_allowed_ips(session)),
        "metrics_allowed_ips_locked": metrics_setting_env_locked("metrics_allowed_ips"),
        "db_dump_enabled": await effective_db_dump_enabled(session),
        "db_dump_enabled_locked": db_dump_setting_env_locked(),
        "db_dump_path": settings.db_dump_path,
        "db_dump_interval_hours": settings.db_dump_interval_hours,
        "db_dump_min_free_mb": settings.db_dump_min_free_mb,
    }


@router.get("/settings", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def settings_page(request: Request, session: AsyncSession = Depends(get_session)) -> HTMLResponse:
    context = await _settings_context(session)
    context["active"] = "settings"
    return templates.TemplateResponse(request, "settings.html", context)


@router.post("/settings/metrics/enabled", response_model=None, dependencies=[Depends(require_login)])
async def update_metrics_enabled(
    # An unchecked HTML checkbox submits no field at all, so presence (not
    # value) is what "on" means here — same convention browsers use. Read
    # from the checkbox's own state (not a blind flip) so a retried/duplicate
    # request is idempotent rather than toggling twice.
    metrics_enabled: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Called by a plain background `fetch()` (see
    `partials/metrics_enabled_panel.html`'s inline script) — no page
    reload, no DOM swap. The switch's own CSS transition is the entire
    visual response to a click; this just persists it. Returns a small
    JSON ack rather than HTML/a redirect, since nothing re-renders.
    """
    if metrics_setting_env_locked("metrics_enabled"):
        raise HTTPException(status_code=403, detail="metrics_enabled is set via PROMHIS_METRICS_ENABLED")
    await crud.set_app_setting(session, "metrics_enabled", "true" if metrics_enabled is not None else "false")
    return JSONResponse({"enabled": metrics_enabled is not None})


@router.post("/settings/metrics/auth", response_model=None, dependencies=[Depends(require_login)])
async def update_metrics_auth(
    metrics_user: str = Form(""),
    metrics_password: str = Form(""),
    metrics_allowed_ips: str = Form(""),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    # A username with no password is a silently-broken half-state — Basic
    # auth only activates when both are set (see auth.require_metrics_auth)
    # — so reject it outright rather than save it. The settings page's own
    # `required` attribute already stops this from being submitted through
    # the real form; this is defense-in-depth for a direct POST.
    if metrics_user.strip() and not metrics_setting_env_locked("metrics_user"):
        existing_password = await crud.get_app_setting(session, "metrics_password")
        if not metrics_password.strip() and not existing_password:
            raise HTTPException(status_code=400, detail="metrics_password is required once metrics_user is set")

    # Each field only applies when its env var is absent — posting a value
    # for an env-locked field is a no-op, never a silent env override.
    if not metrics_setting_env_locked("metrics_user"):
        await crud.set_app_setting(session, "metrics_user", metrics_user.strip() or None)
    if not metrics_setting_env_locked("metrics_password") and metrics_password.strip():
        # Blank submit keeps the existing stored password unchanged (same
        # "blank means unchanged" convention as the Integrations page's
        # secret fields — a secret is never redisplayed, so blank can't mean
        # "clear" here) — see `clear_metrics_password` for the explicit
        # clear action.
        await crud.set_app_setting(session, "metrics_password", metrics_password.strip())
    if not metrics_setting_env_locked("metrics_allowed_ips"):
        ips = [part.strip() for part in metrics_allowed_ips.split(",") if part.strip()]
        await crud.set_app_setting(session, "metrics_allowed_ips", ",".join(ips) or None)
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/metrics/clear-password", response_model=None, dependencies=[Depends(require_login)])
async def clear_metrics_password(session: AsyncSession = Depends(get_session)) -> RedirectResponse:
    if not metrics_setting_env_locked("metrics_password"):
        await crud.set_app_setting(session, "metrics_password", None)
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/db-dump/enabled", response_model=None, dependencies=[Depends(require_login)])
async def update_db_dump_enabled(
    db_dump_enabled: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    if db_dump_setting_env_locked():
        raise HTTPException(status_code=403, detail="db_dump_enabled is set via PROMHIS_DB_DUMP_ENABLED")
    await crud.set_app_setting(session, "db_dump_enabled", "true" if db_dump_enabled is not None else "false")
    return JSONResponse({"enabled": db_dump_enabled is not None})
