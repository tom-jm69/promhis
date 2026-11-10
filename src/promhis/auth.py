"""Authentication.

Two separate gates, matching how the two kinds of caller reach this service:

- Human dashboard pages: a signed session cookie set by ``/login``, checked
  by ``require_login``/``require_login_api`` (FastAPI dependencies).
- The machine-facing webhook ingest endpoint: a pluggable
  ``WebhookAuthenticator`` (Basic or Bearer, selected by
  ``PROMHIS_WEBHOOK_AUTH_MODE``) — this is what Alertmanager's own
  ``webhook_configs.http_config`` sends (``basic_auth`` or
  ``authorization.credentials``), so Alertmanager never needs an interactive
  session. Auth is checked explicitly inside the webhook route (not via a
  dependency that short-circuits) so that both accepted *and* rejected
  requests can be recorded in the audit log — see ``routers/webhook.py``.

Credentials are single-user, configured via environment variables. There is
no user database — this is an internal tool behind one shared login.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import os
import secrets
from typing import Protocol

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from promhis import crud
from promhis.config import settings
from promhis.db import get_session

SESSION_KEY = "promhis_user"


def _constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(hashlib.sha256(a.encode()).digest(), hashlib.sha256(b.encode()).digest())


def verify_credentials(username: str, password: str) -> bool:
    return _constant_time_eq(username, settings.admin_user) and _constant_time_eq(password, settings.admin_password)


# PBKDF2-HMAC-SHA256 for the User table (ROADMAP.md §21) — no new dependency
# (stdlib `hashlib`), and still an accepted choice at a high iteration count.
# `verify_credentials` above doesn't hash anything (it only ever compares
# against the live PROMHIS_ADMIN_PASSWORD value), which doesn't extend to
# multiple stored accounts — this is the real thing for actual stored users.
_PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, digest = stored_hash.split("$", 1)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS).hex()
    return hmac.compare_digest(candidate, digest)


def require_login(request: Request) -> str:
    """Dashboard pages: redirect the browser to /login when unauthenticated."""
    user = request.session.get(SESSION_KEY)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": f"/login?next={request.url.path}"},
        )
    return user


def require_login_api(request: Request) -> str:
    """JSON API routes backing the dashboard: plain 401, no redirect."""
    user = request.session.get(SESSION_KEY)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def generate_api_token() -> str:
    return "promhis_" + secrets.token_urlsafe(32)


def hash_api_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def require_token_or_login(
    request: Request, session: AsyncSession = Depends(get_session)
) -> str:
    """The read-only `/api/v1/{alerts,nodes,stats}` routes accept either the
    dashboard session cookie (for the dashboard's own fetches) or a
    read-only API token (for external tooling, e.g. Grafana) — not the
    webhook endpoint's Basic/Bearer scheme, which is a different audience.
    The audit log stays session-only; it's more sensitive, admin-facing data.

    Every admin can create any number of read-only API tokens — what a given
    token can reach is decided by the token's own type/scope, not by this
    endpoint-level check.
    """
    user = request.session.get(SESSION_KEY)
    if user:
        return user

    header = request.headers.get("authorization", "")
    if header.startswith("Bearer "):
        raw_token = header[len("Bearer ") :]
        token = await crud.verify_api_token(session, hash_api_token(raw_token))
        if token is not None:
            return f"token:{token.name}"

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


_METRICS_ENV_VARS = {
    "metrics_enabled": "PROMHIS_METRICS_ENABLED",
    "metrics_user": "PROMHIS_METRICS_USER",
    "metrics_password": "PROMHIS_METRICS_PASSWORD",
    "metrics_allowed_ips": "PROMHIS_METRICS_ALLOWED_IPS",
}


def metrics_setting_env_locked(key: str) -> bool:
    """True if the matching `PROMHIS_METRICS_*` var is set in the real
    process environment (`os.environ`, not `config.settings` — a `Settings`
    field can't tell a real override from its own default). `routers/
    settings.py` shows that field read-only in that case, and the
    `effective_metrics_*` functions below always prefer the env value —
    same "env is the durable source of truth" precedent as the bootstrap
    admin (`crud.sync_bootstrap_admin`).
    """
    return _METRICS_ENV_VARS[key] in os.environ


async def effective_metrics_enabled(session: AsyncSession) -> bool:
    if metrics_setting_env_locked("metrics_enabled"):
        return settings.metrics_enabled
    raw = await crud.get_app_setting(session, "metrics_enabled")
    if raw is None:
        return True  # unset means on, same as config.py's default
    return raw == "true"


async def effective_metrics_user(session: AsyncSession) -> str | None:
    if metrics_setting_env_locked("metrics_user"):
        return settings.metrics_user
    return await crud.get_app_setting(session, "metrics_user")


async def effective_metrics_password(session: AsyncSession) -> str | None:
    if metrics_setting_env_locked("metrics_password"):
        return settings.metrics_password
    return await crud.get_app_setting(session, "metrics_password")


async def effective_metrics_allowed_ips(session: AsyncSession) -> tuple[str, ...]:
    if metrics_setting_env_locked("metrics_allowed_ips"):
        return settings.metrics_allowed_ips
    raw = await crud.get_app_setting(session, "metrics_allowed_ips")
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _metrics_client_ip_allowed(request: Request, allowed_ips: tuple[str, ...]) -> bool:
    """True if `allowed_ips` is empty (no restriction) or the request's
    client IP matches one of its entries (plain IPs or CIDRs).
    """
    if not allowed_ips:
        return True
    client = request.client
    if client is None:
        return False
    try:
        addr = ipaddress.ip_address(client.host)
    except ValueError:
        return False
    for entry in allowed_ips:
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            continue
        if addr in network:
            return True
    return False


async def require_metrics_auth(request: Request, session: AsyncSession = Depends(get_session)) -> None:
    """Gates `GET /metrics`: can be disabled outright, and/or restricted by
    an IP allowlist and/or HTTP Basic auth — all configurable either via
    `PROMHIS_METRICS_*` env vars or at runtime from the dashboard's Settings
    page (`routers/settings.py`, `AppSetting` rows), independent of the
    dashboard session cookie and the webhook's own Basic/Bearer scheme.
    Nothing configured (the default) means the endpoint stays open, same
    posture as /healthz.
    """
    if not await effective_metrics_enabled(session):
        # 404, not 403: a disabled endpoint should look like it was never
        # routed at all, same "cleanly absent" posture as /brand/logo when
        # branding isn't configured — not "it exists but you're forbidden."
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    allowed_ips = await effective_metrics_allowed_ips(session)
    if not _metrics_client_ip_allowed(request, allowed_ips):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Client IP not allowed")

    metrics_user = await effective_metrics_user(session)
    metrics_password = await effective_metrics_password(session)
    if metrics_user and metrics_password:
        header = request.headers.get("authorization", "")
        username = password = ""
        if header.startswith("Basic "):
            try:
                decoded = base64.b64decode(header[len("Basic ") :]).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError):
                decoded = ""
            username, _, password = decoded.partition(":")
        valid = _constant_time_eq(username, metrics_user) and _constant_time_eq(password, metrics_password)
        if not valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid metrics credentials",
                headers={"WWW-Authenticate": "Basic"},
            )


class WebhookAuthenticator(Protocol):
    """One scheme for authenticating the Alertmanager-facing webhook.

    Adding a new scheme means implementing this + a registry entry below —
    nothing in routers/webhook.py changes.
    """

    name: str
    www_authenticate: str

    def check(self, request: Request) -> bool:
        """True if `request` carries valid credentials for this scheme."""
        ...


class BasicAuthenticator:
    """HTTP Basic — matches Alertmanager's ``http_config.basic_auth``."""

    name = "basic"
    www_authenticate = "Basic"

    def check(self, request: Request) -> bool:
        header = request.headers.get("authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[len("Basic ") :]).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return False
        username, _, password = decoded.partition(":")
        return verify_credentials(username, password)


class BearerAuthenticator:
    """Bearer token — matches Alertmanager's ``http_config.authorization``.

    A single rotatable token, for users who'd rather manage one secret than
    a username/password pair.
    """

    name = "bearer"
    www_authenticate = "Bearer"

    def check(self, request: Request) -> bool:
        if not settings.webhook_token:
            return False
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            return False
        token = header[len("Bearer ") :]
        return _constant_time_eq(token, settings.webhook_token)


WEBHOOK_AUTHENTICATORS: dict[str, WebhookAuthenticator] = {
    "basic": BasicAuthenticator(),
    "bearer": BearerAuthenticator(),
}


def get_webhook_authenticator() -> WebhookAuthenticator:
    return WEBHOOK_AUTHENTICATORS.get(settings.webhook_auth_mode, WEBHOOK_AUTHENTICATORS["basic"])


def generate_secret_key() -> str:
    return secrets.token_urlsafe(32)
