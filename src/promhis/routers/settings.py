"""Settings page (`GET/POST /settings`) — operational knobs editable at
runtime without a restart: the `/metrics` scrape endpoint, scheduled
database dumps, and the daily digest email.

Each field is shown read-only whenever its matching `PROMHIS_*` env var is
set in the real process environment — an env var always wins (see
`runtime_settings.setting_env_locked`), so this page can never silently
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
from promhis.digest import effective_digest_config
from promhis.notifications.base import mask_secret
from promhis.runtime_settings import effective_bool, effective_int, effective_str, setting_env_locked
from promhis.templating import templates

router = APIRouter(tags=["dashboard"])


async def _settings_context(session: AsyncSession) -> dict:
    stored_password = await crud.get_app_setting(session, "metrics_password")
    digest_configured = (await effective_digest_config(session)) is not None
    stored_smtp_password = await crud.get_app_setting(session, "smtp_password")
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
        "db_dump_path": await effective_str(
            session, key="db_dump_path", env_var="PROMHIS_DB_DUMP_PATH", default=settings.db_dump_path
        ),
        "db_dump_path_locked": setting_env_locked("PROMHIS_DB_DUMP_PATH"),
        "db_dump_interval_hours": await effective_int(
            session,
            key="db_dump_interval_hours",
            env_var="PROMHIS_DB_DUMP_INTERVAL_HOURS",
            default=settings.db_dump_interval_hours,
        ),
        "db_dump_interval_hours_locked": setting_env_locked("PROMHIS_DB_DUMP_INTERVAL_HOURS"),
        "db_dump_min_free_mb": await effective_int(
            session,
            key="db_dump_min_free_mb",
            env_var="PROMHIS_DB_DUMP_MIN_FREE_MB",
            default=settings.db_dump_min_free_mb,
        ),
        "db_dump_min_free_mb_locked": setting_env_locked("PROMHIS_DB_DUMP_MIN_FREE_MB"),
        # Digest/SMTP — "configured" means the digest_enabled switch is on
        # *and* a recipient and SMTP host are both set, same meaning
        # digest.effective_digest_config uses to decide whether the
        # scheduler actually sends anything.
        "digest_configured": digest_configured,
        "digest_enabled": await effective_bool(
            session, key="digest_enabled", env_var="PROMHIS_DIGEST_ENABLED", default=settings.digest_enabled
        ),
        "digest_enabled_locked": setting_env_locked("PROMHIS_DIGEST_ENABLED"),
        "digest_to": await effective_str(session, key="digest_to", env_var="PROMHIS_DIGEST_TO", default=None),
        "digest_to_locked": setting_env_locked("PROMHIS_DIGEST_TO"),
        "digest_hour_utc": await effective_int(
            session, key="digest_hour_utc", env_var="PROMHIS_DIGEST_HOUR_UTC", default=settings.digest_hour_utc
        ),
        "digest_hour_utc_locked": setting_env_locked("PROMHIS_DIGEST_HOUR_UTC"),
        "smtp_host": await effective_str(session, key="smtp_host", env_var="PROMHIS_SMTP_HOST", default=None),
        "smtp_host_locked": setting_env_locked("PROMHIS_SMTP_HOST"),
        "smtp_port": await effective_int(
            session, key="smtp_port", env_var="PROMHIS_SMTP_PORT", default=settings.smtp_port
        ),
        "smtp_port_locked": setting_env_locked("PROMHIS_SMTP_PORT"),
        "smtp_user": await effective_str(session, key="smtp_user", env_var="PROMHIS_SMTP_USER", default=None),
        "smtp_user_locked": setting_env_locked("PROMHIS_SMTP_USER"),
        "smtp_password_masked": mask_secret(stored_smtp_password) if stored_smtp_password else None,
        "smtp_password_locked": setting_env_locked("PROMHIS_SMTP_PASSWORD"),
        "smtp_from": await effective_str(
            session, key="smtp_from", env_var="PROMHIS_SMTP_FROM", default=settings.smtp_from
        ),
        "smtp_from_locked": setting_env_locked("PROMHIS_SMTP_FROM"),
        "smtp_use_tls": await effective_bool(
            session, key="smtp_use_tls", env_var="PROMHIS_SMTP_USE_TLS", default=settings.smtp_use_tls
        ),
        "smtp_use_tls_locked": setting_env_locked("PROMHIS_SMTP_USE_TLS"),
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


@router.post("/settings/db-dump/config", response_model=None, dependencies=[Depends(require_login)])
async def update_db_dump_config(
    db_dump_path: str = Form(""),
    db_dump_interval_hours: int = Form(...),
    db_dump_min_free_mb: int = Form(...),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    if not setting_env_locked("PROMHIS_DB_DUMP_PATH") and db_dump_path.strip():
        await crud.set_app_setting(session, "db_dump_path", db_dump_path.strip())
    if not setting_env_locked("PROMHIS_DB_DUMP_INTERVAL_HOURS"):
        await crud.set_app_setting(session, "db_dump_interval_hours", str(db_dump_interval_hours))
    if not setting_env_locked("PROMHIS_DB_DUMP_MIN_FREE_MB"):
        await crud.set_app_setting(session, "db_dump_min_free_mb", str(db_dump_min_free_mb))
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/digest/enabled", response_model=None, dependencies=[Depends(require_login)])
async def update_digest_enabled(
    digest_enabled: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    if setting_env_locked("PROMHIS_DIGEST_ENABLED"):
        raise HTTPException(status_code=403, detail="digest_enabled is set via PROMHIS_DIGEST_ENABLED")
    await crud.set_app_setting(session, "digest_enabled", "true" if digest_enabled is not None else "false")
    return JSONResponse({"enabled": digest_enabled is not None})


@router.post("/settings/digest/config", response_model=None, dependencies=[Depends(require_login)])
async def update_digest_config(
    digest_to: str = Form(""),
    digest_hour_utc: int = Form(...),
    smtp_host: str = Form(""),
    smtp_port: int = Form(...),
    smtp_user: str = Form(""),
    smtp_password: str = Form(""),
    smtp_from: str = Form(""),
    smtp_use_tls: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    if not setting_env_locked("PROMHIS_DIGEST_TO"):
        # Multiple recipients: comma-separated, normalized to ", " —
        # an email "To:" header accepts this natively, no further parsing
        # needed anywhere else.
        addrs = [part.strip() for part in digest_to.split(",") if part.strip()]
        await crud.set_app_setting(session, "digest_to", ", ".join(addrs) or None)
    if not setting_env_locked("PROMHIS_DIGEST_HOUR_UTC"):
        await crud.set_app_setting(session, "digest_hour_utc", str(digest_hour_utc))
    if not setting_env_locked("PROMHIS_SMTP_HOST"):
        await crud.set_app_setting(session, "smtp_host", smtp_host.strip() or None)
    if not setting_env_locked("PROMHIS_SMTP_PORT"):
        await crud.set_app_setting(session, "smtp_port", str(smtp_port))
    if not setting_env_locked("PROMHIS_SMTP_USER"):
        await crud.set_app_setting(session, "smtp_user", smtp_user.strip() or None)
    if not setting_env_locked("PROMHIS_SMTP_PASSWORD") and smtp_password.strip():
        # Blank submit keeps the existing stored password unchanged — same
        # "never redisplayed, blank can't mean clear" convention as
        # metrics_password above. See clear_smtp_password for the explicit
        # clear action.
        await crud.set_app_setting(session, "smtp_password", smtp_password.strip())
    if not setting_env_locked("PROMHIS_SMTP_FROM"):
        await crud.set_app_setting(session, "smtp_from", smtp_from.strip() or None)
    if not setting_env_locked("PROMHIS_SMTP_USE_TLS"):
        await crud.set_app_setting(session, "smtp_use_tls", "true" if smtp_use_tls is not None else "false")
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/digest/clear-password", response_model=None, dependencies=[Depends(require_login)])
async def clear_smtp_password(session: AsyncSession = Depends(get_session)) -> RedirectResponse:
    if not setting_env_locked("PROMHIS_SMTP_PASSWORD"):
        await crud.set_app_setting(session, "smtp_password", None)
    return RedirectResponse(url="/settings", status_code=303)
