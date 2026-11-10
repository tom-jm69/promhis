from __future__ import annotations

from promhis.models import AlertEvent
from promhis.notifications.base import ChannelField, alert_link, post_json, summary_line


class SlackChannel:
    name = "slack"
    display_name = "Slack"
    fields: list[ChannelField] = [{"name": "webhook_url", "label": "Webhook URL", "type": "url", "secret": True}]
    # Slack's own four-color mark, approximated: the official glyph is a
    # pinwheel of rounded lozenge+dot shapes, not plain bars — this keeps
    # the real brand colors and compositional idea, not a pixel-exact
    # trace of the trademarked artwork.
    icon_svg = (
        '<svg viewBox="0 0 24 24">'
        '<rect x="9" y="1.5" width="3.2" height="8.5" rx="1.6" fill="#36C5F0"/>'
        '<rect x="9" y="14" width="3.2" height="8.5" rx="1.6" fill="#2EB67D"/>'
        '<rect x="1.5" y="9" width="8.5" height="3.2" rx="1.6" fill="#E01E5A"/>'
        '<rect x="14" y="9" width="8.5" height="3.2" rx="1.6" fill="#ECB22E"/>'
        "</svg>"
    )

    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url

    async def send(self, event: AlertEvent) -> None:
        text = summary_line(event)
        link = alert_link(event)
        if link:
            text += f"\n<{link}|View in Promhis>"
        await post_json(self.name, self._webhook_url, {"text": text})
