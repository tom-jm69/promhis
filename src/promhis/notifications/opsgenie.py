from __future__ import annotations

from promhis.models import AlertEvent
from promhis.notifications.base import ChannelField, alert_link, post_json, summary_line

_API_BASE = "https://api.opsgenie.com/v2/alerts"

_PRIORITY_MAP = {"critical": "P1", "warning": "P3", "info": "P5"}


class OpsgenieChannel:
    """Opsgenie Alert API. Creates an alert (aliased to the fingerprint) on
    firing, closes that same alias on resolved.
    """

    name = "opsgenie"
    display_name = "Opsgenie"
    fields: list[ChannelField] = [{"name": "api_key", "label": "API Key", "type": "text", "secret": True}]
    # Opsgenie's actual logo mark: exact path data + official brand hex from
    # Simple Icons (simpleicons.org), CC0-licensed for identifying a third-party service.
    icon_svg = '<svg viewBox="0 0 24 24"><title>Opsgenie</title><path fill="#172B4D" d="M12.002 0a5.988 5.988 0 1 1 0 11.975 5.988 5.988 0 0 1 0-11.975zm9.723 13.026h-.03l-4.527-2.242a.671.671 0 0 0-.876.268 22.408 22.408 0 0 1-4.306 5.217 22.407 22.407 0 0 1-4.286-5.2.671.671 0 0 0-.876-.269l-4.535 2.226h-.03a.671.671 0 0 0-.248.902 28.85 28.85 0 0 0 4.55 5.933l-.002.001c.024.025.05.048.075.072.335.335.676.664 1.027.981.081.074.165.144.247.217.315.278.632.555.96.82.144.117.295.227.441.341.277.216.552.434.837.639.44.318.888.625 1.346.917a.963.963 0 0 0 1.007.017c.487-.312.962-.64 1.428-.98.068-.05.132-.103.2-.153.358-.266.713-.537 1.06-.82.234-.19.46-.39.688-.588.17-.147.34-.291.506-.442.295-.268.58-.545.864-.825.061-.06.127-.118.188-.179l-.004-.002a28.852 28.852 0 0 0 4.565-5.949.671.671 0 0 0-.269-.902z"/></svg>'

    def __init__(self, api_key: str) -> None:
        self._headers = {"Authorization": f"GenieKey {api_key}"}

    async def send(self, event: AlertEvent) -> None:
        if event.status == "resolved":
            url = f"{_API_BASE}/{event.fingerprint}/close?identifierType=alias"
            await post_json(self.name, url, {"source": "promhis"}, headers=self._headers)
            return

        payload: dict[str, object] = {
            "message": summary_line(event),
            "alias": event.fingerprint,
            "priority": _PRIORITY_MAP.get((event.severity or "").lower(), "P3"),
        }
        link = alert_link(event)
        if link:
            payload["details"] = {"promhis_url": link}
        await post_json(self.name, _API_BASE, payload, headers=self._headers)
