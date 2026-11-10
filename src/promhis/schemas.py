"""Pydantic schemas.

``AlertmanagerWebhook`` mirrors the payload Alertmanager POSTs to a
``webhook_configs`` receiver:
https://prometheus.io/docs/alerting/latest/configuration/#webhook_config

The rest are API response shapes used by the FastAPI routers.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AlertmanagerAlert(BaseModel):
    status: str
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: datetime
    endsAt: datetime | None = None
    generatorURL: str | None = None
    fingerprint: str


class AlertmanagerWebhook(BaseModel):
    version: str | None = None
    groupKey: str | None = None
    truncatedAlerts: int | None = None
    status: str | None = None
    receiver: str | None = None
    groupLabels: dict[str, str] = Field(default_factory=dict)
    commonLabels: dict[str, str] = Field(default_factory=dict)
    commonAnnotations: dict[str, str] = Field(default_factory=dict)
    externalURL: str | None = None
    alerts: list[AlertmanagerAlert] = Field(default_factory=list)


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fingerprint: str
    alertname: str
    status: str
    severity: str | None
    node: str | None
    labels: dict
    annotations: dict
    starts_at: datetime
    ends_at: datetime | None
    generator_url: str | None
    receiver: str | None
    group_key: str | None
    first_seen: datetime
    last_seen: datetime
    ack_note: str | None
    ack_by: str | None
    ack_at: datetime | None


class AlertEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fingerprint: str
    alertname: str
    status: str
    severity: str | None
    node: str | None
    labels: dict
    annotations: dict
    starts_at: datetime
    ends_at: datetime | None
    receiver: str | None
    group_key: str | None
    received_at: datetime


class AlertDetail(AlertRead):
    events: list[AlertEventRead] = Field(default_factory=list)


class Page(BaseModel):
    items: list[AlertRead]
    total: int
    page: int
    page_size: int


class NodeSummary(BaseModel):
    node: str
    firing: int
    resolved: int
    total: int
    last_seen: datetime
    last_alertname: str
    last_severity: str | None


class SeverityCount(BaseModel):
    severity: str
    count: int


class DailyCount(BaseModel):
    day: str
    count: int


class Stats(BaseModel):
    total_alerts: int
    firing: int
    resolved: int
    nodes: int
    by_severity: list[SeverityCount]
    by_day: list[DailyCount]


class AuditLogEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    received_at: datetime
    source_ip: str | None
    user_agent: str | None
    auth_mode: str
    auth_result: str
    status_code: int
    alert_count: int | None
    receiver: str | None
    error_detail: str | None


class AuditLogPage(BaseModel):
    items: list[AuditLogEntryRead]
    total: int
    page: int
    page_size: int
