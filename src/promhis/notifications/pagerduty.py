from __future__ import annotations

from promhis.models import AlertEvent
from promhis.notifications.base import ChannelField, alert_link, post_json, summary_line

_EVENTS_API_URL = "https://events.pagerduty.com/v2/enqueue"

_SEVERITY_MAP = {"critical": "critical", "warning": "warning", "info": "info"}


class PagerDutyChannel:
    """PagerDuty Events API v2. Fires `trigger` on firing, `resolve` on
    resolved, keyed by the alert's fingerprint as PagerDuty's dedup_key —
    this is what lets a later resolution auto-resolve the same incident.
    """

    name = "pagerduty"
    display_name = "PagerDuty"
    fields: list[ChannelField] = [{"name": "routing_key", "label": "Routing Key", "type": "text", "secret": True}]
    # PagerDuty's actual logo mark: exact path data + official brand hex from
    # Simple Icons (simpleicons.org), CC0-licensed for identifying a third-party service.
    icon_svg = (
        '<svg viewBox="0 0 24 24"><title>PagerDuty</title><path fill="#06AC38" d="M16.965 1.18C15.085.164 13.769 0 10.683 0H3.73v14.55h6.926c2.743 0 4.8-.164 6.61-1.37 1.975-1.303 3.004-3.484 3.004-6.007 0-2.716-1.262-4.896-3.305-5.994zm-5.5 10.326h-4.21V3.113l3.977-.027c3.62-.028 5.43 1.234 5.43 4.128 0 3.113-2.248 4.292-5.197 4.292zM3.73 17.61h3.525V24H3.73Z"/></svg>'
    )

    def __init__(self, routing_key: str) -> None:
        self._routing_key = routing_key

    async def send(self, event: AlertEvent) -> None:
        payload = {
            "routing_key": self._routing_key,
            "event_action": "resolve" if event.status == "resolved" else "trigger",
            "dedup_key": event.fingerprint,
            "payload": {
                "summary": summary_line(event),
                "source": event.node or "promhis",
                "severity": _SEVERITY_MAP.get((event.severity or "").lower(), "warning"),
            },
        }
        link = alert_link(event)
        if link:
            payload["links"] = [{"href": link, "text": "View in Promhis"}]
        await post_json(self.name, _EVENTS_API_URL, payload)
