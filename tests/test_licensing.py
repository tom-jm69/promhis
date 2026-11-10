from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from promhis import licensing
from promhis.config import settings


def _write_license(
    tmp_path: Path,
    private_key: Ed25519PrivateKey,
    *,
    customer: str = "Test Customer",
    expires_at: datetime | None = None,
    features: list[str] | None = None,
    max_users: int | None = None,
) -> Path:
    payload = {
        "customer": customer,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "features": features or [],
        "max_users": max_users,
    }
    payload_bytes = json.dumps(payload).encode()
    signature_bytes = private_key.sign(payload_bytes)
    envelope = {
        "payload": base64.b64encode(payload_bytes).decode(),
        "signature": base64.b64encode(signature_bytes).decode(),
    }
    path = tmp_path / "license.json"
    path.write_text(json.dumps(envelope))
    return path


@pytest.fixture
def test_keypair(monkeypatch: pytest.MonkeyPatch) -> Ed25519PrivateKey:
    """A throwaway keypair, substituted for the app's real embedded public
    key for the duration of the test — so tests can mint a license this
    process will accept as valid without touching the real signing key.
    """
    private_key = Ed25519PrivateKey.generate()
    public_b64 = base64.b64encode(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )
    ).decode()
    monkeypatch.setattr(licensing, "PUBLIC_KEY_B64", public_b64)
    return private_key


@pytest.fixture(autouse=True)
def _reset_license_cache():
    # get_license_status() is lru_cache'd (verified once per process in the
    # real app) — tests need a fresh read every time settings.license_file
    # or the embedded public key changes, in either direction.
    licensing._cached_status.cache_clear()  # pyright: ignore[reportPrivateUsage]
    yield
    licensing._cached_status.cache_clear()  # pyright: ignore[reportPrivateUsage]


def test_missing_license_file_is_free(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "license_file", None)
    status = licensing.get_license_status()
    assert status.state == licensing.LicenseState.FREE
    assert status.reason == "missing"


def test_nonexistent_path_is_free(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "license_file", "/nonexistent/path/license.json")
    status = licensing.get_license_status()
    assert status.state == licensing.LicenseState.FREE
    assert status.reason == "missing"


def test_valid_license_is_active(
    tmp_path: Path, test_keypair: Ed25519PrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_license(tmp_path, test_keypair, customer="Acme Corp", features=["sso", "rbac"])
    monkeypatch.setattr(settings, "license_file", str(path))
    status = licensing.get_license_status()
    assert status.state == licensing.LicenseState.ACTIVE
    assert status.license is not None
    assert status.license.customer == "Acme Corp"
    assert status.license.features == ["sso", "rbac"]


def test_tampered_signature_is_free(
    tmp_path: Path, test_keypair: Ed25519PrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Sign with one key, then swap in a *different* key as "the" public key
    # — simulates a license forged without the real private key.
    path = _write_license(tmp_path, test_keypair)
    other_key = Ed25519PrivateKey.generate()
    other_public_b64 = base64.b64encode(
        other_key.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    ).decode()
    monkeypatch.setattr(licensing, "PUBLIC_KEY_B64", other_public_b64)
    monkeypatch.setattr(settings, "license_file", str(path))
    status = licensing.get_license_status()
    assert status.state == licensing.LicenseState.FREE
    assert status.reason == "invalid_signature"


def test_malformed_file_is_free(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "license.json"
    path.write_text("not json at all")
    monkeypatch.setattr(settings, "license_file", str(path))
    status = licensing.get_license_status()
    assert status.state == licensing.LicenseState.FREE
    assert status.reason == "malformed"


def test_recent_expiry_is_grace(
    tmp_path: Path, test_keypair: Ed25519PrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    expired_yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    path = _write_license(tmp_path, test_keypair, expires_at=expired_yesterday, features=["rbac"])
    monkeypatch.setattr(settings, "license_file", str(path))
    status = licensing.get_license_status()
    assert status.state == licensing.LicenseState.GRACE
    assert status.license is not None  # still parsed


def test_expiry_past_grace_period_is_expired(
    tmp_path: Path, test_keypair: Ed25519PrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    long_expired = datetime.now(timezone.utc) - timedelta(days=licensing.GRACE_PERIOD_DAYS + 1)
    path = _write_license(tmp_path, test_keypair, expires_at=long_expired)
    monkeypatch.setattr(settings, "license_file", str(path))
    status = licensing.get_license_status()
    assert status.state == licensing.LicenseState.EXPIRED


def test_future_expiry_is_active(
    tmp_path: Path, test_keypair: Ed25519PrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    future = datetime.now(timezone.utc) + timedelta(days=365)
    path = _write_license(tmp_path, test_keypair, expires_at=future)
    monkeypatch.setattr(settings, "license_file", str(path))
    assert licensing.get_license_status().state == licensing.LicenseState.ACTIVE


def test_has_feature_true_only_when_flag_listed_and_active(
    tmp_path: Path, test_keypair: Ed25519PrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_license(tmp_path, test_keypair, features=["sso"])
    monkeypatch.setattr(settings, "license_file", str(path))
    assert licensing.has_feature("sso") is True
    assert licensing.has_feature("rbac") is False  # licensed, but not in this license's feature list


def test_has_feature_false_on_free(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "license_file", None)
    assert licensing.has_feature("sso") is False


def test_has_feature_true_during_grace_period(
    tmp_path: Path, test_keypair: Ed25519PrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    # docs/licensing.md: "14-day grace period after expires_at: everything
    # keeps working" — has_feature must stay True during grace, not just ACTIVE.
    expired_yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    path = _write_license(tmp_path, test_keypair, expires_at=expired_yesterday, features=["rbac"])
    monkeypatch.setattr(settings, "license_file", str(path))
    assert licensing.has_feature("rbac") is True


def test_has_feature_false_once_past_grace_period(
    tmp_path: Path, test_keypair: Ed25519PrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    long_expired = datetime.now(timezone.utc) - timedelta(days=licensing.GRACE_PERIOD_DAYS + 1)
    path = _write_license(tmp_path, test_keypair, expires_at=long_expired, features=["rbac"])
    monkeypatch.setattr(settings, "license_file", str(path))
    assert licensing.has_feature("rbac") is False


def test_refresh_license_status_picks_up_a_newly_installed_license(
    tmp_path: Path, test_keypair: Ed25519PrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "license_file", None)
    assert licensing.get_license_status().state == licensing.LicenseState.FREE

    path = _write_license(tmp_path, test_keypair)
    monkeypatch.setattr(settings, "license_file", str(path))
    # Without refresh_license_status(), the FREE result above would stay cached.
    assert licensing.refresh_license_status().state == licensing.LicenseState.ACTIVE
