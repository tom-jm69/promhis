"""Optional background sync against a live Alertmanager instance.

This is a backup/bootstrap path, not the primary ingest mechanism — the
webhook push (``routers.webhook``) is. It exists for two cases the webhook
alone can't cover: alerts that were already firing before Promhis's webhook
receiver was wired up, and any webhook delivery Alertmanager couldn't
complete (receiver downtime, network blip).

Only runs when ``PROMHIS_ALERTMANAGER_URL`` is set.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from promhis import crud
from promhis.config import settings
from promhis.db import async_session_factory
from promhis.schemas import AlertmanagerAlert

logger = logging.getLogger("promhis.poller")


def _v2_status(state: str) -> str:
    # Alertmanager's v2 API carries a third state the webhook payload never
    # does: "suppressed" (silenced). Only this poll-backup path can see it —
    # document that limitation plainly rather than faking it on the primary
    # webhook path, which has no way to know.
    if state == "suppressed":
        return "silenced"
    return "firing" if state == "active" else "resolved"


def _v2_alert_to_webhook_alert(raw: dict) -> AlertmanagerAlert:
    state = (raw.get("status") or {}).get("state", "active")
    return AlertmanagerAlert(
        status=_v2_status(state),
        labels=raw.get("labels", {}),
        annotations=raw.get("annotations", {}),
        startsAt=raw["startsAt"],
        endsAt=raw.get("endsAt"),
        generatorURL=raw.get("generatorURL"),
        fingerprint=raw["fingerprint"],
    )


async def poll_once(client: httpx.AsyncClient) -> int:
    assert settings.alertmanager_url
    response = await client.get(f"{settings.alertmanager_url.rstrip('/')}/api/v2/alerts")
    response.raise_for_status()
    raw_alerts = response.json()

    async with async_session_factory() as session:
        for raw in raw_alerts:
            alert = _v2_alert_to_webhook_alert(raw)
            await crud.ingest_alert(session, alert, receiver="alertmanager-poll")
        await session.commit()
    return len(raw_alerts)


async def run_poller() -> None:
    if not settings.alertmanager_url:
        return
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                count = await poll_once(client)
                logger.info("alertmanager poll: synced %d alerts", count)
            except (httpx.HTTPError, KeyError) as exc:
                logger.warning("alertmanager poll failed: %s", exc)
            await asyncio.sleep(settings.alertmanager_poll_seconds)
