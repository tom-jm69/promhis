"""Application settings, loaded from environment variables / .env file."""

from __future__ import annotations

from typing import Annotated

from pydantic import BeforeValidator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _split_csv(value: object) -> object:
    """pydantic-settings treats a tuple-typed field as "complex" and tries
    to JSON-decode its raw env-var string by default — a plain
    comma-separated value like "a,b,c" isn't valid JSON, so without this
    every one of these fields would crash `Settings()` at import time the
    moment its env var was actually set (silently never caught by tests,
    since nothing here exercises the real env-parsing path — see git
    history). `NoDecode` below turns off that JSON-decode attempt; this
    does the actual comma-splitting instead.
    """
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    return value


CommaSeparatedTuple = Annotated[tuple[str, ...], NoDecode, BeforeValidator(_split_csv)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROMHIS_", env_file=".env", extra="ignore")

    app_title: str = "Promhis — Alertmanager History"
    # Matches docker-compose.yml's bundled `postgres` service for local/dev
    # use; set a real PROMHIS_DATABASE_URL for anything else.
    database_url: str = "postgresql+asyncpg://promhis:promhis@localhost:5432/promhis"

    host: str = "0.0.0.0"
    port: int = 8000

    # How many days of alert events to keep. 0 disables pruning.
    retention_days: int = 90

    # Optional: label used to identify the "node" an alert belongs to.
    # Falls back through this list, in order, until one is present.
    node_labels: CommaSeparatedTuple = ("node", "instance", "hostname")

    # Optional background sync against a live Alertmanager instance, used
    # as a backup/bootstrap to the webhook push (e.g. to pick up alerts
    # that fired before the webhook receiver existed, or if a push is lost).
    alertmanager_url: str | None = None
    alertmanager_poll_seconds: int = 60

    # Dashboard login (session cookie) and webhook ingest (HTTP Basic) share
    # these single-user credentials — this is an internal tool, not multi-user.
    admin_user: str = "admin"
    admin_password: str = "promhis"
    session_secret: str = "insecure-dev-secret-change-me"

    # Webhook ingest auth scheme: "basic" (default, matches admin_user/
    # admin_password above) or "bearer" (a single rotatable token instead).
    webhook_auth_mode: str = "basic"
    webhook_token: str | None = None

    # Trust X-Forwarded-For/X-Forwarded-Proto from whatever's in front of this
    # process. Only turn this on when there genuinely is a trusted reverse
    # proxy/load balancer in front of Promhis — otherwise any client can
    # spoof its own source IP, which matters once that IP is what the audit
    # log records.
    trust_proxy: bool = False

    # Optional auth for GET /metrics (the Prometheus scrape endpoint),
    # independent of the dashboard session cookie and the webhook's own
    # Basic/Bearer scheme. Both are opt-in and independently configurable;
    # unset/empty (the default) leaves /metrics open, same posture as
    # /healthz, for existing deployments already scraping it with no
    # credentials. IP entries are plain IPs or CIDRs, comma-separated, and
    # are checked against `request.client.host` — honors PROMHIS_TRUST_PROXY
    # exactly like the webhook audit log's source_ip (ProxyHeadersMiddleware
    # rewrites that value from X-Forwarded-For when trust_proxy is on).
    metrics_enabled: bool = True
    metrics_user: str | None = None
    metrics_password: str | None = None
    metrics_allowed_ips: CommaSeparatedTuple = ()

    # Custom branding — replaces the flame-mark + "Promhis" wordmark in the
    # navbar/page title. Unset falls back to the stock defaults.
    brand_name: str = "Promhis"
    brand_logo_path: str | None = None

    # Absolute base URL this instance is reachable at (e.g.
    # "https://promhis.example.com"), used only to build "view in Promhis"
    # links in outbound notifications below. Links are omitted when unset.
    public_base_url: str | None = None

    # Outbound notification forwarding (see src/promhis/notifications/) is
    # configured through the dashboard's Integrations page, backed by the
    # NotificationIntegration table — not env vars. See docs/notifications.md.

    # Daily digest email — opt-in, complements (doesn't replace) the instant
    # channels above. Off unless digest_to is set.
    digest_to: str | None = None
    digest_hour_utc: int = 8  # which hour, UTC, to send the daily rollup
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "promhis@localhost"
    smtp_use_tls: bool = True

    # Scheduled Postgres dumps (pg_dump), off by default. "Enabled" can also
    # be flipped at runtime from the Settings page when PROMHIS_DB_DUMP_ENABLED
    # is unset (see auth.effective_db_dump_enabled) — path and interval are
    # env-only, same as every other filesystem/scheduling knob here. Writes a
    # timestamped .sql file to db_dump_path; that directory needs to be a
    # mounted volume for dumps to outlive the container.
    db_dump_enabled: bool = False
    db_dump_path: str = "/var/lib/promhis/dumps"
    db_dump_interval_hours: int = 24
    # Skip a scheduled dump entirely (not even start pg_dump) rather than
    # risk writing a truncated file or filling the volume the rest of the
    # app needs — see db_dump.py.
    db_dump_min_free_mb: int = 500


settings = Settings()
