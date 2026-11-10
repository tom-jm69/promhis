"""Application settings, loaded from environment variables / .env file."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    node_labels: tuple[str, ...] = ("node", "instance", "hostname")

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
    metrics_allowed_ips: tuple[str, ...] = ()

    # Path to a signed license file (see src/promhis/licensing.py,
    # docs/licensing.md). Unset or invalid means the Free tier — every
    # licensed feature is cleanly hidden/disabled, nothing else changes.
    license_file: str | None = None

    # Custom branding (requires the `branding` feature licensed, see
    # ROADMAP.md §19) — replaces the flame-mark + "Promhis" wordmark in the
    # navbar/page title. Ignored entirely on an unlicensed instance; unset
    # on a licensed one falls back to the same defaults.
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


settings = Settings()
