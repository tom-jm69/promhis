from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from promhis import crud
from promhis.auth import hash_password
from promhis.config import settings
from promhis.db import async_session_factory, init_db
from promhis.digest import run_digest_scheduler
from promhis.ee import admin_users as ee_admin_users
from promhis.ee import incident_notes as ee_incident_notes
from promhis.licensing import FeatureRequiredError, has_feature, refresh_license_status
from promhis.poller import run_poller
from promhis.routers import alerts, audit, dashboard, metrics, nodes, settings as settings_router, stats, webhook
from promhis.templating import templates

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("promhis")

STATIC_DIR = Path(__file__).parent / "static"

RETENTION_INTERVAL_SECONDS = 24 * 60 * 60
LICENSE_RECHECK_INTERVAL_SECONDS = 24 * 60 * 60


async def _license_recheck_loop() -> None:
    # A license is verified once at startup (see lifespan below) and cached
    # (licensing.get_license_status is lru_cache'd) — this is what catches a
    # license crossing from ACTIVE into GRACE/EXPIRED without requiring a
    # restart, same shape as the retention loop below.
    while True:
        await asyncio.sleep(LICENSE_RECHECK_INTERVAL_SECONDS)
        refresh_license_status()


async def _retention_loop() -> None:
    while True:
        await asyncio.sleep(RETENTION_INTERVAL_SECONDS)
        async with async_session_factory() as session:
            pruned = await crud.prune_old_events(session, retention_days=settings.retention_days)
            if pruned:
                logger.info("retention: pruned %d old alert events", pruned)
            pruned_audit = await crud.prune_old_audit_entries(session, retention_days=settings.retention_days)
            if pruned_audit:
                logger.info("retention: pruned %d old audit log entries", pruned_audit)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    async with async_session_factory() as session:
        # Keeps the env-var admin identity working exactly as documented
        # today (ROADMAP.md §21) — an existing self-hosted install upgrading
        # to this version logs in exactly the same way it always has.
        await crud.sync_bootstrap_admin(
            session, username=settings.admin_user, password_hash=hash_password(settings.admin_password)
        )
    refresh_license_status()  # verify once at startup, per docs/licensing.md
    tasks = [asyncio.create_task(run_poller()), asyncio.create_task(_license_recheck_loop())]
    if settings.retention_days > 0:
        tasks.append(asyncio.create_task(_retention_loop()))
    if settings.digest_to and settings.smtp_host:
        tasks.append(asyncio.create_task(run_digest_scheduler()))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_title, lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, same_site="lax")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(webhook.router)
    app.include_router(metrics.router)
    app.include_router(settings_router.router)
    app.include_router(alerts.router)
    app.include_router(nodes.router)
    app.include_router(stats.router)
    app.include_router(audit.router)
    app.include_router(dashboard.router)
    app.include_router(ee_admin_users.router)
    app.include_router(ee_incident_notes.router)

    @app.exception_handler(FeatureRequiredError)
    async def _feature_required_handler(request: Request, exc: FeatureRequiredError):
        # docs/licensing.md: JSON 402 for API routes, an upgrade-notice page
        # for dashboard routes — used by routes built with
        # `Depends(licensing.require_feature(flag))` (none yet; the gates
        # built so far check `has_feature` inline instead, see ROADMAP.md §22).
        if request.url.path.startswith("/api/"):
            return JSONResponse(status_code=402, content={"error": "feature_required", "feature": exc.flag})
        return templates.TemplateResponse(request, "upgrade_required.html", {"feature": exc.flag}, status_code=402)

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/brand/logo", tags=["meta"])
    async def brand_logo() -> FileResponse:
        # Custom branding is a licensed feature (ROADMAP.md §19) — 404s
        # rather than serving anything on an unlicensed instance or an
        # unconfigured (or missing-on-disk) path, same "cleanly absent,
        # never a crash" shape as every other gated feature.
        if not has_feature("branding") or not settings.brand_logo_path:
            raise HTTPException(status_code=404)
        path = Path(settings.brand_logo_path)
        if not path.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(path)

    return app


app = create_app()
