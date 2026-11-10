# Licensing: Free vs. Licensed features

Promhis is open-core: one codebase, published on GitHub. The **Free** edition is everything that makes the product work — ingest, history, the dashboard, Postgres, the existing Stats page — unrestricted, forever. **Licensed** features are the ones that only start to matter once multiple people, teams, clusters, or compliance requirements are involved. It's the same image either way, unlocked by a signed license file — not a separate build, not a hosted/cloud offering. See `PRICING.md` for the full free/licensed feature tables.

## Principle

Charge for what organizations need, not for what makes the product work. Durable alert history is the product — it is free and uncapped. Hard rules, true regardless of license state:

- History depth, event count, and retention are never capped on the free tier.
- Webhook ingest, the backup poller, and the core dashboard are never gated.
- Baseline security (login, webhook auth, HTTPS guidance) is never paywalled.
- A missing, invalid, or expired license never blocks startup or ingest.

## What's licensed today, and what "gated" looks like concretely

Of the feature flags listed in `PRICING.md`, only three have actual code behind them so far:

- **`service_tokens`** (more than one API token, scoped/rotatable). The free tier already includes **one** personal read-only API token per admin, full read access — that's not gated at all. Creating a *second* active token (`POST /api-tokens`) returns `402` with `PRICING.md`'s guidance unless `service_tokens` is licensed; revoking a token frees the slot back up. The `/api-tokens` page itself is never locked — it always shows the normal create/list UI, just with the limit message swapped in for the create form once you're at the free cap.
- **`branding`** (custom instance name/logo, ROADMAP.md §19 — not part of the reference spec `PRICING.md`'s table is otherwise based on, a promhis-specific addition). Falls back to the stock flame mark/"Promhis" wordmark and page title on an unlicensed instance, even if `PROMHIS_BRAND_NAME`/`PROMHIS_BRAND_LOGO_PATH` are set — never a broken image, never a half-applied brand.
- **`rbac`** (multiple admin users). The `User` table, login flow, and Admin Users management page exist (ROADMAP.md §21/§22) — the free tier is single-admin (the bootstrap account mirrored from `PROMHIS_ADMIN_USER`/`PROMHIS_ADMIN_PASSWORD`); creating a second admin requires this flag.
- **`annotations`** (postmortem incident notes on an alert, ROADMAP.md §23). An "Incident Notes" panel on the alert detail page — distinct from the free per-alert acknowledgment note (ROADMAP.md §7, a single overwritable "someone's looking at this" flag) and from Alertmanager's own read-only `annotations` payload dict shown in its own panel on the same page. Notes are append-only (no edit, only delete) once created. **Creating** a note requires `has_feature("annotations")`; an unlicensed instance shows the normal history plus a locked create-form message instead. **Viewing and deleting already-existing notes are never gated** — consistent with this doc's own "existing data stays viewable" expiry rule, and deletion is cleanup rather than the licensed capability itself (same reasoning as API tokens: revoking is always free, only creating a *second* one is gated).

Everything else in the licensed-feature table (`sso`, `audit_log`, `multi_source`, `analytics`, `reports`, `bulk_export`) is not built yet — the flags are reserved names for when they are, not current gates. **PagerDuty/Opsgenie forwarding is free** — an earlier pass of this repo gated it, then reverted that (ROADMAP.md §22): gating "the product working" isn't the model this charges on.

A gated feature is cleanly hidden/disabled when unlicensed, never a crash and never a silent no-op — that's the `has_feature(flag)`/`require_feature(flag)` contract (see below).

## Expiry behavior

- **14-day grace period** after `expires_at`: everything keeps working — `has_feature()` returns the same as a fully active license — with an admin-facing banner (not yet built; the state machine supports it).
- **After grace**, licensed features go read-only rather than disappearing: existing data (once `annotations`/`reports`/`audit_log` exist) stays viewable, creating new ones is disabled. `sso` keeps working for already-authenticated users (locking people out of an alerting tool is unacceptable) — only creating new SSO config is disabled, and local admin login always works regardless. `service_tokens` already created keep working until their own expiry; creating new ones is disabled, same as the free-tier cap being back in force.
- A license is verified once at startup and re-verified once a day thereafter (`main.py`'s `_license_recheck_loop`) — a license crossing from active into grace or expired is caught without a restart.

## Renewal and revocation

There's no phone-home, so there's no live revocation — the license file itself is the only thing the app ever checks, fully offline, same as how Checkmk's air-gapped mode verifies a downloaded license with no network access from the monitored instance. The way to make a license non-perpetual (and get a real point where you can cut someone off) is the same lever already in the file format: issue with a real `--expires-days` cycle instead of omitting it.

- Issue licenses for a subscription period (e.g. `--expires-days 90` or `--expires-days 365`), not perpetual, unless the customer actually bought a perpetual license.
- Each cycle, the customer gets a fresh signed file from you out-of-band (email, a portal, however you distribute it) and drops it in at `PROMHIS_LICENSE_FILE`. The instance's network access is never involved — only the human renewal step is "online."
- To revoke, just don't issue a new file next cycle. The old one runs out `expires_at` → 14-day `GRACE` → `EXPIRED`, same state machine as any other expiry (see "Expiry behavior" above).
- No usage/telemetry reporting is part of this — the instance never reports back anything (not service counts, not user counts, nothing). Renewal is a trust/billing relationship between you and the customer, not something the app enforces or observes.

## Installing a license

1. Obtain a `.json` license file (contact your vendor — there's no self-service purchase flow today, see `PRICING.md`).
2. Set `PROMHIS_LICENSE_FILE=/path/to/your-license.json` (or the equivalent line in `.env`).
3. Restart Promhis, or wait up to a day for the daily recheck to pick it up — the first verification still happens at startup, so a restart is the fast path.

## How verification works

Entirely offline — no phone-home, no license server, no new network dependency for a self-hosted install:

- A license file is a small JSON envelope: a base64-encoded JSON payload (`customer`, `issued_at`, `expires_at`, `features`, `max_users`) plus a base64-encoded Ed25519 signature over the raw payload bytes.
- `src/promhis/licensing.py` verifies that signature against a public key embedded in the app. An invalid signature, a missing/unreadable file, or an unparseable payload all resolve to `LicenseState.FREE`, cleanly — never an error page, never a crashed startup.
- `expires_at` can be `null` for a perpetual license. `features` is the list of flag keys this license unlocks (`has_feature(flag)` checks membership). `max_users` is optional and not yet enforced anywhere (reserved for `rbac`'s eventual per-license user cap).

## Gating API (`src/promhis/licensing.py`)

- `LicenseState` — `FREE` / `ACTIVE` / `GRACE` / `EXPIRED`.
- `has_feature(flag: str) -> bool` — `True` for `ACTIVE` and `GRACE` states when `flag` is in the license's `features` list; `False` for `FREE` and `EXPIRED`.
- `require_feature(flag: str)` — a FastAPI dependency; raises `FeatureRequiredError`, caught by an app-wide exception handler (`main.py`) that renders a JSON `402` for `/api/*` routes or the `upgrade_required.html` page for dashboard routes. Not yet used by any route — the gates built so far (`service_tokens`, `branding`) check `has_feature()` inline instead, since their degraded states (a limit message, a stock logo) are more specific than a generic upgrade page.
- Templates get `has_feature` as a Jinja global (`templating.py`), so the UI can conditionally show/hide nav items or badges.

## `require_token_or_login` (`src/promhis/auth.py`)

The read-only `/api/v1/{alerts,nodes,stats}` routes accept either the dashboard session cookie or a Bearer API token — this dependency itself never checks licensing. What a token can reach is decided by the token's own type/scope (not built yet beyond "one free personal token"), not by this endpoint-level check.

## Issuing a license (for the vendor, not self-hosters)

`promhis-license` is a standalone offline tool — it's not part of the running app (not shipped in the production image), and self-hosters never need it:

```bash
# Once, to create your signing keypair (do this once, keep the private key safe):
promhis-license keygen --private-out signing-key.txt
# -> paste the printed public key into src/promhis/licensing.py's PUBLIC_KEY_B64

# Per customer, to issue a license:
promhis-license issue --customer "Acme Corp" --private-key signing-key.txt \
  --expires-days 365 --features service_tokens branding --out acme-license.json
# Omit --expires-days for a perpetual license; omit --features for a license
# that doesn't unlock anything yet (reserved for future features).
```

The private key must never be committed to the repository or shipped in the Docker image — anyone who has it can mint a license this app accepts. The repository ships with a **development** keypair (clearly marked as such in `licensing.py`) purely so tests and local experimentation work without needing a real key; replace `PUBLIC_KEY_B64` with your own before issuing any license you intend to actually sell.
