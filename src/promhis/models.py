"""Database models.

Two tables:

- ``Alert``: current known state of a distinct alert, keyed by Alertmanager's
  fingerprint. Upserted on every webhook delivery.
- ``AlertEvent``: an append-only log of every status transition seen for a
  fingerprint (firing -> resolved -> firing again, ...). This is what gives
  us "history" rather than just a live table.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import JSON, Column, Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Alert(SQLModel, table=True):
    """Latest known state of an alert, one row per Alertmanager fingerprint."""

    fingerprint: str = Field(primary_key=True)

    alertname: str = Field(index=True)
    status: str = Field(index=True)  # "firing" | "resolved"
    severity: str | None = Field(default=None, index=True)
    node: str | None = Field(default=None, index=True)

    labels: dict = Field(default_factory=dict, sa_column=Column(JSON))
    annotations: dict = Field(default_factory=dict, sa_column=Column(JSON))

    starts_at: datetime
    ends_at: datetime | None = None

    generator_url: str | None = None
    receiver: str | None = None
    group_key: str | None = Field(default=None, index=True)

    first_seen: datetime = Field(default_factory=utcnow)
    last_seen: datetime = Field(default_factory=utcnow)

    # Lightweight acknowledgment — not a silence, just "someone's looking at
    # this" so two people on a shared login don't duplicate work. Cleared
    # (all three set back to None) rather than deleted-and-recreated.
    ack_note: str | None = None
    ack_by: str | None = None
    ack_at: datetime | None = None


class AlertEvent(SQLModel, table=True):
    """One row per webhook alert entry ever received, i.e. the history log."""

    id: int | None = Field(default=None, primary_key=True)
    fingerprint: str = Field(index=True)

    alertname: str = Field(index=True)
    status: str = Field(index=True)
    severity: str | None = Field(default=None, index=True)
    node: str | None = Field(default=None, index=True)

    labels: dict = Field(default_factory=dict, sa_column=Column(JSON))
    annotations: dict = Field(default_factory=dict, sa_column=Column(JSON))

    starts_at: datetime
    ends_at: datetime | None = None

    receiver: str | None = None
    group_key: str | None = Field(default=None, index=True)
    received_at: datetime = Field(default_factory=utcnow, index=True)


class AuditLogEntry(SQLModel, table=True):
    """One row per request to the webhook ingest endpoint — accepted or
    rejected. This is what lets you answer "why isn't Alertmanager reaching
    Promhis" (bad auth, wrong URL, malformed payload) and "who/what is
    actually hitting this endpoint" after the fact.
    """

    id: int | None = Field(default=None, primary_key=True)
    received_at: datetime = Field(default_factory=utcnow, index=True)

    source_ip: str | None = None
    user_agent: str | None = None

    auth_mode: str  # "basic" | "bearer" — whichever scheme was configured/attempted
    auth_result: str = Field(index=True)  # "success" | "failure" | "missing"

    status_code: int
    alert_count: int | None = None
    receiver: str | None = None
    error_detail: str | None = None


class ApiToken(SQLModel, table=True):
    """A read-only API token, for pulling data into Grafana/other internal
    tooling without sharing the dashboard login. Only the hash is stored —
    the raw token is shown once, at creation, and never again.
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str
    token_hash: str = Field(unique=True, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    last_used_at: datetime | None = None
    revoked: bool = Field(default=False, index=True)


class NotificationIntegration(SQLModel, table=True):
    """A configured notification channel, set up through the dashboard's
    Integrations page — see routers/integrations.py. Replaces the env-var
    based configuration notifications/ originally shipped with.
    """

    id: int | None = Field(default=None, primary_key=True)
    channel_type: str = Field(index=True)  # matches a NotificationChannel.name
    enabled: bool = Field(default=True)
    config: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # Label-match conditions gating which alerts reach this integration, e.g.
    # [{"label": "env", "value": "production"}] — ANDed together. Empty list
    # (the default) means "every alert", preserving the original
    # dispatch-to-everyone behavior. See notifications/registry.py.
    routing_rules: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AlertAnnotation(SQLModel, table=True):
    """A postmortem/incident note on an alert (the `annotations` licensed
    feature, ROADMAP.md §22/§23) — distinct from `Alert.ack_note` (a single,
    overwritable "someone's looking at this" flag) and from the Alertmanager
    payload's own `Alert.annotations` dict (arbitrary labels Alertmanager
    sends us, rendered read-only on the detail page). This is an append-only
    list of timestamped notes a team leaves for a postmortem, one alert can
    have many. Immutable once created — no edit, only delete — matching the
    project's append-only-history philosophy for `AlertEvent`; correcting a
    note means deleting and adding a new one, not silently rewriting history.
    """

    id: int | None = Field(default=None, primary_key=True)
    fingerprint: str = Field(index=True)
    author: str
    body: str
    created_at: datetime = Field(default_factory=utcnow, index=True)


class AppSetting(SQLModel, table=True):
    """A small set of operational settings editable at runtime from the
    dashboard's Settings page (`routers/settings.py`) without a restart —
    currently just `/metrics` scrape-endpoint auth (IP allowlist + Basic
    credentials). Unlike the rest of `config.Settings` (env-only, read once
    at process start), these can change while the app is running.

    An env var always wins when set (see `auth.metrics_setting_env_locked`)
    — same "env is the durable source of truth" precedent as the bootstrap
    admin (`crud.sync_bootstrap_admin`). A row here only takes effect when
    its matching `PROMHIS_METRICS_*` env var is absent.
    """

    key: str = Field(primary_key=True)
    value: str | None = None
    updated_at: datetime = Field(default_factory=utcnow)


class User(SQLModel, table=True):
    """An admin dashboard account (ROADMAP.md §21).

    `is_bootstrap` marks the single account mirrored from
    `PROMHIS_ADMIN_USER`/`PROMHIS_ADMIN_PASSWORD` at every startup (see
    `crud.sync_bootstrap_admin`) — it exists so an existing self-hosted
    install upgrading to this version keeps logging in exactly the same way
    it always has, with zero config changes. The Free tier is hard-capped
    at one admin user (the bootstrap account); the `rbac` feature licensed
    can create more via the Admin Users page.
    """

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    is_bootstrap: bool = Field(default=False, index=True)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)
    last_login_at: datetime | None = None
