# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`): breaking changes to the webhook/API contract or self-hosted config bump `MAJOR`, new backward-compatible features bump `MINOR`, fixes bump `PATCH`.

## [Unreleased]

### Added

- Optional scheduled database dumps (`pg_dump`), off by default — `PROMHIS_DB_DUMP_ENABLED`/`_PATH`/`_INTERVAL_HOURS`/`_MIN_FREE_MB`, also toggleable from the Settings page. A dump is skipped entirely (never started) if free disk space is below the configured floor.
- Every daily-digest/SMTP setting (recipient, send hour, host/port/user/password/from/TLS) and the remaining database-dump settings (path, interval, minimum free space) are now also editable from the Settings page, not just env vars — same env-wins rule as `/metrics`.
- `PROMHIS_DIGEST_TO` accepts multiple comma-separated recipient addresses.
- An explicit `PROMHIS_DIGEST_ENABLED` toggle (also on the Settings page) for the daily digest, independent of whether a recipient/SMTP host happen to be set — defaults to on, so existing setups are unaffected.
- The Settings page now hides a feature's detailed configuration fields (database dump, daily digest/SMTP) until its toggle is switched on.

### Changed

- Multiple admin users, custom branding, and incident notes are now free and uncapped for everyone (no longer require a license).

### Fixed

- `PROMHIS_NODE_LABELS` and `PROMHIS_METRICS_ALLOWED_IPS` crashed the whole app at startup if actually set — both are documented as comma-separated values, but pydantic-settings tried to JSON-decode them. Fixed.

### Removed

- The signed-license feature-gating system (`src/promhis/licensing.py`, `src/promhis/ee/`, `PRICING.md`, `docs/licensing.md`). This project is fully FOSS (MIT) for now; a licensing model may return later based on real user interest.

## [0.1.0] - 2026-11-10

Initial release.

### Added

- Webhook ingest from Alertmanager, with a durable, append-only event log (`Alert` current state + `AlertEvent` history) backed by Postgres.
- Dashboard: Overview, Alerts register, Nodes, Statistics/Insights, Audit Log.
- Per-node alert history and drilldown.
- Outbound notification forwarding (Slack, Discord, Microsoft Teams, PagerDuty, Opsgenie, generic webhook) configured through the dashboard, with label-based routing rules.
- Ingest authentication (Basic/bearer) and an audit log of webhook deliveries.
- API tokens for scripted access to the JSON API.
- Lightweight per-alert acknowledgment notes and incident annotations.
- Daily digest email (opt-in).
- Admin user management (multiple admin accounts) with a licensed `rbac` tier; custom branding (name/logo).
- Offline, signed-license feature gating (`src/promhis/licensing.py`) — core ingest/dashboard/Postgres/Stats are always free and uncapped.
- Dashboard-wide htmx interactions (no full-page reloads for filtering/sorting/pagination/forms).
- Docker Compose deployment and a Helm chart for Kubernetes.
- Marketing website (`website/`).

[Unreleased]: https://github.com/tom-jm69/promhis/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/tom-jm69/promhis/releases/tag/v0.1.0
