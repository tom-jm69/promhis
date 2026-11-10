"""Enterprise feature licensing — entirely offline, no phone-home.

A license file is a small JSON envelope: a base64-encoded JSON payload
(``customer``/``issued_at``/``expires_at``/``features``/``max_users``) plus
a base64-encoded Ed25519 signature over the raw payload bytes, verified
against the public key embedded below. See `docs/licensing.md` for the
exact file format and `license_cli.py` (``promhis-license keygen``/
``issue``) for generating a keypair and issuing a license.

Hard rules (see ROADMAP.md §15/§22): a missing, invalid, malformed, or
expired license is never an error and never blocks startup or ingest — it's
the Free edition, which is the default and fully supported. Feature checks
go through `has_feature(flag)`/`require_feature(flag)` and behave as if the
feature doesn't exist when unlicensed, never crash. Core functionality
(webhook ingest, the poller, the dashboard, unlimited history/retention,
Postgres, the existing free Stats page) is never gated by this module at
all — licensing only touches the small set of features actually listed as
licensed in docs/licensing.md.
"""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import lru_cache
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from promhis.config import settings

logger = logging.getLogger("promhis.licensing")

# Public half of the keypair used to sign Enterprise license files.
#
# THIS IS A DEVELOPMENT KEY, generated for this codebase so tests and local
# license issuance work out of the box. Anyone with the matching private key
# (which is NOT in this repository) can mint a license this app will accept.
# Generate your own keypair with `promhis-license keygen` before issuing any
# real Enterprise license, and replace this constant with your public key —
# never commit the private key it produces.
PUBLIC_KEY_B64 = "ZduvSYngZE4VexFyXDCH2hb5Q5bSp22u0ueL6szOrmI="

# Past `expires_at`, everything keeps working for this long (with an admin
# banner) before licensed features degrade to read-only. See
# docs/licensing.md's "Expiry behavior" section for exactly what "read-only"
# means per feature — this module only exposes the state, not the per-route
# degradation logic, which is a per-feature concern.
GRACE_PERIOD_DAYS = 14


class LicenseState(str, Enum):
    FREE = "free"  # no license, or one that failed to verify
    ACTIVE = "active"
    GRACE = "grace"  # past expires_at, within GRACE_PERIOD_DAYS
    EXPIRED = "expired"  # past the grace period


@dataclass(frozen=True)
class License:
    customer: str
    issued_at: datetime
    expires_at: datetime | None = None
    features: list[str] = field(default_factory=list)
    max_users: int | None = None


@dataclass(frozen=True)
class LicenseStatus:
    state: LicenseState
    license: License | None
    # Diagnostic only (logged, not shown to end users): None when a real
    # license parsed, else "missing"/"malformed"/"invalid_signature".
    reason: str | None = None


def _public_key() -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(PUBLIC_KEY_B64))


def _state_for(lic: License) -> LicenseState:
    if lic.expires_at is None:
        return LicenseState.ACTIVE
    now = datetime.now(timezone.utc)
    if now <= lic.expires_at:
        return LicenseState.ACTIVE
    if now <= lic.expires_at + timedelta(days=GRACE_PERIOD_DAYS):
        return LicenseState.GRACE
    return LicenseState.EXPIRED


def verify_license_file(path: str | Path) -> LicenseStatus:
    path = Path(path)
    if not path.is_file():
        return LicenseStatus(state=LicenseState.FREE, license=None, reason="missing")

    try:
        envelope = json.loads(path.read_text())
        payload_bytes = base64.b64decode(envelope["payload"])
        signature_bytes = base64.b64decode(envelope["signature"])
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("licensing: malformed license file at %s: %s", path, exc)
        return LicenseStatus(state=LicenseState.FREE, license=None, reason="malformed")

    try:
        _public_key().verify(signature_bytes, payload_bytes)
    except InvalidSignature:
        logger.warning("licensing: invalid signature on license file at %s", path)
        return LicenseStatus(state=LicenseState.FREE, license=None, reason="invalid_signature")

    try:
        data = json.loads(payload_bytes)
        issued_at = datetime.fromisoformat(data["issued_at"])
        expires_at = datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None
        lic = License(
            customer=data["customer"],
            issued_at=issued_at,
            expires_at=expires_at,
            features=list(data.get("features", [])),
            max_users=data.get("max_users"),
        )
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("licensing: unreadable license payload at %s: %s", path, exc)
        return LicenseStatus(state=LicenseState.FREE, license=None, reason="malformed")

    return LicenseStatus(state=_state_for(lic), license=lic)


@lru_cache(maxsize=1)
def _cached_status() -> LicenseStatus:
    if not settings.license_file:
        return LicenseStatus(state=LicenseState.FREE, license=None, reason="missing")
    return verify_license_file(settings.license_file)


def get_license_status() -> LicenseStatus:
    """Cached — verified once at startup and re-verified once a day
    thereafter (`main.py`'s `_license_recheck_loop`), not on every request.
    A license crossing from ACTIVE into GRACE/EXPIRED is caught by that
    daily recheck without requiring a restart.
    """
    return _cached_status()


def refresh_license_status() -> LicenseStatus:
    _cached_status.cache_clear()
    return _cached_status()


def has_feature(flag: str) -> bool:
    """True for ACTIVE and GRACE (grace period: "everything keeps working,
    with a banner" per docs/licensing.md) — only EXPIRED (past grace) and
    FREE return False. EXPIRED's "existing X stays viewable, creating new
    ones is disabled" split is a per-feature route concern (a view route
    simply doesn't gate on this at all; a create route does), not something
    this one boolean can express by itself.
    """
    status = get_license_status()
    if status.state not in (LicenseState.ACTIVE, LicenseState.GRACE):
        return False
    if status.license is None:
        return False
    return flag in status.license.features


class FeatureRequiredError(Exception):
    """Raised by `require_feature`'s dependency; caught by an app-wide
    exception handler (`main.py`) that renders a 402 — JSON for `/api/*`
    routes, an upgrade-notice page for dashboard routes.
    """

    def __init__(self, flag: str) -> None:
        self.flag = flag
        super().__init__(f"feature required: {flag}")


def require_feature(flag: str) -> Callable[[], Awaitable[None]]:
    async def _dependency() -> None:
        if not has_feature(flag):
            raise FeatureRequiredError(flag)

    return _dependency
