"""Daily digest email — opt-in, complements (doesn't replace) the instant
notification channels in `notifications/`. Off unless digest_to is set
(env, or the Settings page when PROMHIS_DIGEST_TO is unset), in which case a
once-a-day rollup of what fired/resolved is sent via plain SMTP (stdlib
`smtplib`, run off the event loop — it's blocking).
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from sqlalchemy.ext.asyncio import AsyncSession

from promhis import crud
from promhis.config import settings
from promhis.db import async_session_factory
from promhis.models import AlertEvent
from promhis.runtime_settings import effective_bool, effective_int, effective_str

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


@dataclass(frozen=True)
class DigestConfig:
    to_addr: str
    hour_utc: int
    smtp_host: str
    smtp_port: int
    smtp_user: str | None
    smtp_password: str | None
    smtp_from: str
    smtp_use_tls: bool


async def effective_digest_config(session: AsyncSession) -> DigestConfig | None:
    """None means "not configured" — same meaning as the old
    `if not settings.digest_to or not settings.smtp_host` guard, just
    re-checked live instead of only at startup.
    """
    to_addr = await effective_str(session, key="digest_to", env_var="PROMHIS_DIGEST_TO", default=None)
    smtp_host = await effective_str(session, key="smtp_host", env_var="PROMHIS_SMTP_HOST", default=None)
    if not to_addr or not smtp_host:
        return None
    return DigestConfig(
        to_addr=to_addr,
        hour_utc=await effective_int(
            session, key="digest_hour_utc", env_var="PROMHIS_DIGEST_HOUR_UTC", default=settings.digest_hour_utc
        ),
        smtp_host=smtp_host,
        smtp_port=await effective_int(
            session, key="smtp_port", env_var="PROMHIS_SMTP_PORT", default=settings.smtp_port
        ),
        smtp_user=await effective_str(session, key="smtp_user", env_var="PROMHIS_SMTP_USER", default=None),
        smtp_password=await effective_str(
            session, key="smtp_password", env_var="PROMHIS_SMTP_PASSWORD", default=None
        ),
        smtp_from=await effective_str(session, key="smtp_from", env_var="PROMHIS_SMTP_FROM", default=settings.smtp_from)
        or settings.smtp_from,
        smtp_use_tls=await effective_bool(
            session, key="smtp_use_tls", env_var="PROMHIS_SMTP_USE_TLS", default=settings.smtp_use_tls
        ),
    )


def _send_sync(subject: str, body: str, config: DigestConfig) -> None:
    """The blocking part — isolated so `send_digest` can offload it with
    asyncio.to_thread and so tests can monkeypatch this one function.
    """
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.smtp_from
    message["To"] = config.to_addr
    message.set_content(body)

    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=10) as client:
        if config.smtp_use_tls:
            client.starttls()
        if config.smtp_user and config.smtp_password:
            client.login(config.smtp_user, config.smtp_password)
        client.send_message(message)


async def send_digest(subject: str, body: str, config: DigestConfig) -> None:
    await asyncio.to_thread(_send_sync, subject, body, config)


def seconds_until_next_run(hour_utc: int) -> float:
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def run_digest_scheduler() -> None:
    # Always runs (not gated on settings.digest_to/smtp_host at startup) so
    # that configuring it from the Settings page — when the matching env
    # vars are unset — takes effect without a restart, same as
    # db_dump_enabled/metrics_enabled.
    while True:
        async with async_session_factory() as session:
            hour_utc = await effective_int(
                session, key="digest_hour_utc", env_var="PROMHIS_DIGEST_HOUR_UTC", default=settings.digest_hour_utc
            )
        await asyncio.sleep(seconds_until_next_run(hour_utc))
        try:
            async with async_session_factory() as session:
                config = await effective_digest_config(session)
            if config is None:
                continue
            since = datetime.now(timezone.utc) - timedelta(hours=24)
            async with async_session_factory() as session:
                events = await crud.digest_events(session, since=since)
            subject, body = build_digest(events, window_hours=24)
            await send_digest(subject, body, config)
            logger.info("digest: sent to %s (%d events)", config.to_addr, len(events))
        except Exception:
            # Broad on purpose: an SMTP failure, a transient DB error while
            # building the digest, anything — this loop must never die
            # permanently from one bad night, since the next chance to send
            # is 24h away and a dead loop is otherwise silent until restart.
            logger.exception("digest: send failed")
