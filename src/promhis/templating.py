from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from promhis.config import settings

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def brand_name() -> str:
    return settings.brand_name or "Promhis"


def brand_logo_url() -> str | None:
    return "/brand/logo" if settings.brand_logo_path else None


def timeago(value: datetime | None) -> str:
    if value is None:
        return "—"
    now = datetime.now(timezone.utc)
    dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    years = months // 12
    return f"{years}y ago"


def seconds_to_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h {minutes % 60}m"
    days = hours // 24
    return f"{days}d {hours % 24}h"


def duration(start: datetime, end: datetime | None) -> str:
    stop = end or datetime.now(timezone.utc)
    start_aware = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
    stop_aware = stop if stop.tzinfo else stop.replace(tzinfo=timezone.utc)
    return seconds_to_duration((stop_aware - start_aware).total_seconds())


def duration_pct(start: datetime, end: datetime | None, *, reference_days: float = 7.0) -> int:
    """Log-scaled bar width (0-100) for drawing duration as a measured length.

    Linear scaling would make anything under an hour invisible next to a
    multi-day outage; log scaling keeps short and long durations both legible
    on the same bar, which is the point of the duration-as-length signature.
    """
    stop = end or datetime.now(timezone.utc)
    start_aware = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
    stop_aware = stop if stop.tzinfo else stop.replace(tzinfo=timezone.utc)
    seconds = max(0.0, (stop_aware - start_aware).total_seconds())
    reference_seconds = reference_days * 86400
    pct = math.log10(seconds + 1) / math.log10(reference_seconds + 1) * 100
    return max(4, min(100, round(pct)))


def severity_class(severity: str | None) -> str:
    key = (severity or "none").lower()
    if key in {"critical", "page", "disaster"}:
        return "sev-critical"
    if key in {"warning", "warn", "degraded"}:
        return "sev-warning"
    if key in {"info", "informational", "notice"}:
        return "sev-info"
    return "sev-none"


def script_json(value: Any) -> Markup:
    """Serialize `value` for embedding inside a `<script>` tag.

    Plain `json.dumps` doesn't escape `<`/`>`/`&`, so attacker-controlled
    strings (e.g. an alert's `severity` label) containing `</script>` would
    otherwise break out of the tag and execute as markup.
    """
    return Markup(
        json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    )


templates.env.filters["timeago"] = timeago
templates.env.filters["duration"] = duration
templates.env.filters["secondsduration"] = seconds_to_duration
templates.env.filters["durationpct"] = duration_pct
templates.env.filters["sevclass"] = severity_class
templates.env.filters["scriptjson"] = script_json
templates.env.globals["brand_name"] = brand_name
templates.env.globals["brand_logo_url"] = brand_logo_url
