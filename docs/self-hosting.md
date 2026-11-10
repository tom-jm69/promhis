# Self-hosting

Promhis only runs in Docker — there's no supported native/host run path (even in development; see `CONTRIBUTING.md`). Two ways to run it: Docker Compose (below) for a single box, or the [Helm chart](#kubernetes-helm) for a cluster.

## Quickstart (Docker Compose)

```bash
git clone <this repo> && cd promhis
cp .env.example .env   # fill in PROMHIS_ADMIN_PASSWORD, PROMHIS_SESSION_SECRET, POSTGRES_PASSWORD
docker compose up --build
```

This also starts a bundled Postgres container (`docker-compose.yml`'s `postgres` service) — Promhis waits for it to report healthy before starting. The dashboard is then at `http://localhost:8000`, behind the login you set in `.env`. Data persists in a named Docker volume across restarts.

## Try it with a real Alertmanager

```bash
docker compose --profile demo up --build
```

This also starts a local Alertmanager wired up to Promhis via [`deploy/alertmanager.yml`](../deploy/alertmanager.yml) — edit that file's placeholder webhook password to match your `.env` first. See [`alertmanager-integration.md`](alertmanager-integration.md) for pointing a *real* (non-demo) Alertmanager at Promhis.

## Try it without any Alertmanager

```bash
docker compose exec promhis promhis-seed
```

Populates the dashboard with synthetic alert history so you can see it working before wiring up real infrastructure.

## Configuration

Every setting is an environment variable (`PROMHIS_*`) or a line in `.env`. See [`configuration.md`](configuration.md) for the full reference — at minimum, change `PROMHIS_ADMIN_PASSWORD` and `PROMHIS_SESSION_SECRET` from their insecure defaults before exposing this to anyone but yourself.

## Storage

Postgres (via `asyncpg`) is the only supported storage. `docker-compose.yml` bundles a `postgres:16-alpine` container by default; point `PROMHIS_DATABASE_URL` at your own instance instead if you'd rather not run it (comment out the `postgres` service too, then).

## Database dumps (optional)

Off by default — set `PROMHIS_DB_DUMP_ENABLED=true` (or toggle it from the **Settings** page) to have Promhis write a timestamped `pg_dump` `.sql` file to `PROMHIS_DB_DUMP_PATH` on a schedule. `docker-compose.yml` already mounts a named volume at the default path; the dump is skipped (not attempted) whenever free space there drops below `PROMHIS_DB_DUMP_MIN_FREE_MB`. See `configuration.md`.

## Upgrading

Pull the new image and `docker compose up --build` again — migrations, if any are ever needed, run automatically on startup (SQLModel's `create_all` today; there's no destructive schema migration path yet since the schema has only grown). If you're upgrading past the point outbound notification env vars were replaced by the Integrations page, see the migration note at the top of [`notifications.md`](notifications.md).

## Kubernetes (Helm)

See [`deploy/helm/promhis/README.md`](../deploy/helm/promhis/README.md) for the Helm chart — same image, run as a Deployment, with the same bundled-Postgres-by-default story as Compose above (an in-cluster Postgres container, or point it at your own).

## Development

All tooling runs in Docker too — see `CONTRIBUTING.md` for the type-check/test-suite commands and PR expectations.
