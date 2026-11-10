"""Alertmanager webhook ingest.

Point an Alertmanager ``webhook_configs`` receiver at ``POST
/api/v1/webhook``. Auth is a pluggable ``WebhookAuthenticator`` (Basic or
Bearer, see ``auth.py``) matching Alertmanager's own native
``http_config.basic_auth``/``http_config.authorization`` support, so it never
needs an interactive session. See ``deploy/alertmanager.yml`` for a worked
example.

Auth is checked here explicitly (not via a dependency that short-circuits)
and every request — accepted or rejected — is recorded in the audit log.
That's the whole point of the audit log: a rejected request (bad auth,
malformed payload) is exactly the case someone needs to debug later.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from promhis import crud
from promhis.auth import get_webhook_authenticator
from promhis.db import get_session
from promhis.metrics import ALERTS_INGESTED_TOTAL, WEBHOOK_REQUESTS_TOTAL
from promhis.notifications.registry import build_registry, matches_routing_rules
from promhis.schemas import AlertmanagerWebhook

router = APIRouter(prefix="/api/v1", tags=["webhook"])


@router.post("/webhook")
async def receive_webhook(request: Request, session: AsyncSession = Depends(get_session)) -> dict[str, int]:
    authenticator = get_webhook_authenticator()
    source_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    authenticated = authenticator.check(request)
    if not authenticated:
        auth_result = "missing" if "authorization" not in request.headers else "failure"
        await crud.record_audit_entry(
            session,
            source_ip=source_ip,
            user_agent=user_agent,
            auth_mode=authenticator.name,
            auth_result=auth_result,
            status_code=401,
            error_detail="missing or invalid webhook credentials",
        )
        WEBHOOK_REQUESTS_TOTAL.labels(auth_result=auth_result, status_code="401").inc()
        raise HTTPException(
            status_code=401,
            detail="Invalid webhook credentials",
            headers={"WWW-Authenticate": authenticator.www_authenticate},
        )

    body = await request.body()
    try:
        payload = AlertmanagerWebhook.model_validate_json(body)
    except ValidationError as exc:
        await crud.record_audit_entry(
            session,
            source_ip=source_ip,
            user_agent=user_agent,
            auth_mode=authenticator.name,
            auth_result="success",
            status_code=400,
            error_detail=f"payload validation failed: {exc.error_count()} error(s)",
        )
        WEBHOOK_REQUESTS_TOTAL.labels(auth_result="success", status_code="400").inc()
        raise HTTPException(status_code=400, detail="Invalid Alertmanager webhook payload") from exc

    events = await crud.ingest_webhook(session, payload)
    await crud.record_audit_entry(
        session,
        source_ip=source_ip,
        user_agent=user_agent,
        auth_mode=authenticator.name,
        auth_result="success",
        status_code=200,
        alert_count=len(events),
        receiver=payload.receiver,
    )
    WEBHOOK_REQUESTS_TOTAL.labels(auth_result="success", status_code="200").inc()
    ALERTS_INGESTED_TOTAL.inc(len(events))

    # Fan out to every configured notification channel whose routing rules
    # match a given event's labels (no rules configured = matches every
    # event, same as before routing rules existed). Each channel's own
    # `send()` never raises (see notifications/base.py's post_json), and
    # `return_exceptions=True` is a second layer of the same guarantee — a
    # bad/slow channel can never fail the webhook response to Alertmanager.
    routes = await build_registry(session)
    if routes:
        await asyncio.gather(
            *(
                channel.send(event)
                for event in events
                for channel, rules in routes.values()
                if matches_routing_rules(event.labels, rules)
            ),
            return_exceptions=True,
        )

    return {"ingested": len(events)}
