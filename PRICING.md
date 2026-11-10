# Pricing

Open-core: one codebase, published on GitHub. The **Free** edition is everything that makes the product work — ingest, history, the dashboard, Postgres, the existing Stats page — unrestricted, forever. **Licensed** features are the ones that only start to matter once multiple people, teams, clusters, or compliance requirements are involved. See [`docs/licensing.md`](docs/licensing.md) for exactly how that split is enforced.

**Buyer-based split.** The test for "free or licensed" is who needs it: if a solo SRE or small team needs a capability to get real value out of Promhis, it stays free. If it only becomes necessary once there are 50+ users, multiple teams, or a regulated compliance requirement in the picture, it's a reasonable candidate for Licensed — because by then there's a buyer (a manager, a security team, a compliance officer) who isn't the engineer using the tool day to day. This is why ingest, history, search, and the Stats page (including flapping/noisy-alert detection) are permanently free — they're exactly what makes a solo on-call engineer's life better, and a crippled free tier gets no adoption.

| Edition | Price | Includes |
|---|---|---|
| **Free** | $0 (OSS) | Everything below except the licensed feature list. Unlimited events, unlimited retention, Postgres, the existing Stats page (current counts, recent activity, top firing alerts) — your infrastructure, your data. |
| **Licensed** | Contact us | Everything in Free, plus whichever licensed features your license's `features` list includes (see below) — one license can unlock any subset. |

Both editions are the same self-hosted deployment — run it yourself, on your own infrastructure, either way. There is no hosted/managed offering; Promhis does not run an instance for you.

## Hard rules

These are never true, regardless of license state:

- History depth, event count, and retention are never capped on the free tier.
- Webhook ingest, the backup poller, and the core dashboard are never gated.
- Baseline security (login, webhook auth, HTTPS guidance) is never paywalled.
- A missing, invalid, or expired license never blocks startup or ingest.

## Free features

| Area | Feature |
|---|---|
| Ingest | Alertmanager webhook ingest (`routers/webhook.py`) with HTTP Basic/Bearer auth |
| Ingest | Backup poller against `/api/v2/alerts` (`poller.py`) |
| History | Alert current state + `AlertEvent` append-only history, unlimited |
| History | Configurable retention pruning |
| Storage | Postgres (`asyncpg`) — free, uncapped, no tier gates it |
| Dashboard | All current pages: alerts, nodes, history, search, filters |
| Dashboard | The existing Stats page (current counts, recent activity, top firing alerts, MTTR, flapping detection, top-noisy-alerts) |
| Auth | Single local admin login (session cookie) |
| API | Read access to alerts, nodes, stats endpoints |
| API | One personal API token (Bearer) for the admin user, full read access |
| API | Paginated history over the API |
| Nodes | Node identity via `PROMHIS_NODE_LABELS` |

## Licensed features

Each has a feature flag key, used in the license file's `features` list and checked via `has_feature(flag)`/`require_feature(flag)` (`src/promhis/licensing.py`).

| Flag | Feature | Notes |
|---|---|---|
| `sso` | SAML SSO, SCIM user provisioning, group→role mapping | Not yet built. Deliberately scoped to avoid the "SSO tax": basic OIDC login is planned as a **free** auth option once SSO work starts at all — only the enterprise-identity pieces (SAML, SCIM, group-to-role mapping) are licensed. Local admin login keeps working alongside either as a break-glass account. |
| `rbac` | Multiple users, roles (admin/editor/viewer), team/namespace-scoped alert visibility | The free tier stays single-admin — this is what unlocks more than one admin account at all, via the Admin Users page (ROADMAP.md §21). Namespace/cluster-scoped team views are a planned extension of the same flag, not yet built. |
| `audit_log` | Log of logins, settings changes, exports, API token usage | A different thing from the existing, already-free webhook-ingest audit log (`/audit-log`, ROADMAP.md §5) — that one stays free and unrelated to this flag. |
| `multi_source` | Multiple Alertmanager sources aggregated into one history, with cross-source incident correlation/grouping | Not yet built. |
| `analytics` | A separate, deeper analytics page: SLA/SLO reports, MTTR trends and on-call load per team or person, longer-range trends beyond the free Stats page | The free Stats page (MTTR, flapping, top-noisy-alerts) is not what this gates — that's permanently free, see above and the buyer-based split note. Not yet built. |
| `reports` | Scheduled reports and digests (email, Slack), CSV/PDF export | Not yet built — distinct from the existing free CSV export on the Alerts page. |
| `annotations` | Notes and incident annotations on alert events, for postmortems | Distinct from the existing free per-alert acknowledgment note (ROADMAP.md §7), which stays free. |
| `service_tokens` | More than one API token, scoped (read/write, team-scoped), expiry, rotation | The free tier keeps exactly one personal admin token; this only raises the cap/adds scoping — see `routers/dashboard.py`'s `create_api_token_submit`. |
| `bulk_export` | Full-history dumps, streaming exports over arbitrary time ranges, plus connectors to BI/data-warehouse targets (Snowflake, BigQuery) | Not yet built — the free API's pagination is unaffected. |
| `archival` | Immutable/tamper-evident history storage, legal hold, tiered long-term archival to S3/GCS | Not yet built. Aimed at regulated customers who must prove what alerted and when, not at raising the free tier's retention cap — retention depth itself stays free and uncapped regardless of this flag. |
| `itsm` | ServiceNow / Jira Service Management integration: auto-ticketing and two-way sync | Not yet built. Distinct from the existing free outbound notification channels (Slack/Discord/Teams/PagerDuty/Opsgenie/webhook) — those stay free; this is ticketing-system sync specifically. |
| `ha` | High-availability / clustered deployment, multi-region | Not yet built. Still a single self-hosted deployment per customer — see "Not a hosted offering" below; this is about running that one deployment redundantly, not about Promhis hosting it for you. |
| `branding` | Custom instance name and logo in the navbar/page title (ROADMAP.md §19) | Not part of the reference feature list above — a promhis-specific addition, already built. |

API endpoints for a licensed feature are licensed through the same flag — there's no separate "API tier." No rate limiting in any tier.

## Not a hosted offering, not multi-tenant

Both editions are the same self-hosted deployment, and that's a deliberate, repeatedly-confirmed decision (see `ROADMAP.md`'s pivot note and "Explicit non-goals"), not an oversight to revisit lightly. Two ideas worth naming explicitly because they come up in general open-core/SaaS playbooks and don't apply here as currently scoped:

- **No hosted/managed SaaS tier.** An earlier pass of this project's planning considered a hosted offering and explicitly cancelled it. If that changes, it's a deliberate strategic call for the user to make, not something to quietly reintroduce via a pricing-table edit.
- **No multi-tenancy.** Every deployment is single-tenant, one organization's one instance, one database — including MSP/platform-team use (managing alerts for many downstream customers from one shared Promhis instance). `rbac`'s team-scoped views are about *roles within one org*, not tenant isolation between separate customers. Genuine multi-tenant support would be new product surface, not a flag on the existing model.

## License verification

Entirely offline — a signed license file (`PROMHIS_LICENSE_FILE`), verified against a public key baked into the app at startup and re-checked once a day thereafter. No phone-home, no license server, no new network dependency for a self-hosted install. See [`docs/licensing.md`](docs/licensing.md) for the file format, expiry/grace-period behavior, and how to install or issue one.

## Not yet enforced beyond the license check itself

There is no usage metering, no per-seat/per-volume billing, and no self-service purchase flow today — obtaining and renewing a license is a manual, out-of-band process (contact us), not a Stripe-backed checkout. This is a deliberate, disclosed scoping decision (see `ROADMAP.md`'s "Explicit non-goals" section), not an oversight.
