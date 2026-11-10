from __future__ import annotations

from promhis.models import AlertEvent
from promhis.notifications.base import ChannelField, alert_link, post_json, severity_color, summary_line


class TeamsChannel:
    """Microsoft Teams incoming webhook, MessageCard format — the simplest
    format that's still broadly supported for a one-line text notification.
    """

    name = "teams"
    display_name = "Microsoft Teams"
    fields: list[ChannelField] = [{"name": "webhook_url", "label": "Webhook URL", "type": "url", "secret": True}]
    # Microsoft Teams' purple tile with its stylized "T" + collaborator-dot
    # mark, simplified rather than traced exactly from the official asset.
    icon_svg = (
        '<svg viewBox="0 0 24 24">'
        '<rect x="2" y="2" width="20" height="20" rx="5" fill="#5059C9"/>'
        '<rect x="6.5" y="7.5" width="10" height="2.2" rx="1.1" fill="#fff"/>'
        '<rect x="10.4" y="7.5" width="2.2" height="10" rx="1.1" fill="#fff"/>'
        '<circle cx="17.5" cy="7" r="2" fill="#fff"/>'
        "</svg>"
    )

    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url

    async def send(self, event: AlertEvent) -> None:
        text = summary_line(event)
        card: dict = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": text,
            "themeColor": severity_color(event.severity),
            "title": text,
        }
        link = alert_link(event)
        if link:
            card["potentialAction"] = [
                {
                    "@type": "OpenUri",
                    "name": "View in Promhis",
                    "targets": [{"os": "default", "uri": link}],
                }
            ]
        await post_json(self.name, self._webhook_url, card)
