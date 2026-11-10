# Configuration reference

All settings are environment variables prefixed `PROMHIS_` (or a `.env` file in the working directory — see `.env.example`). This is the full list; `src/promhis/config.py` is the source of truth if this page and the code ever disagree.

## Core

| Variable | Default | Notes |
|---|---|---|
| `PROMHIS_APP_TITLE` | `Promhis — Alertmanager History` | Shown in the dashboard's title bar/header. |
| `PROMHIS_DATABASE_URL` | `postgresql+asyncpg://promhis:promhis@localhost:5432/promhis` | SQLAlchemy async URL. Postgres is the only supported backend — `docker-compose.yml` sets this to point at its bundled `postgres` service; the Python-level default above is a local-dev fallback only. |
| `PROMHIS_HOST` / `PROMHIS_PORT` | `0.0.0.0` / `8000` | What uvicorn binds to. |
| `PROMHIS_RETENTION_DAYS` | `90` | How long alert history events and audit log entries are kept. `0` disables pruning entirely. |
| `PROMHIS_NODE_LABELS` | `node,instance,hostname` | Ordered, comma-separated label names checked (in order) to derive an alert's "node" — there's no first-class node field in Alertmanager's data model. First match wins. |

## Backup poller (optional)

A supplement to the webhook push, not a replacement — see `alertmanager-integration.md` for why the webhook is primary.

| Variable | Default | Notes |
|---|---|---|
| `PROMHIS_ALERTMANAGER_URL` | unset | Base URL of a live Alertmanager to poll (`/api/v2/alerts`). Poller is disabled entirely when unset. |
| `PROMHIS_ALERTMANAGER_POLL_SECONDS` | `60` | Poll interval, only relevant when the above is set. |

## Dashboard login & webhook auth

Single shared login — see this project's own `CLAUDE.md`/`CONTRIBUTING.md` for why there's deliberately no multi-user model.

| Variable | Default | Notes |
|---|---|---|
| `PROMHIS_ADMIN_USER` | `admin` | Dashboard session login username, and the Basic-auth username Alertmanager's webhook uses by default. |
| `PROMHIS_ADMIN_PASSWORD` | `promhis` | **Change this in any real deployment.** Shared by dashboard login and webhook Basic auth. |
| `PROMHIS_SESSION_SECRET` | `insecure-dev-secret-change-me` | Signs the dashboard session cookie. **Change this in any real deployment** — generate with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`. |
| `PROMHIS_WEBHOOK_AUTH_MODE` | `basic` | `basic` (uses the admin credentials above) or `bearer` (a single rotatable token, see below). Full comparison in `security-and-auditing.md`. |
| `PROMHIS_WEBHOOK_TOKEN` | unset | Required when `webhook_auth_mode=bearer`; ignored otherwise. |

## Metrics endpoint (`/metrics`)

Open by default, same posture as `/healthz`. Set either or both of the below to restrict it — neither is required, and they're independent of the dashboard login/webhook auth above.

| Variable | Default | Notes |
|---|---|---|
| `PROMHIS_METRICS_ENABLED` | `true` | Set `false` to disable `/metrics` entirely — returns a plain 404, same "cleanly absent" posture as any other disabled feature, not an auth error. |
| `PROMHIS_METRICS_ALLOWED_IPS` | unset | Comma-separated IPs/CIDRs allowed to reach `/metrics` (e.g. `10.0.0.0/8,127.0.0.1`). Checked against the request's client IP — honors `PROMHIS_TRUST_PROXY` the same way the audit log's `source_ip` does. |
| `PROMHIS_METRICS_USER` / `PROMHIS_METRICS_PASSWORD` | unset | HTTP Basic credentials required to scrape `/metrics`, checked only when **both** are set. Point Prometheus's `scrape_configs` `basic_auth` at these. |

All four of the above can also be set at runtime from the dashboard's **Settings** page (gear icon, `/settings`) instead of `.env` — useful when you'd rather not restart the container to change them. Whichever env var is set always wins: the matching Settings field is shown read-only in that case, so `.env` can never be silently overridden by something set in the UI.

## Networking / proxy

| Variable | Default | Notes |
|---|---|---|
| `PROMHIS_TRUST_PROXY` | `false` | Honor `X-Forwarded-For`/`X-Forwarded-Proto` from whatever's in front of this process. Only set `true` behind a real reverse proxy/load balancer you trust — otherwise any client can spoof the source IP the audit log records. See `security-and-auditing.md`. |
| `PROMHIS_PUBLIC_BASE_URL` | unset | This instance's public URL (e.g. `https://promhis.example.com`). Used only to build "view in Promhis" links in outbound notifications; omitted entirely when unset. |

## Outbound notifications

Slack/Discord/Teams/PagerDuty/Opsgenie/custom-webhook forwarding is configured in-app on the dashboard's **Integrations** page (`/integrations`), not via environment variables — see `notifications.md`, including the migration note for anyone upgrading from a version that used the old `PROMHIS_*_WEBHOOK_URL`-style env vars.

## Daily digest email (optional)

Opt-in — off entirely unless both `digest_to` and `smtp_host` are set. Complements, rather than replaces, the instant channels above.

| Variable | Default | Notes |
|---|---|---|
| `PROMHIS_DIGEST_TO` | unset | Recipient address. Setting this (and `smtp_host`) is what turns the digest on at all. |
| `PROMHIS_DIGEST_HOUR_UTC` | `8` | Hour (UTC) the daily rollup is sent. |
| `PROMHIS_SMTP_HOST` | unset | SMTP server hostname. |
| `PROMHIS_SMTP_PORT` | `587` | SMTP server port. |
| `PROMHIS_SMTP_USER` / `PROMHIS_SMTP_PASSWORD` | unset | SMTP auth, if your server requires it. |
| `PROMHIS_SMTP_FROM` | `promhis@localhost` | `From:` address on the digest email. |
| `PROMHIS_SMTP_USE_TLS` | `true` | STARTTLS on connect. |

## Branding

| Variable | Default | Notes |
|---|---|---|
| `PROMHIS_BRAND_NAME` | `Promhis` | Custom instance name shown in the navbar and page `<title>`. |
| `PROMHIS_BRAND_LOGO_PATH` | unset | Path to a logo image file (mounted into the container) served at `/brand/logo` and shown in the navbar in place of the flame mark. |

## Database dump (optional)

Off by default. Writes a timestamped `pg_dump` `.sql` file on a schedule — a plain Postgres backup, restorable with `psql`/`pg_restore` independent of Promhis itself.

| Variable | Default | Notes |
|---|---|---|
| `PROMHIS_DB_DUMP_ENABLED` | `false` | Also toggleable at runtime from the **Settings** page when this env var is unset — same env-wins pattern as the `/metrics` settings above. |
| `PROMHIS_DB_DUMP_PATH` | `/var/lib/promhis/dumps` | Directory dumps are written into. **Needs to be a mounted volume** — `docker-compose.yml` already mounts one at this default path; otherwise dumps live on the container's ephemeral filesystem and vanish on restart. |
| `PROMHIS_DB_DUMP_INTERVAL_HOURS` | `24` | How often to dump. |
| `PROMHIS_DB_DUMP_MIN_FREE_MB` | `500` | Safety floor: a dump is skipped entirely (pg_dump is never even started) whenever free space at `db_dump_path` is below this — never risk writing a truncated backup or filling the volume. |

## See also

- `security-and-auditing.md` — the webhook auth schemes and audit log in detail.
- `notifications.md` — configuring outbound channels via the Integrations page.
