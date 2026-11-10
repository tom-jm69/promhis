# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`): breaking changes to the webhook/API contract or self-hosted config bump `MAJOR`, new backward-compatible features bump `MINOR`, fixes bump `PATCH`.

## [Unreleased]

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
