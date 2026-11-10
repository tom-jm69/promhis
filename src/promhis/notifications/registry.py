"""Builds the set of active notification channels from the database.

A channel exists in the registry only when an enabled `NotificationIntegration`
row configures it. Adding a new integration means a new module (implementing
``NotificationChannel``, with its own `display_name`/`fields`) plus one line
in `CHANNEL_CLASSES` below; nothing else in the app changes.

This used to read `PROMHIS_*_WEBHOOK_URL`-style env vars directly. That path
is gone — see docs/notifications.md and the Integrations dashboard page.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from promhis import crud
from promhis.notifications.base import NotificationChannel
from promhis.notifications.discord import DiscordChannel
from promhis.notifications.opsgenie import OpsgenieChannel
from promhis.notifications.pagerduty import PagerDutyChannel
from promhis.notifications.slack import SlackChannel
from promhis.notifications.teams import TeamsChannel
from promhis.notifications.webhook import CustomWebhookChannel

# All outbound notification channels, PagerDuty/Opsgenie included, are free
# (ROADMAP.md §22 reconciliation, 2026-11-06) — an earlier pass of this
# repo gated PagerDuty/Opsgenie behind a license; that's reverted, since
# gating "the product working" rather than "what only matters at team/org
# scale" isn't the model this product charges on.
CHANNEL_CLASSES: dict[str, type[NotificationChannel]] = {
    "slack": SlackChannel,
    "discord": DiscordChannel,
    "teams": TeamsChannel,
    "pagerduty": PagerDutyChannel,
    "opsgenie": OpsgenieChannel,
    "webhook": CustomWebhookChannel,
}


def matches_routing_rules(labels: dict[str, str], rules: list[dict[str, str]] | None) -> bool:
    """Label-match conditions gating which alerts reach an integration —
    ANDed together; no rules (empty/absent) means "every alert," which is
    also the pre-routing-rules default behavior, so an integration with
    none configured is unaffected by this feature.
    """
    if not rules:
        return True
    return all(labels.get(rule.get("label", "")) == rule.get("value") for rule in rules)


async def build_registry(session: AsyncSession) -> dict[str, tuple[NotificationChannel, list[dict[str, str]]]]:
    """One (channel, routing_rules) pair per *enabled* integration row, keyed
    by that row's id (not channel_type — a user may configure more than one
    of the same type, e.g. two different Slack channels). The caller decides
    which alerts actually reach a channel via `matches_routing_rules`.
    """
    routes: dict[str, tuple[NotificationChannel, list[dict[str, str]]]] = {}
    integrations = await crud.list_enabled_integrations(session)
    for integration in integrations:
        channel_class = CHANNEL_CLASSES.get(integration.channel_type)
        if channel_class is None:
            continue
        try:
            channel = channel_class(**integration.config)
        except TypeError:
            # Misconfigured row (missing/extra keys) — skip it rather than
            # fail the whole registry build for every other channel.
            continue
        routes[str(integration.id)] = (channel, integration.routing_rules)
    return routes
