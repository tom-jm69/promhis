from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.message import EmailMessage

import pytest

from promhis import digest
from promhis.config import settings
from promhis.db import async_session_factory
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
    seconds = digest.seconds_until_next_run(hour_utc=8)
    assert 0 < seconds <= 24 * 60 * 60


def _digest_config() -> digest.DigestConfig:
    return digest.DigestConfig(
        to_addr="oncall@example.com",
        hour_utc=8,
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="user",
        smtp_password="pass",
        smtp_from="promhis@localhost",
        smtp_use_tls=True,
    )


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

    monkeypatch.setattr(digest.smtplib, "SMTP", FakeSMTP)

    await digest.send_digest("Test subject", "Test body", _digest_config())

    assert len(sent_messages) == 1
    assert sent_messages[0]["Subject"] == "Test subject"
    assert sent_messages[0]["To"] == "oncall@example.com"


@pytest.mark.asyncio
async def test_effective_digest_config_none_by_default() -> None:
    # Neither digest_to nor smtp_host is set in the test environment.
    async with async_session_factory() as session:
        assert await digest.effective_digest_config(session) is None


@pytest.mark.asyncio
async def test_effective_digest_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # setting_env_locked checks the real process environment, not the
    # Settings object — both need patching together, same as the existing
    # metrics env-locked tests.
    monkeypatch.setenv("PROMHIS_DIGEST_TO", "oncall@example.com")
    monkeypatch.setattr(settings, "digest_to", "oncall@example.com")
    monkeypatch.setenv("PROMHIS_SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")

    async with async_session_factory() as session:
        config = await digest.effective_digest_config(session)
    assert config is not None
    assert config.to_addr == "oncall@example.com"
    assert config.smtp_host == "smtp.example.com"


@pytest.mark.asyncio
async def test_scheduler_runs_without_crashing_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    # Neither digest_to nor smtp_host is set in the test environment —
    # the scheduler must keep looping (not crash, not send anything), just
    # with nothing to do each cycle.
    monkeypatch.setattr(digest, "seconds_until_next_run", lambda hour_utc: 0.0)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(digest.run_digest_scheduler(), timeout=0.5)
