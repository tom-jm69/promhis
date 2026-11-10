# Pointing Alertmanager at Promhis

Promhis's primary ingest path is an Alertmanager `webhook_configs` receiver — Alertmanager pushes every alert state change to `POST /api/v1/webhook` as it happens. (The optional poller in `PROMHIS_ALERTMANAGER_URL` is a bootstrap/backup, not a replacement — see `docs/configuration.md`.)

This covers the same ground as [`deploy/alertmanager.yml`](../deploy/alertmanager.yml), which is the worked example to copy from.

## Pointing the receiver at Promhis

Point the receiver at your own Promhis container, over your own network:

```yaml
receivers:
  - name: promhis
    webhook_configs:
      - url: http://promhis:8000/api/v1/webhook   # or your container/service's reachable address
        send_resolved: true                        # required — this is how Promhis learns an alert cleared
        http_config:
          basic_auth:
            username: admin
            password: change-me
```

If Promhis is reachable only inside a private network (the common case — there's no reason to expose the webhook endpoint publicly for a same-network Alertmanager), plain `http://` between them is fine; nothing but the two of you can see it. If Alertmanager has to cross a public network to reach Promhis (e.g. a different host, a different site), put a TLS-terminating reverse proxy in front of Promhis and use `https://` instead — Basic-auth credentials go out on every POST, so that traffic shouldn't cross a public network in the clear.

## Choosing Basic vs. Bearer auth

Either case can use HTTP Basic (default, matches the dashboard admin login) or a Bearer token instead — see [`security-and-auditing.md`](security-and-auditing.md#authentication) for the full comparison and how to set `PROMHIS_WEBHOOK_AUTH_MODE`/`PROMHIS_WEBHOOK_TOKEN`. On the Alertmanager side, Bearer looks like:

```yaml
http_config:
  authorization:
    credentials: <the token>
```

Only one scheme is active at a time on the Promhis side, selected by `PROMHIS_WEBHOOK_AUTH_MODE`.

## Verifying it's working

- `send_resolved: true` is required, not optional — without it Alertmanager never tells Promhis an alert cleared, and it'll sit "firing" forever in the dashboard.
- Trigger a test alert (or wait for a real one) and check the overview page's "Last webhook received" badge, or the `/audit-log` page for the request — every attempt is recorded there, accepted or rejected, which is the fastest way to debug a misconfigured `http_config` or URL (see [`security-and-auditing.md`](security-and-auditing.md#the-audit-log)).
- A `401` in the audit log means the credentials don't match; a `400` with a parse error means the payload didn't validate — both get an `error_detail` string explaining what went wrong.
