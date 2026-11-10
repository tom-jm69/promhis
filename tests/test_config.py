from __future__ import annotations

import pytest

from promhis.config import Settings


def test_comma_separated_env_vars_do_not_crash_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test: these fields are documented as plain comma-separated
    values (docs/configuration.md), not JSON arrays. pydantic-settings
    treats tuple-typed fields as "complex" and JSON-decodes the raw env
    string by default — a plain "a,b,c" isn't valid JSON, so without the
    NoDecode + manual-split handling in config.py, constructing Settings()
    with either of these set for real crashed at import time.
    """
    monkeypatch.setenv("PROMHIS_NODE_LABELS", "node,instance,hostname")
    monkeypatch.setenv("PROMHIS_METRICS_ALLOWED_IPS", "10.0.0.0/8, 127.0.0.1")

    settings = Settings()

    assert settings.node_labels == ("node", "instance", "hostname")
    assert settings.metrics_allowed_ips == ("10.0.0.0/8", "127.0.0.1")


def test_comma_separated_env_vars_single_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMHIS_NODE_LABELS", "node")
    assert Settings().node_labels == ("node",)


def test_comma_separated_env_vars_default_when_unset() -> None:
    settings = Settings()
    assert settings.node_labels == ("node", "instance", "hostname")
    assert settings.metrics_allowed_ips == ()
