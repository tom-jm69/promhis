"""Daily digest email — opt-in, complements (doesn't replace) the instant
notification channels in `notifications/`. Off unless PROMHIS_DIGEST_TO is
set, in which case a once-a-day rollup of what fired/resolved is sent via
plain SMTP (stdlib `smtplib`, run off the event loop — it's blocking).
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from promhis import crud
from promhis.config import settings
from promhis.db import async_session_factory
from promhis.models import AlertEvent

logger = logging.getLogger("promhis.digest")


def build_digest(events: list[AlertEvent], *, window_hours: int) -> tuple[str, str]:
    """Returns (subject, plain-text body). Pure function — easy to test
    without touching the database or SMTP.
    """
    firing = [e for e in events if e.status == "firing"]
    resolved = [e for e in events if e.status == "resolved"]

    subject = f"Promhis daily digest — {len(firing)} firing, {len(resolved)} resolved (last {window_hours}h)"

    lines = [
        f"Promhis digest — last {window_hours} hours",
        f"{len(events)} total events, {len(firing)} firing, {len(resolved)} resolved.",
        "",
    ]

    if firing:
        lines.append(f"Firing ({len(firing)}):")
        for e in firing:
            node = f" on {e.node}" if e.node else ""
            lines.append(f"  - [{e.severity or 'none'}] {e.alertname}{node} (started {e.starts_at.isoformat()})")
        lines.append("")

    if resolved:
        lines.append(f"Resolved ({len(resolved)}):")
        for e in resolved:
            node = f" on {e.node}" if e.node else ""
            lines.append(f"  - {e.alertname}{node}")
        lines.append("")

    if not events:
        lines.append("No alert activity in this window.")

    if settings.public_base_url:
        lines.append(f"View the full history: {settings.public_base_url.rstrip('/')}/alerts")

    return subject, "\n".join(lines)


def _send_sync(subject: str, body: str) -> None:
    """The blocking part — isolated so `send_digest` can offload it with
    asyncio.to_thread and so tests can monkeypatch this one function.
    """
    assert settings.digest_to and settings.smtp_host
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = settings.digest_to
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as client:
        if settings.smtp_use_tls:
            client.starttls()
        if settings.smtp_user and settings.smtp_password:
            client.login(settings.smtp_user, settings.smtp_password)
        client.send_message(message)


async def send_digest(subject: str, body: str) -> None:
    await asyncio.to_thread(_send_sync, subject, body)


def seconds_until_next_run() -> float:
    now = datetime.now(timezone.utc)
    target = now.replace(hour=settings.digest_hour_utc, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def run_digest_scheduler() -> None:
    if not settings.digest_to or not settings.smtp_host:
        return
    while True:
        await asyncio.sleep(seconds_until_next_run())
        try:
            since = datetime.now(timezone.utc) - timedelta(hours=24)
            async with async_session_factory() as session:
                events = await crud.digest_events(session, since=since)
            subject, body = build_digest(events, window_hours=24)
            await send_digest(subject, body)
            logger.info("digest: sent to %s (%d events)", settings.digest_to, len(events))
        except (smtplib.SMTPException, OSError) as exc:
            logger.warning("digest: send failed: %s", exc)
