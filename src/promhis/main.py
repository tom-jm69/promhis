from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from promhis import crud
from promhis.auth import hash_password
from promhis.config import settings
from promhis.db import async_session_factory, init_db
from promhis.digest import run_digest_scheduler
from promhis.poller import run_poller
from promhis.routers import (
    admin_users,
    alerts,
    audit,
    dashboard,
    incident_notes,
    metrics,
    nodes,
    settings as settings_router,
    stats,
    webhook,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("promhis")

STATIC_DIR = Path(__file__).parent / "static"

RETENTION_INTERVAL_SECONDS = 24 * 60 * 60


async def _retention_loop() -> None:
    while True:
        await asyncio.sleep(RETENTION_INTERVAL_SECONDS)
        try:
            async with async_session_factory() as session:
                pruned = await crud.prune_old_events(session, retention_days=settings.retention_days)
                if pruned:
                    logger.info("retention: pruned %d old alert events", pruned)
                pruned_audit = await crud.prune_old_audit_entries(session, retention_days=settings.retention_days)
                if pruned_audit:
                    logger.info("retention: pruned %d old audit log entries", pruned_audit)
        except Exception:
            # Broad on purpose: a transient DB error here must not
            # permanently kill retention for the rest of the process's
            # life — log and try again next cycle (24h later).
            logger.exception("retention: prune pass failed")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    async with async_session_factory() as session:
        # Keeps the env-var admin identity working exactly as documented
        # today — an existing self-hosted install upgrading to this version
        # logs in exactly the same way it always has.
        await crud.sync_bootstrap_admin(
            session, username=settings.admin_user, password_hash=hash_password(settings.admin_password)
        )
    tasks = [asyncio.create_task(run_poller())]
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
    app.include_router(admin_users.router)
    app.include_router(incident_notes.router)

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/brand/logo", tags=["meta"])
    async def brand_logo() -> FileResponse:
        # 404s rather than serving anything when unconfigured or the
        # configured path is missing on disk — "cleanly absent, never a
        # crash", same shape as the rest of the dashboard's optional bits.
        if not settings.brand_logo_path:
            raise HTTPException(status_code=404)
        path = Path(settings.brand_logo_path)
        if not path.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(path)

    return app


app = create_app()
