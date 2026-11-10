# Ingest authentication and the audit log

Promhis does not blindly accept alerts. Every request to the webhook ingest endpoint — accepted or rejected — is authenticated and recorded.

## Authentication

`POST /api/v1/webhook` requires one of two schemes, selected by `PROMHIS_WEBHOOK_AUTH_MODE` (default `basic`):

### Basic (default)

Matches `PROMHIS_ADMIN_USER`/`PROMHIS_ADMIN_PASSWORD` — the same credentials as the dashboard login. Set it on the Alertmanager side with:

```yaml
http_config:
  basic_auth:
    username: admin
    password: change-me
```

### Bearer

A single rotatable token instead of a username/password pair. Set `PROMHIS_WEBHOOK_AUTH_MODE=bearer` and `PROMHIS_WEBHOOK_TOKEN=<a long random value>` on the Promhis side, and on the Alertmanager side:

```yaml
http_config:
  authorization:
    credentials: <the same token>
```

Only one scheme is active at a time — whichever `PROMHIS_WEBHOOK_AUTH_MODE` names. See [`deploy/alertmanager.yml`](../deploy/alertmanager.yml) for both, side by side.

Both schemes compare credentials with a constant-time comparison (`hmac.compare_digest`), not `==`, to avoid timing attacks.

## The audit log

Every webhook request — regardless of outcome — is written to a durable, queryable log (the `/audit-log` dashboard page, or `GET /api/v1/audit-log`). This answers two different questions:

- **"Why isn't Alertmanager reaching Promhis?"** A misconfigured `http_config`, a typo'd URL, a malformed payload — the rejected request is right there with the reason, not lost in a container's stdout that rotated away.
- **"Who's actually sending alerts here?"** Source IP, user agent, timestamp, for every request — basic security visibility into the one endpoint on this service that's reachable without an interactive login.

Each entry records: timestamp, source IP, user agent, which auth mode was attempted, the outcome (`success` / `failure` / `missing`), the HTTP status returned, the alert count (when the payload parsed), the receiver name, and an error detail string for rejections.

### Source IP accuracy behind a proxy

If Promhis sits behind a reverse proxy or load balancer, the "source IP" uvicorn sees by default is the proxy's IP, not the real client's. Set `PROMHIS_TRUST_PROXY=true` to make Promhis honor `X-Forwarded-For`/`X-Forwarded-Proto` from whatever's in front of it — **only do this when there genuinely is a trusted proxy in front of Promhis**. With it set and no real proxy in front, any client can put an arbitrary value in `X-Forwarded-For` and have it recorded as the "real" source IP, which defeats the audit log's purpose. A bare-metal self-host with nothing in front of it should leave this `false` (the default).

### Retention

Audit entries are pruned on the same schedule as alert history (`PROMHIS_RETENTION_DAYS`, default 90 days) — not kept forever, but long enough to debug a misconfigured Alertmanager days or weeks later.
