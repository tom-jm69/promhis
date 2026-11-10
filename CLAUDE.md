# Promhis

Durable history + dashboard for Prometheus Alertmanager alerts. See `PRODUCT.md` (product intent) and `DESIGN.md` (dashboard visual system — "the Alertmanager console": dark navbar, flame-orange accent, flat Bootstrap-era chrome, deliberately mirroring the real Prometheus/Alertmanager UI) before making product or UI decisions; see `README.md` for setup/usage.

## Running things — Docker only

This project has no supported native/host run path. Never run `uv run promhis`, `uvicorn`, or start the dev server directly on the host.

- App: `docker compose up --build`
- Tests: `docker build --target test .` (fails the build if any test fails)
- Seed demo data: `docker compose exec promhis promhis-seed`

`basedpyright` (type checking) is the one exception — it's static analysis, not running the app, and is fine to run natively: `uv run basedpyright` (must stay at 0 errors; the whole codebase is typed this way on purpose).

## Architecture

- `src/promhis/models.py` — SQLModel tables. `Alert` is current state per fingerprint (upserted); `AlertEvent` is the append-only history log (one row per webhook delivery, never updated/deleted except by retention pruning). The history is the point — don't collapse these into one table.
- `src/promhis/crud.py` — all DB access, fully async.
- `src/promhis/db.py` — async SQLAlchemy engine/session (`asyncpg`; Postgres is the only supported backend).
- `src/promhis/schemas.py` — Pydantic: `AlertmanagerWebhook`/`AlertmanagerAlert` mirror Alertmanager's actual webhook payload shape; the rest are API response models.
- `src/promhis/auth.py` — two separate auth gates: `require_login`/`require_login_api` (session cookie, for humans) and `require_webhook_auth` (HTTP Basic, for Alertmanager itself — it can't do interactive login).
- `src/promhis/routers/` — `webhook.py` (ingest), `alerts.py`/`nodes.py`/`stats.py` (JSON API backing the dashboard), `dashboard.py` (server-rendered pages + login/logout).
- `src/promhis/templating.py` — Jinja2 setup + custom filters (`timeago`, `duration`, `durationpct`, `sevclass`).
- `src/promhis/poller.py` — optional backup sync against a live Alertmanager's `/api/v2/alerts`; the webhook is the primary ingest path, this is a bootstrap/backup, not a replacement.
- `src/promhis/main.py` — app factory, lifespan (DB init, poller task, retention pruning task).

## Conventions

- **Everything async.** DB access, routers, the poller — all `async def`/`await`. This was an explicit user requirement, not incidental.
- **Node identity** comes from alert labels, checked in order via `PROMHIS_NODE_LABELS` (default `node`, `instance`, `hostname`) — there's no first-class node field in Alertmanager's data model, `crud.extract_node` derives it.
- **basedpyright must stay clean** (`uv run basedpyright` → 0 errors). When SQLModel's class-level field access confuses the type checker (`.desc()`, `.ilike()`, `.is_not()` on a field used in a query), wrap it in `sqlmodel.col(...)` rather than ignoring the error.
- **No npm / no build step.** Frontend JS libs (htmx, Chart.js) are CDN `<script>` tags pinned with Subresource Integrity hashes in `templates/base.html` — generate a new hash (`openssl dgst -sha384 -binary <file> | openssl base64 -A`) if you ever bump a version, don't drop the `integrity` attribute.
- **Design system is locked in `DESIGN.md`** (Alertmanager-console world: dark navbar, Prometheus flame-orange as the single accent color, flat 1px-bordered Bootstrap-era components, system font stack, status/severity as solid-color labels never color-alone). This replaced an earlier bespoke "brass/walnut annunciator" direction — if you see that phrase anywhere (old comments, stale docs), it's describing a superseded design, not the current one. Read `DESIGN.md` before touching CSS/templates. The `impeccable` design-hook runs automatically on template/CSS edits; treat its findings seriously rather than suppressing them reflexively.
- **Single admin on Free, multi-user on `rbac` license.** `PROMHIS_ADMIN_USER`/`PROMHIS_ADMIN_PASSWORD` seed the one bootstrap `User` row (`crud.sync_bootstrap_admin`, kept in sync at every startup) that every self-hosted install still logs in with unchanged. A real `User` table/login flow now exists (ROADMAP.md §21, built on explicit user request) — Free stays hard-capped at that one admin; more require the `rbac` feature licensed (`PRICING.md`, `docs/licensing.md`). Don't add permissions/roles beyond "how many people can log in" without the user asking — that's explicitly out of scope for §21.
- **Licensing is `src/promhis/licensing.py`**, not a separate billing system — `has_feature(flag)`/`require_feature(flag)`, offline Ed25519-signed license files, no phone-home. See `PRICING.md`/`docs/licensing.md` for what's free vs. licensed. Core functionality (ingest, dashboard, Postgres, the existing Stats page, all notification channels including PagerDuty/Opsgenie) is never gated — only features that matter at team/org scale are.
