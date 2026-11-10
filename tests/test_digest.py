from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.message import EmailMessage

import pytest

from promhis import digest
from promhis.config import settings
from promhis.models import AlertEvent


def _event(status: str, alertname: str = "HighCPULoad", node: str | None = "web-01") -> AlertEvent:
    return AlertEvent(
        fingerprint=f"fp-{alertname}-{status}",
        alertname=alertname,
        status=status,
        severity="critical",
        node=node,
        labels={},
        annotations={},
        starts_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ends_at=None,
    )


def test_build_digest_empty() -> None:
    subject, body = digest.build_digest([], window_hours=24)
    assert "0 firing, 0 resolved" in subject
    assert "No alert activity" in body


def test_build_digest_mixed_events() -> None:
    events = [_event("firing"), _event("firing", alertname="DiskFull"), _event("resolved")]
    subject, body = digest.build_digest(events, window_hours=24)
    assert "2 firing, 1 resolved" in subject
    assert "HighCPULoad" in body
    assert "DiskFull" in body
    assert "Firing (2):" in body
    assert "Resolved (1):" in body


def test_build_digest_includes_public_url_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "public_base_url", "https://promhis.example.com")
    _, body = digest.build_digest([_event("firing")], window_hours=24)
    assert "https://promhis.example.com/alerts" in body


def test_seconds_until_next_run_is_positive_and_bounded() -> None:
    seconds = digest.seconds_until_next_run()
    assert 0 < seconds <= 24 * 60 * 60


@pytest.mark.asyncio
async def test_send_digest_composes_and_sends_via_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    sent_messages = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            self.host = host
            self.port = port

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *exc: object) -> None:
            pass

        def starttls(self) -> None:
            pass

        def login(self, user: str, password: str) -> None:
            pass

        def send_message(self, message: EmailMessage) -> None:
            sent_messages.append(message)

    monkeypatch.setattr(settings, "digest_to", "oncall@example.com")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_user", "user")
    monkeypatch.setattr(settings, "smtp_password", "pass")
    monkeypatch.setattr(digest.smtplib, "SMTP", FakeSMTP)

    await digest.send_digest("Test subject", "Test body")

    assert len(sent_messages) == 1
    assert sent_messages[0]["Subject"] == "Test subject"
    assert sent_messages[0]["To"] == "oncall@example.com"


@pytest.mark.asyncio
async def test_digest_scheduler_noop_when_unconfigured() -> None:
    # settings.digest_to is None by default in the test environment —
    # run_digest_scheduler must return immediately, not loop forever.
    await asyncio.wait_for(digest.run_digest_scheduler(), timeout=1.0)
