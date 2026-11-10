from __future__ import annotations

import re

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


def _extract_integration_id(page_html: str, action: str) -> str:
    match = re.search(rf'/integrations/(\d+)/{action}"', page_html)
    assert match is not None
    return match.group(1)


def _extract_routing_id(page_html: str, display_name: str) -> str:
    """Routing rows don't carry an action suffix in their form action
    (`/routing/{id}`, not `/routing/{id}/update`) — scoped to the row for a
    specific channel's display name, same reasoning as `_extract_id_for_channel`.
    """
    name_index = page_html.index(display_name)
    match = re.search(r'/routing/(\d+)"', page_html[name_index:])
    assert match is not None
    return match.group(1)


def _extract_id_for_channel(page_html: str, display_name: str, action: str) -> str:
    """Like `_extract_integration_id`, but scoped to the configured-row for
    a specific channel's display name — rows list newest-first, so when a
    test creates more than one integration it can't rely on "the first
    match" meaning "the one I created first." Searches from the
    "Configured integrations" table, skipping the "Add integration" picker
    above it, which also prints every channel's display name.
    """
    table_start = page_html.index("Configured integrations")
    name_index = page_html.index(display_name, table_start)
    match = re.search(rf'/integrations/(\d+)/{action}"', page_html[name_index:])
    assert match is not None
    return match.group(1)


async def test_integrations_page_requires_login(client: AsyncClient) -> None:
    response = await client.get("/integrations", follow_redirects=False)
    assert response.status_code == 303


async def test_create_integration(authed_client: AsyncClient) -> None:
    create = await authed_client.post(
        "/integrations",
        data={"channel_type": "slack", "cfg_slack_webhook_url": "https://hooks.slack.test/abcd1234"},
    )
    assert create.status_code == 303

    page = await authed_client.get("/integrations")
    assert page.status_code == 200
    assert "Slack" in page.text
    # The secret is masked, not shown in full, in the listing.
    assert "https://hooks.slack.test/abcd1234" not in page.text
    assert "••••1234" in page.text


async def test_toggle_integration(authed_client: AsyncClient) -> None:
    await authed_client.post(
        "/integrations", data={"channel_type": "discord", "cfg_discord_webhook_url": "https://discord.test/x"}
    )
    page = await authed_client.get("/integrations")
    integration_id = _extract_integration_id(page.text, "toggle")
    assert "enabled" in page.text

    toggle = await authed_client.post(f"/integrations/{integration_id}/toggle")
    assert toggle.status_code == 303

    page_after = await authed_client.get("/integrations")
    assert "disabled" in page_after.text


async def test_update_integration_blank_keeps_existing_secret(authed_client: AsyncClient) -> None:
    # Teams is just a convenient channel type with a secret field, chosen
    # arbitrarily for this generic config-update behavior test.
    await authed_client.post(
        "/integrations", data={"channel_type": "teams", "cfg_teams_webhook_url": "https://teams.test/routing-key-0001"}
    )
    page = await authed_client.get("/integrations")
    integration_id = _extract_integration_id(page.text, "update")

    # Blank submit — the secret should be left untouched.
    update = await authed_client.post(f"/integrations/{integration_id}/update", data={})
    assert update.status_code == 303
    page_after = await authed_client.get("/integrations")
    assert "••••0001" in page_after.text

    # A new value does replace it.
    await authed_client.post(
        f"/integrations/{integration_id}/update", data={"cfg_teams_webhook_url": "https://teams.test/routing-key-9999"}
    )
    page_replaced = await authed_client.get("/integrations")
    assert "••••9999" in page_replaced.text
    assert "••••0001" not in page_replaced.text


async def test_delete_integration(authed_client: AsyncClient) -> None:
    # Custom Webhook is just a convenient channel type, chosen arbitrarily
    # for this generic delete-flow test.
    await authed_client.post(
        "/integrations", data={"channel_type": "webhook", "cfg_webhook_webhook_url": "https://webhook.test/my-api-key"}
    )
    page = await authed_client.get("/integrations")
    integration_id = _extract_integration_id(page.text, "delete")

    delete = await authed_client.post(f"/integrations/{integration_id}/delete")
    assert delete.status_code == 303

    page_after = await authed_client.get("/integrations")
    assert "No integrations configured yet." in page_after.text


async def test_disabling_integration_stops_it_firing_on_next_ingest(
    authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def _recording_post_json(name: str, url: str, payload: dict, *, headers: dict | None = None) -> None:
        calls.append(name)

    monkeypatch.setattr("promhis.notifications.slack.post_json", _recording_post_json)

    await authed_client.post(
        "/integrations", data={"channel_type": "slack", "cfg_slack_webhook_url": "https://hooks.slack.test/x"}
    )
    page = await authed_client.get("/integrations")
    integration_id = _extract_integration_id(page.text, "toggle")

    webhook_payload = {
        "receiver": "promhis",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "IntegrationTest", "severity": "critical", "node": "n1"},
                "annotations": {},
                "startsAt": "2026-01-01T00:00:00Z",
                "endsAt": None,
                "generatorURL": None,
                "fingerprint": "fp-integ-1",
            }
        ],
    }
    first = await authed_client.post("/api/v1/webhook", json=webhook_payload, auth=("testadmin", "testpass"))
    assert first.status_code == 200
    assert calls == ["slack"]

    await authed_client.post(f"/integrations/{integration_id}/toggle")
    webhook_payload["alerts"][0]["fingerprint"] = "fp-integ-2"
    second = await authed_client.post("/api/v1/webhook", json=webhook_payload, auth=("testadmin", "testpass"))
    assert second.status_code == 200
    assert calls == ["slack"]  # unchanged — the disabled channel didn't fire again


async def test_routing_rule_only_fires_on_matching_alert(
    authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def _recording_post_json(name: str, url: str, payload: dict, *, headers: dict | None = None) -> None:
        calls.append(name)

    monkeypatch.setattr("promhis.notifications.slack.post_json", _recording_post_json)

    await authed_client.post(
        "/integrations", data={"channel_type": "slack", "cfg_slack_webhook_url": "https://hooks.slack.test/x"}
    )
    page = await authed_client.get("/integrations")
    integration_id = _extract_integration_id(page.text, "toggle")

    await authed_client.post(
        f"/routing/{integration_id}",
        data={"rule_label_0": "env", "rule_value_0": "production"},
    )

    def _payload(fingerprint: str, env: str) -> dict:
        return {
            "receiver": "promhis",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "RoutingTest", "severity": "critical", "node": "n1", "env": env},
                    "annotations": {},
                    "startsAt": "2026-01-01T00:00:00Z",
                    "endsAt": None,
                    "generatorURL": None,
                    "fingerprint": fingerprint,
                }
            ],
        }

    non_matching = await authed_client.post(
        "/api/v1/webhook", json=_payload("fp-route-1", "staging"), auth=("testadmin", "testpass")
    )
    assert non_matching.status_code == 200
    assert calls == []  # staging alert doesn't match the env=production rule

    matching = await authed_client.post(
        "/api/v1/webhook", json=_payload("fp-route-2", "production"), auth=("testadmin", "testpass")
    )
    assert matching.status_code == 200
    assert calls == ["slack"]


async def test_integration_with_no_rules_still_receives_everything(
    authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def _recording_post_json(name: str, url: str, payload: dict, *, headers: dict | None = None) -> None:
        calls.append(name)

    monkeypatch.setattr("promhis.notifications.discord.post_json", _recording_post_json)

    await authed_client.post(
        "/integrations", data={"channel_type": "discord", "cfg_discord_webhook_url": "https://discord.test/x"}
    )

    response = await authed_client.post(
        "/api/v1/webhook",
        json={
            "receiver": "promhis",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "NoRuleTest", "severity": "warning", "node": "n2"},
                    "annotations": {},
                    "startsAt": "2026-01-01T00:00:00Z",
                    "endsAt": None,
                    "generatorURL": None,
                    "fingerprint": "fp-norule-1",
                }
            ],
        },
        auth=("testadmin", "testpass"),
    )
    assert response.status_code == 200
    assert calls == ["discord"]


async def test_overlapping_integrations_route_independently(
    authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def _recording_slack(name: str, url: str, payload: dict, *, headers: dict | None = None) -> None:
        calls.append("slack")

    async def _recording_discord(name: str, url: str, payload: dict, *, headers: dict | None = None) -> None:
        calls.append("discord")

    monkeypatch.setattr("promhis.notifications.slack.post_json", _recording_slack)
    monkeypatch.setattr("promhis.notifications.discord.post_json", _recording_discord)

    await authed_client.post(
        "/integrations", data={"channel_type": "slack", "cfg_slack_webhook_url": "https://hooks.slack.test/x"}
    )
    await authed_client.post(
        "/integrations", data={"channel_type": "discord", "cfg_discord_webhook_url": "https://discord.test/x"}
    )
    page = await authed_client.get("/integrations")
    slack_id = _extract_id_for_channel(page.text, "Slack", "toggle")

    # Scope the Slack integration to env=production; leave Discord unscoped
    # (receives everything) — both configured channels must route
    # independently off the same alert.
    await authed_client.post(
        f"/routing/{slack_id}",
        data={"rule_label_0": "env", "rule_value_0": "production"},
    )

    response = await authed_client.post(
        "/api/v1/webhook",
        json={
            "receiver": "promhis",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "OverlapTest", "severity": "critical", "node": "n3", "env": "staging"},
                    "annotations": {},
                    "startsAt": "2026-01-01T00:00:00Z",
                    "endsAt": None,
                    "generatorURL": None,
                    "fingerprint": "fp-overlap-1",
                }
            ],
        },
        auth=("testadmin", "testpass"),
    )
    assert response.status_code == 200
    assert calls == ["discord"]  # Slack's rule didn't match staging; Discord has no rules and always fires


async def test_send_test_notification_success(authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ok_post_json(name: str, url: str, payload: dict, *, headers: dict | None = None) -> None:
        return None

    monkeypatch.setattr("promhis.notifications.slack.post_json", _ok_post_json)

    await authed_client.post(
        "/integrations", data={"channel_type": "slack", "cfg_slack_webhook_url": "https://hooks.slack.test/x"}
    )
    page = await authed_client.get("/integrations")
    integration_id = _extract_integration_id(page.text, "test")

    response = await authed_client.post(f"/integrations/{integration_id}/test")
    assert response.status_code == 303

    page_after = await authed_client.get("/integrations")
    assert "Test notification sent to" in page_after.text
    assert "Slack" in page_after.text


async def test_send_test_notification_surfaces_real_failure(
    authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    async def _failing_post_json(name: str, url: str, payload: dict, *, headers: dict | None = None) -> None:
        request = httpx.Request("POST", url)
        response = httpx.Response(401, request=request)
        raise httpx.HTTPStatusError("401 Unauthorized", request=request, response=response)

    monkeypatch.setattr("promhis.notifications.slack.post_json", _failing_post_json)

    await authed_client.post(
        "/integrations", data={"channel_type": "slack", "cfg_slack_webhook_url": "https://hooks.slack.test/bad"}
    )
    page = await authed_client.get("/integrations")
    integration_id = _extract_integration_id(page.text, "test")

    response = await authed_client.post(f"/integrations/{integration_id}/test")
    assert response.status_code == 303

    page_after = await authed_client.get("/integrations")
    assert "failed" in page_after.text.lower()


async def test_routing_page_requires_login(client: AsyncClient) -> None:
    response = await client.get("/routing", follow_redirects=False)
    assert response.status_code == 303


async def test_routing_rules_chip_shows_all_alerts_when_unscoped(authed_client: AsyncClient) -> None:
    await authed_client.post(
        "/integrations", data={"channel_type": "discord", "cfg_discord_webhook_url": "https://discord.test/chip"}
    )
    page = await authed_client.get("/routing")
    assert "all alerts" in page.text


async def test_set_routing_rule_via_routing_tab(authed_client: AsyncClient) -> None:
    await authed_client.post(
        "/integrations", data={"channel_type": "slack", "cfg_slack_webhook_url": "https://hooks.slack.test/route-tab"}
    )
    page = await authed_client.get("/routing")
    integration_id = _extract_routing_id(page.text, "Slack")

    update = await authed_client.post(
        f"/routing/{integration_id}", data={"rule_label_0": "env", "rule_value_0": "production"}
    )
    assert update.status_code == 303

    routing_page = await authed_client.get("/routing")
    assert "<b>env</b>=production" in routing_page.text
    # Routing is no longer shown or editable on the Integrations page itself.
    integrations_page = await authed_client.get("/integrations")
    assert "<b>env</b>=production" not in integrations_page.text
    assert "rule_label_0" not in integrations_page.text


async def test_editing_integration_config_does_not_clear_routing_rules(authed_client: AsyncClient) -> None:
    await authed_client.post(
        "/integrations", data={"channel_type": "teams", "cfg_teams_webhook_url": "https://teams.test/routing-key-0001"}
    )
    page = await authed_client.get("/integrations")
    integration_id = _extract_integration_id(page.text, "update")

    await authed_client.post(f"/routing/{integration_id}", data={"rule_label_0": "env", "rule_value_0": "production"})

    # Editing the channel's config on the Integrations page must not touch
    # its routing rules — a real bug caught while splitting the two pages
    # (this endpoint used to unconditionally overwrite routing_rules from
    # whatever rule_label_*/rule_value_* fields were on the submitted form,
    # which is now none, since that editor lives on /routing instead).
    await authed_client.post(
        f"/integrations/{integration_id}/update", data={"cfg_teams_webhook_url": "https://teams.test/routing-key-9999"}
    )

    routing_page = await authed_client.get("/routing")
    assert "<b>env</b>=production" in routing_page.text


async def test_create_integration_via_htmx_returns_rows_fragment(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/integrations",
        data={"channel_type": "slack", "cfg_slack_webhook_url": "https://hooks.slack.test/htmx-create"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "Slack" in response.text
    assert "••••eate" in response.text  # masked secret present
    assert "<nav" not in response.text
    assert "Add integration" not in response.text  # fragment is just the rows, not the Add panel


async def test_update_integration_via_htmx_returns_row_fragment(authed_client: AsyncClient) -> None:
    await authed_client.post(
        "/integrations", data={"channel_type": "teams", "cfg_teams_webhook_url": "https://teams.test/routing-key-htmx1"}
    )
    page = await authed_client.get("/integrations")
    integration_id = _extract_integration_id(page.text, "update")

    response = await authed_client.post(
        f"/integrations/{integration_id}/update",
        data={"cfg_teams_webhook_url": "https://teams.test/routing-key-htmx9"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert f'id="integration-row-{integration_id}"' in response.text
    assert "••••tmx9" in response.text
    assert "<nav" not in response.text


async def test_update_routing_rules_via_htmx_returns_row_fragment(authed_client: AsyncClient) -> None:
    await authed_client.post(
        "/integrations", data={"channel_type": "discord", "cfg_discord_webhook_url": "https://discord.test/htmx-route"}
    )
    page = await authed_client.get("/routing")
    integration_id = _extract_routing_id(page.text, "Discord")

    response = await authed_client.post(
        f"/routing/{integration_id}",
        data={"rule_label_0": "env", "rule_value_0": "production"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert f'id="routing-row-{integration_id}"' in response.text
    assert "<b>env</b>=production" in response.text
    assert "<nav" not in response.text


async def test_label_key_datalist_reflects_alert_history(authed_client: AsyncClient) -> None:
    await authed_client.post(
        "/api/v1/webhook",
        json={
            "receiver": "promhis",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "LabelKeyTest", "severity": "critical", "region": "eu-west-1"},
                    "annotations": {},
                    "startsAt": "2026-01-01T00:00:00Z",
                    "endsAt": None,
                    "generatorURL": None,
                    "fingerprint": "fp-labelkey-1",
                }
            ],
        },
        auth=("testadmin", "testpass"),
    )
    page = await authed_client.get("/routing")
    assert 'id="label-keys"' in page.text
    assert '<option value="region">' in page.text


async def test_toggle_integration_via_htmx_returns_row_fragment(authed_client: AsyncClient) -> None:
    await authed_client.post(
        "/integrations", data={"channel_type": "discord", "cfg_discord_webhook_url": "https://discord.test/hx"}
    )
    page = await authed_client.get("/integrations")
    integration_id = _extract_integration_id(page.text, "toggle")

    toggle = await authed_client.post(
        f"/integrations/{integration_id}/toggle", headers={"HX-Request": "true"}
    )
    assert toggle.status_code == 200
    assert f'id="integration-row-{integration_id}"' in toggle.text
    assert "disabled" in toggle.text
    # No full-page chrome in the fragment — just the row.
    assert "Configured integrations" not in toggle.text


async def test_delete_integration_via_htmx_returns_empty_body(authed_client: AsyncClient) -> None:
    await authed_client.post(
        "/integrations", data={"channel_type": "webhook", "cfg_webhook_webhook_url": "https://webhook.test/hx-delete-key"}
    )
    page = await authed_client.get("/integrations")
    integration_id = _extract_integration_id(page.text, "delete")

    delete = await authed_client.post(
        f"/integrations/{integration_id}/delete", headers={"HX-Request": "true"}
    )
    assert delete.status_code == 200
    assert delete.text == ""

    page_after = await authed_client.get("/integrations")
    assert "No integrations configured yet." in page_after.text


async def test_send_test_notification_via_htmx_returns_inline_fragment(
    authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _ok_post_json(name: str, url: str, payload: dict, *, headers: dict | None = None) -> None:
        return None

    monkeypatch.setattr("promhis.notifications.slack.post_json", _ok_post_json)

    await authed_client.post(
        "/integrations", data={"channel_type": "slack", "cfg_slack_webhook_url": "https://hooks.slack.test/hx-test"}
    )
    page = await authed_client.get("/integrations")
    integration_id = _extract_integration_id(page.text, "test")

    response = await authed_client.post(
        f"/integrations/{integration_id}/test", headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    assert "Sent to" in response.text
    # Inline fragment, not the full page's session-flash banner.
    assert "Configured integrations" not in response.text
