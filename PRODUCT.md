# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Python FastAPI backend, server-rendered Jinja2 templates (no SPA/build step), SQLModel over Postgres for storage.

## Users

Primary: a small SRE/ops team member checking the dashboard during or after an incident, or during on-call review — cross-referencing "what's firing" against other signals, sometimes at odd hours and under time pressure. Scanability and unambiguous firing/resolved signaling outrank decoration.

## Product Purpose

Promhis is the durable history layer Alertmanager itself doesn't provide. Alertmanager's own UI forgets resolved alerts quickly; Promhis receives Alertmanager's webhook deliveries, logs every status transition permanently, and gives operators a searchable record of what fired, where, and when — including full per-node drilldown (every alert a given node has ever thrown).

## Positioning

Not an Alertmanager replacement or a metrics/trend-analytics tool — it is the permanent record and per-node drilldown Alertmanager lacks. Scope is deliberately narrow: durable history + node-centric browsing, not pattern/flapping analysis (that was explicitly ruled out in favor of staying a reliable archive-with-drilldown).

## Operating Context

Runs as an internal, self-hosted service alongside Alertmanager, on infrastructure the ops team already controls. Alertmanager is configured with a `webhook_configs` receiver pointing at Promhis's ingest endpoint. Reachable beyond a fully trusted network/VPN boundary, so it needs its own login rather than relying solely on network placement.

## Capabilities and Constraints

- Ingests Alertmanager's standard webhook payload (`alerts[]` with labels/annotations/status/fingerprint/startsAt/endsAt) and appends every delivery to an immutable event log, plus maintains a current-state row per fingerprint.
- "Node" identity is derived from an alert's labels (checked in order: `node`, `instance`, `hostname` — configurable), since Alertmanager alerts don't have a first-class node field.
- Human-facing dashboard pages require login (session-based); the machine-facing webhook ingest endpoint is authenticated separately (HTTP Basic, matching Alertmanager's native `webhook_configs` basic-auth support) so Alertmanager doesn't need an interactive session.
- Single shared view — no multi-tenant/per-user scoping was requested; one login gate protects the whole dashboard.
- No build tooling: any client-side JS/CSS must run from CDN or static files Jinja2 serves directly.

## Evidence on Hand

None — greenfield build. No existing brand name beyond the repo's existing name "promhis," no existing screenshots, copy, or data to preserve.

## Product Principles

1. The firing/resolved state of anything must be legible at a glance, under stress, without reading labels closely.
2. History is the point — never destroy or hide past events in favor of only showing current state.
3. Node is a first-class navigation axis, not just a label value buried in a details panel.
4. Stay an archive with drilldown, not an analytics product — resist scope creep toward trend/ML features.
5. Zero client-side build step; every page must work as a server-rendered document plus CDN scripts.

## Accessibility & Inclusion

No specific standard was mandated; firing/resolved and severity signaling should not rely on color alone (pair with icon/shape/label) given the stress/low-attention usage context.
