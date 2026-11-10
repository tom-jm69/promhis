from __future__ import annotations

from promhis.models import AlertEvent
from promhis.notifications.base import ChannelField, post_json


class CustomWebhookChannel:
    """Generic outbound webhook (Business tier): posts the raw alert event,
    no service-specific formatting — for piping into whatever the user's
    own tooling expects.
    """

    name = "webhook"
    display_name = "Custom Webhook"
    fields: list[ChannelField] = [{"name": "webhook_url", "label": "Webhook URL", "type": "url", "secret": True}]
    icon_svg = (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M10 13a5 5 0 0 0 7.07 0l2.12-2.12a5 5 0 0 0-7.07-7.07L10.5 5.5"/>'
        '<path d="M14 11a5 5 0 0 0-7.07 0L4.8 13.12a5 5 0 0 0 7.07 7.07L13.5 18.5"/>'
        "</svg>"
    )

    def __init__(self, webhook_url: str) -> None:
        self._url = webhook_url

    async def send(self, event: AlertEvent) -> None:
        payload = {
            "fingerprint": event.fingerprint,
            "alertname": event.alertname,
            "status": event.status,
            "severity": event.severity,
            "node": event.node,
            "labels": event.labels,
            "annotations": event.annotations,
            "starts_at": event.starts_at.isoformat(),
            "ends_at": event.ends_at.isoformat() if event.ends_at else None,
            "receiver": event.receiver,
        }
        await post_json(self.name, self._url, payload)
