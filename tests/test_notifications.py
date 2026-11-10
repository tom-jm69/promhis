from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from promhis import crud
from promhis.db import async_session_factory
from promhis.models import AlertEvent
from promhis.notifications.discord import DiscordChannel
from promhis.notifications.opsgenie import OpsgenieChannel
from promhis.notifications.pagerduty import PagerDutyChannel
from promhis.notifications.registry import build_registry
from promhis.notifications.slack import SlackChannel
from promhis.notifications.teams import TeamsChannel
from promhis.notifications.webhook import CustomWebhookChannel

pytestmark = pytest.mark.asyncio


def _event(status: str = "firing") -> AlertEvent:
    return AlertEvent(
        fingerprint="fp-notif-1",
        alertname="HighCPULoad",
        status=status,
        severity="critical",
        node="web-01",
        labels={"alertname": "HighCPULoad"},
        annotations={"summary": "CPU above 90%"},
        starts_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ends_at=None,
        receiver="promhis",
    )


class _RecordingPostJson:
    """Stand-in for notifications.base.post_json that records calls instead
    of making a real HTTP request."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, dict | None]] = []

    async def __call__(self, name: str, url: str, payload: dict, *, headers: dict | None = None) -> None:
        self.calls.append((name, url, payload, headers))


async def test_registry_only_includes_enabled_integrations(client: AsyncClient) -> None:
    async with async_session_factory() as session:
        enabled = await crud.create_integration(
            session, channel_type="slack", config={"webhook_url": "https://hooks.slack.test/x"}
        )
        disabled = await crud.create_integration(
            session, channel_type="discord", config={"webhook_url": "https://discord.test/x"}
        )
        await crud.update_integration(session, disabled.id, enabled=False)

        registry = await build_registry(session)
        assert set(registry.keys()) == {str(enabled.id)}


async def test_registry_empty_when_nothing_configured(client: AsyncClient) -> None:
    async with async_session_factory() as session:
        assert await build_registry(session) == {}


async def test_registry_skips_misconfigured_row(client: AsyncClient) -> None:
    async with async_session_factory() as session:
        integration = await crud.create_integration(session, channel_type="slack", config={})
        registry = await build_registry(session)
        assert str(integration.id) not in registry


async def test_registry_carries_routing_rules(client: AsyncClient) -> None:
    async with async_session_factory() as session:
        integration = await crud.create_integration(session, channel_type="slack", config={"webhook_url": "https://x"})
        await crud.update_integration(session, integration.id, routing_rules=[{"label": "env", "value": "production"}])

        routes = await build_registry(session)
        _channel, rules = routes[str(integration.id)]
        assert rules == [{"label": "env", "value": "production"}]


async def test_matches_routing_rules_empty_matches_everything() -> None:
    from promhis.notifications.registry import matches_routing_rules

    assert matches_routing_rules({"env": "staging"}, []) is True
    assert matches_routing_rules({"env": "staging"}, None) is True


async def test_matches_routing_rules_single_condition() -> None:
    from promhis.notifications.registry import matches_routing_rules

    rules = [{"label": "env", "value": "production"}]
    assert matches_routing_rules({"env": "production", "node": "web-1"}, rules) is True
    assert matches_routing_rules({"env": "staging"}, rules) is False
    assert matches_routing_rules({}, rules) is False


async def test_matches_routing_rules_multiple_conditions_anded() -> None:
    from promhis.notifications.registry import matches_routing_rules

    rules = [{"label": "env", "value": "production"}, {"label": "severity", "value": "critical"}]
    assert matches_routing_rules({"env": "production", "severity": "critical"}, rules) is True
    assert matches_routing_rules({"env": "production", "severity": "warning"}, rules) is False


async def test_raise_send_errors_propagates_post_json_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Integrations page's test-send button needs real pass/fail
    feedback, unlike real ingest dispatch which must stay silent on
    failure — `raise_send_errors()` is the one sanctioned way to flip that.
    """
    import httpx

    from promhis.notifications.base import post_json, raise_send_errors

    class _FailingClient:
        async def __aenter__(self) -> "_FailingClient":
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        async def post(self, url: str, json: dict | None = None, headers: dict | None = None) -> None:
            raise httpx.ConnectError("boom", request=httpx.Request("POST", url))

    monkeypatch.setattr("promhis.notifications.base.httpx.AsyncClient", lambda timeout=5.0: _FailingClient())

    # Default behavior: the failure is logged and swallowed, never raised.
    await post_json("test", "https://example.invalid", {})

    # Inside raise_send_errors(), the same failure propagates to the caller.
    with pytest.raises(httpx.ConnectError):
        with raise_send_errors():
            await post_json("test", "https://example.invalid", {})


async def test_slack_payload_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _RecordingPostJson()
    monkeypatch.setattr("promhis.notifications.slack.post_json", recorder)
    await SlackChannel("https://hooks.slack.test/x").send(_event())

    name, url, payload, _ = recorder.calls[0]
    assert name == "slack"
    assert url == "https://hooks.slack.test/x"
    assert "HighCPULoad" in payload["text"]
    assert "FIRING" in payload["text"]


async def test_discord_payload_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _RecordingPostJson()
    monkeypatch.setattr("promhis.notifications.discord.post_json", recorder)
    await DiscordChannel("https://discord.test/x").send(_event())

    _, _, payload, _ = recorder.calls[0]
    assert payload["embeds"][0]["color"] == 0xD9534F  # critical severity color


async def test_teams_payload_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _RecordingPostJson()
    monkeypatch.setattr("promhis.notifications.teams.post_json", recorder)
    await TeamsChannel("https://teams.test/x").send(_event())

    _, _, payload, _ = recorder.calls[0]
    assert payload["@type"] == "MessageCard"
    assert payload["themeColor"] == "d9534f"


async def test_pagerduty_trigger_and_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _RecordingPostJson()
    monkeypatch.setattr("promhis.notifications.pagerduty.post_json", recorder)
    channel = PagerDutyChannel("routing-key-123")
    await channel.send(_event(status="firing"))
    await channel.send(_event(status="resolved"))

    _, _, trigger_payload, _ = recorder.calls[0]
    _, _, resolve_payload, _ = recorder.calls[1]
    assert trigger_payload["event_action"] == "trigger"
    assert trigger_payload["dedup_key"] == "fp-notif-1"
    assert resolve_payload["event_action"] == "resolve"


async def test_opsgenie_create_and_close_use_different_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _RecordingPostJson()
    monkeypatch.setattr("promhis.notifications.opsgenie.post_json", recorder)
    channel = OpsgenieChannel("my-api-key")
    await channel.send(_event(status="firing"))
    await channel.send(_event(status="resolved"))

    create_name, create_url, create_payload, _ = recorder.calls[0]
    _, close_url, _, _ = recorder.calls[1]
    assert create_url == "https://api.opsgenie.com/v2/alerts"
    assert create_payload["alias"] == "fp-notif-1"
    assert close_url == "https://api.opsgenie.com/v2/alerts/fp-notif-1/close?identifierType=alias"


async def test_custom_webhook_posts_raw_event(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _RecordingPostJson()
    monkeypatch.setattr("promhis.notifications.webhook.post_json", recorder)
    await CustomWebhookChannel("https://custom.test/x").send(_event())

    _, _, payload, _ = recorder.calls[0]
    assert payload["fingerprint"] == "fp-notif-1"
    assert payload["status"] == "firing"


async def test_notification_failure_does_not_break_ingest(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _BoomChannel:
        name = "boom"

        async def send(self, event: AlertEvent) -> None:
            raise RuntimeError("simulated channel failure")

    async def _boom_registry(session: object) -> dict[str, tuple[_BoomChannel, list[dict[str, str]]]]:
        return {"boom": (_BoomChannel(), [])}

    monkeypatch.setattr("promhis.routers.webhook.build_registry", _boom_registry)

    response = await client.post(
        "/api/v1/webhook",
        json={
            "receiver": "promhis",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "X", "severity": "critical", "node": "n1"},
                    "annotations": {},
                    "startsAt": "2026-01-01T00:00:00Z",
                    "endsAt": None,
                    "generatorURL": None,
                    "fingerprint": "fp-boom-1",
                }
            ],
        },
        auth=("testadmin", "testpass"),
    )
    assert response.status_code == 200
    assert response.json() == {"ingested": 1}
