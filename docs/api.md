# REST API

Promhis exposes two distinct JSON surfaces, built on two different auth models — don't confuse them:

1. **Ingest** (`POST /api/v1/webhook`) — what Alertmanager pushes to. See [`alertmanager-integration.md`](alertmanager-integration.md) for setup and [`security-and-auditing.md`](security-and-auditing.md) for its auth model.
2. **Read API** (`/api/v1/alerts`, `/nodes`, `/stats`, `/audit-log`) — what the dashboard itself calls, and what you can script against (e.g. pulling data into Grafana).

Full, always-current request/response schemas are at the live OpenAPI UI, `/docs` on any running instance (e.g. `http://localhost:8000/docs` for a local Compose setup) — this page is the auth model and payload-contract summary, not a field-by-field schema dump.

## Ingest: `POST /api/v1/webhook`

Accepts an Alertmanager `webhook_configs` payload — `AlertmanagerWebhook` in `src/promhis/schemas.py`, which mirrors [Alertmanager's own webhook payload shape](https://prometheus.io/docs/alerting/latest/configuration/#webhook_config) exactly:

```json
{
  "receiver": "promhis",
  "status": "firing",
  "groupKey": "...",
  "groupLabels": {},
  "commonLabels": {},
  "commonAnnotations": {},
  "alerts": [
    {
      "status": "firing",
      "labels": {"alertname": "HighCPULoad", "severity": "critical", "node": "web-01"},
      "annotations": {"summary": "CPU above 90%"},
      "startsAt": "2026-01-01T00:00:00Z",
      "endsAt": null,
      "generatorURL": "...",
      "fingerprint": "abc123"
    }
  ]
}
```

**Auth:** HTTP Basic or Bearer, selected by `PROMHIS_WEBHOOK_AUTH_MODE` — see [`security-and-auditing.md`](security-and-auditing.md#authentication). Every request, accepted or rejected, is recorded in the audit log.

**Response:** `{"ingested": <n>}` with the count of alerts processed, `200` on success. `401` on bad/missing credentials, `400` on a payload that doesn't validate.

## Read API: `/api/v1/*`

| Endpoint | Returns |
|---|---|
| `GET /api/v1/alerts` | Paginated, filterable alert list. Filters: `status`, `severity`, `node`, `alertname`, `search`, `group`; `sort` (e.g. `-last_seen`); `page`/`page_size` (max 200/page). |
| `GET /api/v1/alerts/{fingerprint}` | One alert's current state plus its full event history. `404` if the fingerprint is unknown. |
| `GET /api/v1/alerts/export.csv` | Same filters as the list endpoint, as a CSV download (capped at 50,000 rows). |
| `GET /api/v1/nodes` | Per-node summary (alert counts by status, last-seen). `sort` param. |
| `GET /api/v1/nodes/{node}/history` | Full event history for one node. |
| `GET /api/v1/stats` | Dashboard-wide summary counts (the overview page's numbers). |
| `GET /api/v1/audit-log` | Paginated webhook ingest audit log. Filter: `outcome` (`success`/`failure`/`missing`). |

### Auth

Two different dependencies, deliberately not unified:

- **`/alerts`, `/nodes`, `/stats`** — `require_login_or_api_token`: either the dashboard session cookie, or `Authorization: Bearer <token>` checked against a hashed, revocable **API token** created on the dashboard's API Tokens page (`/api-tokens`). This is the surface meant for scripting/external tooling (Grafana, etc.) — see the API Tokens note in `ROADMAP.md` §7 for the tier-gating story (published, not code-enforced).
- **`/audit-log`** — `require_login_api`: **session cookie only**, no API token fallback. Deliberately more restrictive — it's admin-facing data (source IPs, auth attempts against your ingest endpoint), not something to hand to a read-only integration token.

An API token that works against `/alerts` will get `401` against `/audit-log`; that's intentional, not a bug.

### Creating an API token

Dashboard → API Tokens → name it → the raw token is shown exactly once, at creation. It's stored only as a SHA-256 hash — if you lose it, revoke and create a new one. Use it as `Authorization: Bearer <token>`.

```bash
curl -H "Authorization: Bearer <token>" https://your-promhis/api/v1/stats
```
