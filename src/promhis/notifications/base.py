"""The notification channel interface.

Every outbound integration (Slack, Discord, Teams, PagerDuty, Opsgenie, a
generic custom webhook) implements ``NotificationChannel``. Adding a new one
means one new module + one registry entry in ``registry.py`` — nothing in
the ingest path (``routers/webhook.py``) changes.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Protocol, TypedDict

import httpx

from promhis.config import settings
from promhis.metrics import NOTIFICATION_SENDS_TOTAL
from promhis.models import AlertEvent

logger = logging.getLogger("promhis.notifications")

# Normally `post_json` swallows every failure (see its own docstring) — a
# bad channel must never block ingest. The Integrations page's "send test
# notification" button is the one deliberate exception: a user clicking it
# wants to know immediately whether the credentials actually work, so it
# runs under `raise_send_errors()` to get the real failure back instead of a
# silently-swallowed log line. Never set outside that one route.
_raise_on_failure: ContextVar[bool] = ContextVar("raise_on_failure", default=False)


@contextmanager
def raise_send_errors() -> Iterator[None]:
    token = _raise_on_failure.set(True)
    try:
        yield
    finally:
        _raise_on_failure.reset(token)

# Shared across channels that color-code by severity (Discord embeds, Teams
# MessageCard themeColor) — same palette as the dashboard's DESIGN.md.
SEVERITY_COLOR_HEX = {
    "critical": "d9534f",
    "warning": "f0ad4e",
    "info": "5bc0de",
}


def severity_color(severity: str | None) -> str:
    return SEVERITY_COLOR_HEX.get((severity or "").lower(), "777777")


def alert_link(event: AlertEvent) -> str | None:
    """"View in Promhis" link, or None if PROMHIS_PUBLIC_BASE_URL isn't set."""
    if not settings.public_base_url:
        return None
    return f"{settings.public_base_url.rstrip('/')}/alerts/{event.fingerprint}"


def mask_secret(value: str) -> str:
    """For the Integrations page: a saved secret is never redisplayed in
    full, only enough of its tail to tell two credentials apart.
    """
    if not value:
        return ""
    tail = value[-4:] if len(value) > 4 else value
    return f"••••{tail}"


def summary_line(event: AlertEvent) -> str:
    node = f" on {event.node}" if event.node else ""
    summary = event.annotations.get("summary") if isinstance(event.annotations, dict) else None
    detail = f" — {summary}" if summary else ""
    return f"[{event.status.upper()}] {event.alertname}{node}{detail}"


class ChannelField(TypedDict):
    """One config field a channel needs, for the Integrations page's
    generically-rendered add/edit form — see routers/integrations.py.
    """

    name: str  # must match the channel class's __init__ keyword exactly
    label: str
    type: str  # "text" | "url"
    secret: bool  # masked after save, requires a new value to replace


class NotificationChannel(Protocol):
    """One outbound integration. `name` is the registry/config key and is
    used in logs when `send` fails. `display_name`/`fields`/`icon_svg` drive
    the Integrations page's UI — adding a new channel means a new module
    with these five class attributes + `send()`, plus one registry.py entry.
    """

    name: str
    display_name: str
    fields: list[ChannelField]
    icon_svg: str  # inline <svg>...</svg>, authored not emoji — see each channel module

    async def send(self, event: AlertEvent) -> None: ...


async def post_json(
    channel_name: str,
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
) -> None:
    """Shared "POST JSON, never raise" helper every channel calls.

    A channel's own failure (timeout, 4xx/5xx, DNS error — anything) is
    logged and swallowed here, never propagated. This is what makes a bad/
    slow channel unable to block ingest or another channel: the caller
    (``routers/webhook.py``) fans these out with
    ``asyncio.gather(..., return_exceptions=True)``, but this function
    already never raises, so that's a second layer of the same guarantee.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("notification channel %s failed: %s", channel_name, exc)
        NOTIFICATION_SENDS_TOTAL.labels(channel=channel_name, result="failure").inc()
        if _raise_on_failure.get():
            raise
        return
    NOTIFICATION_SENDS_TOTAL.labels(channel=channel_name, result="success").inc()
