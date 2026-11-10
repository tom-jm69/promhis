# Promhis — Alarm Register

[![CI](https://github.com/tom-jm69/promhis/actions/workflows/ci.yml/badge.svg)](https://github.com/tom-jm69/promhis/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Docker Image](https://img.shields.io/badge/ghcr.io-promhis-blue?logo=docker)](https://github.com/tom-jm69/promhis/pkgs/container/promhis)

A durable history and dashboard for [Prometheus Alertmanager](https://prometheus.io/docs/alerting/latest/alertmanager/) alerts. Alertmanager itself forgets resolved alerts quickly; Promhis receives its webhook deliveries, logs every status transition permanently, and gives operators a searchable, per-node history of what fired, where, and when.

Free and open source ([`LICENSE`](LICENSE), MIT) to self-host, forever — every feature (ingest, history, the dashboard, Postgres, Stats, multiple admin users, custom branding, API tokens) is free and uncapped.

See [`PRODUCT.md`](PRODUCT.md) for the product's intent and [`DESIGN.md`](DESIGN.md) for the dashboard's visual system (the Alertmanager-console look — dark navbar, flame-orange accent, flat Bootstrap-era chrome).

## Stack

- **Backend:** FastAPI, fully async (async SQLAlchemy/SQLModel over `asyncpg`).
- **Frontend:** server-rendered Jinja2 templates, htmx for partial refresh/filtering, Chart.js for the overview charts — no build step, no npm.
- **Storage:** Postgres only (`docker-compose.yml` bundles one by default).

## Running it

This project only runs in Docker — there's no supported native/host run path.

```bash
cp .env.example .env   # fill in PROMHIS_ADMIN_PASSWORD, PROMHIS_SESSION_SECRET, POSTGRES_PASSWORD
docker compose up --build
```

The dashboard is then at `http://localhost:8000`, behind the login you set in `.env`. See [`docs/self-hosting.md`](docs/self-hosting.md) for the demo profile, seeding sample data, upgrading, and the [Helm chart](deploy/helm/promhis/README.md) for Kubernetes.

## Wiring up a real Alertmanager

Point an Alertmanager `webhook_configs` receiver at `POST /api/v1/webhook` — see [`docs/alertmanager-integration.md`](docs/alertmanager-integration.md) (and [`deploy/alertmanager.yml`](deploy/alertmanager.yml) for a worked example).

## Configuration

Every setting is an environment variable, prefixed `PROMHIS_`. Full reference: [`docs/configuration.md`](docs/configuration.md) (or `src/promhis/config.py` for the source of truth). At minimum, change `PROMHIS_ADMIN_PASSWORD` and `PROMHIS_SESSION_SECRET` from their insecure defaults.

## Development

All tooling runs in Docker too:

```bash
# Type check (basedpyright, strict on src/)
docker run --rm -v "$PWD":/app -w /app python:3.13-slim bash -c \
  "pip install -q uv && uv sync -q && uv run basedpyright"

# Test suite
docker build --target test .
```

See `CONTRIBUTING.md` for PR expectations.

## Docs

- [`docs/self-hosting.md`](docs/self-hosting.md) — Docker Compose quickstart, demo mode, seeding, upgrading.
- [`docs/alertmanager-integration.md`](docs/alertmanager-integration.md) — wiring up Alertmanager.
- [`docs/configuration.md`](docs/configuration.md) — full `PROMHIS_*` env var reference.
- [`docs/notifications.md`](docs/notifications.md) — outbound Slack/Discord/Teams/PagerDuty/Opsgenie/webhook forwarding.
- [`docs/security-and-auditing.md`](docs/security-and-auditing.md) — webhook auth schemes and the audit log.
- [`docs/api.md`](docs/api.md) — REST API reference; interactive docs at `/docs` on a running instance.

## Project

- [`website/index.html`](website/index.html) — the marketing site (open `website/index.html` directly in a browser, or serve the repo root as static files).
- [`LICENSE`](LICENSE) — MIT.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev setup, PR expectations.
- [`ROADMAP.md`](ROADMAP.md) — what's shipped and what's next.
