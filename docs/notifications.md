# Outbound notification forwarding

Promhis receives alerts from Alertmanager. It can also forward them to Slack, Discord, Microsoft Teams, PagerDuty, Opsgenie, or a generic custom webhook. Each one is configured through the dashboard's **Integrations** page (`/integrations`), not environment variables — pick a channel type, fill in its one credential field, save. A channel only fires when its integration row exists *and* is enabled; disabling one (or deleting it) stops it firing on the next ingest without touching anything else.

> **Migration note:** earlier versions configured these six channels via `PROMHIS_SLACK_WEBHOOK_URL`/`PROMHIS_DISCORD_WEBHOOK_URL`/`PROMHIS_TEAMS_WEBHOOK_URL`/`PROMHIS_PAGERDUTY_ROUTING_KEY`/`PROMHIS_OPSGENIE_API_KEY`/`PROMHIS_CUSTOM_WEBHOOK_URL`. None of those env vars are read anymore — if you're upgrading from a self-hosted instance that used them, re-enter the same credentials on the Integrations page after upgrading. This is a one-time breaking change. (Every other env var — admin credentials, session secret, database URL, webhook auth mode — is unaffected.)

Every channel is fire-and-forget: a failing or slow notification target never fails the webhook response Alertmanager gets, and one channel's failure never blocks another's. Failures are logged (`promhis.notifications` logger), not surfaced anywhere else.

A saved credential is never shown again in full on the Integrations page — only a masked tail (e.g. `••••1234`), so you have to deliberately replace it to change it. Leaving the field blank when editing an integration keeps the existing credential.

## Verifying an integration works

Each configured integration has a **Send test** button that fires one synthetic alert through that channel only, right away — no need to wait for a real incident to find out a webhook URL or API key is wrong. Unlike real alert delivery (which fails silently — see above), a test send reports back on the page whether it actually succeeded, including the real error (e.g. "401 Unauthorized") when it didn't.

## Routing: sending only some alerts to an integration

By default, every *enabled* integration receives every alert. The **Routing** tab (separate from **Integrations**, which only handles channel config/secrets) lists every configured integration with its own small routing-rules editor — up to a few `label = value` rows, with autocomplete suggestions drawn from label keys actually seen in your alert history. When any rows are set for an integration, only alerts whose labels match **every** row reach it; an integration with no rows set still receives everything (the original behavior, unaffected). This is a deliberately simple equality match, not a pattern/expression language — e.g. set `env` = `production` on a PagerDuty integration to only page for production alerts, while a Slack integration with no rules still gets everything for visibility. Different integrations route independently, so one alert can reach some of your configured channels and not others based on its labels.

## Slack

**Field:** Webhook URL — e.g. `https://hooks.slack.com/services/T000/B000/XXXX`

Create an [Incoming Webhook](https://api.slack.com/messaging/webhooks) in your Slack workspace and paste its URL into the Integrations page.

## Discord

**Field:** Webhook URL — e.g. `https://discord.com/api/webhooks/<id>/<token>`

Channel Settings → Integrations → Webhooks → New Webhook, copy its URL.

## Microsoft Teams

**Field:** Webhook URL — e.g. `https://<org>.webhook.office.com/webhookb2/...`

Channel → Connectors → Incoming Webhook. Promhis sends the classic MessageCard format, which every Teams incoming webhook still accepts.

## PagerDuty

**Field:** Routing Key — a service's "Events API v2" integration key.

Promhis sends `trigger` when an alert fires and `resolve` when it resolves, keyed by the alert's fingerprint as PagerDuty's `dedup_key` — so a resolution in Alertmanager auto-resolves the matching PagerDuty incident.

## Opsgenie

**Field:** API Key — from an Opsgenie API integration.

Promhis creates an alert (aliased to the fingerprint) on firing and closes that same alias on resolution.

## Generic custom webhook

**Field:** Webhook URL — your own endpoint.

Posts the raw alert event as JSON (fingerprint, alertname, status, severity, node, labels, annotations, timestamps, receiver) — no service-specific formatting. For piping into your own tooling. **Business tier and up on the cloud offering** (see `PRICING.md`); unrestricted on self-host.

## Linking back to Promhis

Set `PROMHIS_PUBLIC_BASE_URL` (e.g. `https://promhis.example.com`) to have Slack/Discord/Teams/PagerDuty/Opsgenie notifications include a link back to that alert's page in your Promhis dashboard. Omitted entirely when unset. (This one setting stays an env var — it describes the instance itself, not a specific integration.)

## Which tiers get which channels

See `PRICING.md` for the full breakdown — in short: Starter has no outbound forwarding, Team adds Slack/Discord/Teams, Business adds PagerDuty/Opsgenie/the generic webhook. Self-hosted has everything, unrestricted (the tier gating only applies to the cloud offering, and even there it's a published tier definition, not a technically enforced limit today — see the roadmap's non-goals).

## Extending with a new channel

Each channel is one small class implementing `async def send(self, event: AlertEvent) -> None` under `src/promhis/notifications/`, plus `display_name` and a `fields` list (`ChannelField`s — name, label, input type, which field is the secret) that drives its Integrations-page form automatically. Register it with one line in `src/promhis/notifications/registry.py`'s `CHANNEL_CLASSES`. Adding one is: write the class, add the registry line — no dashboard or form code to touch. See `CONTRIBUTING.md`'s extensibility section.
