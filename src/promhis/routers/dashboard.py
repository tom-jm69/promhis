"""Server-rendered dashboard pages."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import FormData

from promhis import crud, insights
from promhis.auth import SESSION_KEY, generate_api_token, hash_api_token, require_login, verify_password
from promhis.db import get_session
from promhis.licensing import has_feature
from promhis.models import AlertEvent, ApiToken, NotificationIntegration
from promhis.notifications.base import mask_secret, raise_send_errors
from promhis.notifications.registry import CHANNEL_CLASSES
from promhis.templating import templates

NEW_TOKEN_SESSION_KEY = "promhis_new_api_token"
TEST_RESULT_SESSION_KEY = "promhis_integration_test_result"

# A fixed, small number of label=value rows on the routing-rules editor —
# deliberately not a dynamic add/remove UI (see ROADMAP.md §14: "simple
# key/value rows, not a full expression language").
ROUTING_RULE_SLOTS = 4

router = APIRouter(tags=["dashboard"])


def wants_partial(request: Request) -> bool:
    """True for a targeted htmx call (filter/sort/pagination/row-update)
    that wants just its panel back. False for a *boosted* nav-tab click
    (hx-boost on .rail-nav, base.html) — those also carry HX-Request, but
    need the full page back since htmx swaps the whole <body> from it.
    """
    return bool(request.headers.get("HX-Request")) and not request.headers.get("HX-Boosted")


@router.get("/login", response_model=None)
async def login_page(request: Request, next: str = "/") -> HTMLResponse | RedirectResponse:
    if request.session.get(SESSION_KEY):
        return RedirectResponse(url=next, status_code=303)
    return templates.TemplateResponse(request, "login.html", {"next": next, "error": None})


@router.post("/login", response_model=None)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    # Dashboard login checks the User table (ROADMAP.md §21), not the live
    # env-var value directly — the bootstrap admin is always a row in that
    # table (kept in sync at startup by `crud.sync_bootstrap_admin`), so an
    # existing self-hosted install still logs in with the same credentials
    # it always has. Webhook ingest auth (`auth.BasicAuthenticator`) is a
    # separate, unrelated gate and is untouched — it still checks
    # `PROMHIS_ADMIN_USER`/`PROMHIS_ADMIN_PASSWORD` directly, as documented.
    user = await crud.get_user_by_username(session, username)
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"next": next, "error": "Invalid username or password."},
            status_code=401,
        )
    await crud.record_login(session, user)
    request.session[SESSION_KEY] = user.username
    return RedirectResponse(url=next or "/", status_code=303)


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.pop(SESSION_KEY, None)
    return RedirectResponse(url="/login", status_code=303)


@router.get("/", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def overview(request: Request, session: AsyncSession = Depends(get_session)) -> HTMLResponse:
    stats = await crud.dashboard_stats(session)
    recent, _ = await crud.list_alerts(session, page=1, page_size=12)
    last_ingest = await crud.last_successful_ingest(session)
    # 24h is a conservative "something's probably wrong" threshold, not a
    # heartbeat SLA — Alertmanager only sends when something changes, so
    # quiet infra can legitimately go a while between deliveries.
    ingest_stale = last_ingest is not None and (datetime.now(timezone.utc) - last_ingest) > timedelta(hours=24)
    mttr = await crud.mttr_seconds(session)
    top_noisy = await crud.top_noisy_alerts(session)
    # "Fresh instance" = never received a webhook at all, not just zero
    # current alerts — a self-hosted install that's been running a while and
    # happens to be fully resolved shouldn't see first-run onboarding again.
    show_onboarding = last_ingest is None
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "stats": stats,
            "stats_json": stats.model_dump_json(),
            "recent": recent,
            "last_ingest": last_ingest,
            "ingest_stale": ingest_stale,
            "mttr": mttr,
            "top_noisy": top_noisy,
            "show_onboarding": show_onboarding,
            # Free tier's one admin slot is always filled by the bootstrap
            # admin from the first startup onward, so "invite a teammate"
            # is only ever actionable with an `rbac` license — never a dead
            # end, never gated on a slot count that can't exist on free tier.
            "can_invite_teammate": has_feature("rbac"),
            "active": "overview",
        },
    )


@router.get("/partials/recent-alerts", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def recent_alerts_partial(request: Request, session: AsyncSession = Depends(get_session)) -> HTMLResponse:
    recent, _ = await crud.list_alerts(session, page=1, page_size=12)
    return templates.TemplateResponse(request, "partials/alerts_rows.html", {"alerts": recent})


@router.get("/alerts", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def alerts_page(
    request: Request,
    status: str | None = None,
    severity: str | None = None,
    node: str | None = None,
    search: str | None = None,
    group: str | None = None,
    sort: str = "-last_seen",
    page: int = 1,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    page_size = 25
    items, total = await crud.list_alerts(
        session,
        status=status or None,
        severity=severity or None,
        node=node or None,
        search=search or None,
        group=group or None,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    node_names = await crud.list_node_names(session)
    context = {
        "alerts": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_next": page * page_size < total,
        "has_prev": page > 1,
        "filters": {"status": status or "", "severity": severity or "", "node": node or "", "search": search or ""},
        "node_names": node_names,
        "group": group or "",
        "sort": sort,
        "active": "alerts",
    }
    if wants_partial(request):
        return templates.TemplateResponse(request, "partials/alerts_table.html", context)
    return templates.TemplateResponse(request, "alerts.html", context)


@router.get("/alerts/{fingerprint}", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def alert_detail_page(
    request: Request, fingerprint: str, page: int = 1, session: AsyncSession = Depends(get_session)
) -> HTMLResponse:
    alert = await crud.get_alert(session, fingerprint)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    page_size = 50
    events, total = await crud.get_alert_events_page(session, fingerprint, page=page, page_size=page_size)
    group_siblings = 0
    if alert.group_key:
        group_siblings = await crud.group_siblings_count(session, alert.group_key, fingerprint)
    flaps = await crud.flap_count(session, fingerprint)
    notes = await crud.list_annotations(session, fingerprint)
    context = {
        "alert": alert,
        "events": events,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_next": page * page_size < total,
        "has_prev": page > 1,
        "group_siblings": group_siblings,
        "flaps": flaps,
        "fingerprint": fingerprint,
        "notes": notes,
        "can_annotate": has_feature("annotations"),
        "active": "alerts",
    }
    if wants_partial(request):
        return templates.TemplateResponse(request, "partials/alert_ledger.html", context)
    return templates.TemplateResponse(request, "alert_detail.html", context)


@router.post("/alerts/{fingerprint}/ack", response_model=None, dependencies=[Depends(require_login)])
async def alert_ack_submit(
    request: Request,
    fingerprint: str,
    note: str = Form(""),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    by = request.session.get(SESSION_KEY, "unknown")
    alert = await crud.set_alert_ack(session, fingerprint, note=note, by=by)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    if wants_partial(request):
        return templates.TemplateResponse(request, "partials/ack_panel.html", {"alert": alert})
    return RedirectResponse(url=f"/alerts/{fingerprint}", status_code=303)


@router.get("/nodes", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def nodes_page(
    request: Request, sort: str = "-last_seen", session: AsyncSession = Depends(get_session)
) -> HTMLResponse:
    nodes = await crud.list_nodes(session, sort=sort)
    context = {"nodes": nodes, "sort": sort, "active": "nodes"}
    if wants_partial(request):
        return templates.TemplateResponse(request, "partials/nodes_panel.html", context)
    return templates.TemplateResponse(request, "nodes.html", context)


@router.get("/nodes/{node}", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def node_detail_page(request: Request, node: str, session: AsyncSession = Depends(get_session)) -> HTMLResponse:
    events = await crud.node_alert_history(session, node)
    nodes = await crud.list_nodes(session)
    summary = next((n for n in nodes if n.node == node), None)
    return templates.TemplateResponse(
        request,
        "node_detail.html",
        {"node": node, "events": events, "summary": summary, "active": "nodes"},
    )


@router.get("/audit-log", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def audit_log_page(
    request: Request,
    outcome: str | None = None,
    page: int = 1,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    page_size = 50
    entries, total = await crud.list_audit_log(session, outcome=outcome or None, page=page, page_size=page_size)
    context = {
        "entries": entries,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_next": page * page_size < total,
        "has_prev": page > 1,
        "outcome": outcome or "",
        "active": "audit-log",
    }
    if wants_partial(request):
        return templates.TemplateResponse(request, "partials/audit_log_panel.html", context)
    return templates.TemplateResponse(request, "audit_log.html", context)



API_TOKEN_LIMIT_MESSAGE = (
    "Free tier allows one active API token — revoke it to create a new one, "
    "or a service_tokens license to create more."
)


@router.get("/api-tokens", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def api_tokens_page(request: Request, session: AsyncSession = Depends(get_session)) -> HTMLResponse:
    # One personal read-only token is free for every admin (docs/licensing.md)
    # — this page is never locked. `service_tokens` only raises the active-token
    # cap past one; it doesn't gate the feature's existence.
    tokens = await crud.list_api_tokens(session)
    active_count = await crud.count_active_api_tokens(session)
    # Shown once, immediately after creation, then discarded — never stored
    # anywhere the raw token could be read back later.
    new_token = request.session.pop(NEW_TOKEN_SESSION_KEY, None)
    return templates.TemplateResponse(
        request,
        "api_tokens.html",
        {
            "tokens": tokens,
            "new_token": new_token,
            "at_free_limit": active_count >= 1 and not has_feature("service_tokens"),
            "active": "api-tokens",
        },
    )


@router.post("/api-tokens", response_model=None, dependencies=[Depends(require_login)])
async def create_api_token_submit(
    request: Request, name: str = Form(...), session: AsyncSession = Depends(get_session)
) -> HTMLResponse | RedirectResponse:
    active_count = await crud.count_active_api_tokens(session)
    if active_count >= 1 and not has_feature("service_tokens"):
        raise HTTPException(status_code=402, detail=API_TOKEN_LIMIT_MESSAGE)
    raw_token = generate_api_token()
    await crud.create_api_token(session, name=name.strip() or "unnamed", token_hash=hash_api_token(raw_token))
    if wants_partial(request):
        tokens = await crud.list_api_tokens(session)
        new_active_count = await crud.count_active_api_tokens(session)
        return templates.TemplateResponse(
            request,
            "partials/api_tokens_panel.html",
            {
                "tokens": tokens,
                "new_token": raw_token,
                "at_free_limit": new_active_count >= 1 and not has_feature("service_tokens"),
            },
        )
    request.session[NEW_TOKEN_SESSION_KEY] = raw_token
    return RedirectResponse(url="/api-tokens", status_code=303)


@router.post("/api-tokens/{token_id}/revoke", response_model=None, dependencies=[Depends(require_login)])
async def revoke_api_token_submit(
    token_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> HTMLResponse | RedirectResponse:
    await crud.revoke_api_token(session, token_id)
    if wants_partial(request):
        token = await session.get(ApiToken, token_id)
        if token is None:
            raise HTTPException(status_code=404, detail="Token not found")
        return templates.TemplateResponse(request, "partials/api_token_row.html", {"t": token})
    return RedirectResponse(url="/api-tokens", status_code=303)


@router.get("/stats", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def stats_page(
    request: Request, range: str = "7d", session: AsyncSession = Depends(get_session)
) -> HTMLResponse:
    delta = insights.resolve_range(range)
    since = datetime.now(timezone.utc) - delta if delta else None

    # Each of these is its own bounded query — SQL-side aggregation for the
    # day/node breakdowns, a LIMIT for the raw browser, a COUNT(*) for the
    # header — instead of fetching every event in range into Python and
    # slicing/counting/crunching it here, which used to mean "All time" on a
    # long-lived install pulled the entire event table into memory on every
    # page load.
    daily = await crud.daily_status_counts(session, since=since)
    severity_trend = await crud.severity_by_day(session, since=since)
    top_nodes = await crud.top_nodes_by_volume(session, since=since)
    mttr_events = await crud.resolved_events_for_mttr_trend(session, since=since)
    mttr_trend = insights.mttr_weekly_trend(mttr_events)
    event_count = await crud.event_count_in_range(session, since=since)
    recent_events = await crud.recent_events_in_range(session, since=since, limit=200)

    data = {
        "daily": daily,
        "severity_trend": severity_trend,
        "mttr_trend": mttr_trend,
    }
    context = {
        "range": range,
        "events": recent_events,
        "event_count": event_count,
        "top_nodes": top_nodes,
        "mttr_trend": mttr_trend,
        "data_json": json.dumps(data),
        "active": "stats",
    }
    if wants_partial(request):
        return templates.TemplateResponse(request, "partials/stats_panel.html", context)
    return templates.TemplateResponse(request, "stats.html", context)


def _integration_field_prefix(channel_type: str, field_name: str) -> str:
    # Several channel types share a field name (e.g. "webhook_url" for
    # Slack/Discord/Teams/custom-webhook) — the add-integration form renders
    # one fieldset per type in the same <form>, so inputs need a
    # type-qualified name to avoid colliding on submit.
    return f"cfg_{channel_type}_{field_name}"


def _parse_routing_rules(form: FormData) -> list[dict[str, str]]:
    # A slot only counts as a rule when both the label and value are filled
    # in — a half-filled row is treated as not-yet-a-rule rather than an
    # error.
    rules: list[dict[str, str]] = []
    for i in range(ROUTING_RULE_SLOTS):
        label = str(form.get(f"rule_label_{i}", "")).strip()
        value = str(form.get(f"rule_value_{i}", "")).strip()
        if label and value:
            rules.append({"label": label, "value": value})
    return rules


def _test_event() -> AlertEvent:
    return AlertEvent(
        fingerprint="promhis-test-notification",
        alertname="PromhisTestAlert",
        status="firing",
        severity="info",
        node=None,
        labels={"alertname": "PromhisTestAlert"},
        annotations={"summary": "This is a test notification from Promhis — not a real alert."},
        starts_at=datetime.now(timezone.utc),
        ends_at=None,
        receiver="promhis-test",
    )


def _build_integration_row(integration: NotificationIntegration) -> dict:
    channel_class = CHANNEL_CLASSES.get(integration.channel_type)
    fields = channel_class.fields if channel_class else []
    display_name = channel_class.display_name if channel_class else integration.channel_type
    icon_svg = channel_class.icon_svg if channel_class else None
    masked_config = [
        {
            "name": field["name"],
            "label": field["label"],
            "value": mask_secret(integration.config.get(field["name"], "")) if field["secret"] else integration.config.get(field["name"], ""),
        }
        for field in fields
    ]
    # Pad/truncate to ROUTING_RULE_SLOTS so the /routing tab's editor always
    # has a fixed number of label/value row inputs to prefill, existing or
    # not. `muted` flags every empty slot past the first one immediately
    # following the filled rows — a presentation-only hint ("fill top to
    # bottom") on an otherwise fully usable input; it does not change which
    # slots accept input or how they're parsed.
    existing_rules = integration.routing_rules or []
    rule_slots = [
        {**existing_rules[i], "muted": False}
        if i < len(existing_rules)
        else {"label": "", "value": "", "muted": i > len(existing_rules)}
        for i in range(ROUTING_RULE_SLOTS)
    ]
    return {
        "integration": integration,
        "display_name": display_name,
        "icon_svg": icon_svg,
        "fields": fields,
        "masked_config": masked_config,
        "rule_slots": rule_slots,
        # Unpadded, for the Routing tab's at-a-glance summary chips.
        "routing_rules": existing_rules,
    }


@router.get("/integrations", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def integrations_page(request: Request, session: AsyncSession = Depends(get_session)) -> HTMLResponse:
    integrations = await crud.list_integrations(session)
    channel_types = [
        {
            "key": key,
            "display_name": channel_class.display_name,
            "fields": channel_class.fields,
            "icon_svg": channel_class.icon_svg,
        }
        for key, channel_class in CHANNEL_CLASSES.items()
    ]
    test_result = request.session.pop(TEST_RESULT_SESSION_KEY, None)
    rows = [_build_integration_row(integration) for integration in integrations]
    return templates.TemplateResponse(
        request,
        "integrations.html",
        {
            "rows": rows,
            "channel_types": channel_types,
            "field_prefix": _integration_field_prefix,
            "test_result": test_result,
            "active": "integrations",
        },
    )


@router.post("/integrations", response_model=None, dependencies=[Depends(require_login)])
async def create_integration_submit(
    request: Request, session: AsyncSession = Depends(get_session)
) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    channel_type = str(form.get("channel_type", ""))
    channel_class = CHANNEL_CLASSES.get(channel_type)
    if channel_class is None:
        raise HTTPException(status_code=400, detail="Unknown channel type")
    config = {}
    for field in channel_class.fields:
        value = str(form.get(_integration_field_prefix(channel_type, field["name"]), "")).strip()
        if value:
            config[field["name"]] = value
    # Routing is assigned separately on the /routing tab — a newly created
    # integration starts unscoped (receives everything) until configured there.
    await crud.create_integration(session, channel_type=channel_type, config=config)
    if wants_partial(request):
        integrations = await crud.list_integrations(session)
        rows = [_build_integration_row(integration) for integration in integrations]
        return templates.TemplateResponse(
            request, "partials/integrations_rows.html", {"rows": rows, "field_prefix": _integration_field_prefix}
        )
    return RedirectResponse(url="/integrations", status_code=303)


@router.get("/routing", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def routing_page(request: Request, session: AsyncSession = Depends(get_session)) -> HTMLResponse:
    integrations = await crud.list_integrations(session)
    label_keys = await crud.distinct_label_keys(session)
    rows = [_build_integration_row(integration) for integration in integrations]
    return templates.TemplateResponse(
        request,
        "routing.html",
        {
            "rows": rows,
            "rule_slot_range": range(ROUTING_RULE_SLOTS),
            "label_keys": label_keys,
            "active": "routing",
        },
    )


@router.post("/routing/{integration_id}", response_model=None, dependencies=[Depends(require_login)])
async def update_routing_rules_submit(
    integration_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    routing_rules = _parse_routing_rules(form)
    updated = await crud.update_integration(session, integration_id, routing_rules=routing_rules)
    if updated is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    if wants_partial(request):
        row = _build_integration_row(updated)
        return templates.TemplateResponse(request, "partials/routing_row.html", {"row": row})
    return RedirectResponse(url="/routing", status_code=303)


@router.post("/integrations/{integration_id}/toggle", response_model=None, dependencies=[Depends(require_login)])
async def toggle_integration_submit(
    integration_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> HTMLResponse | RedirectResponse:
    integration = await crud.get_integration(session, integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    updated = await crud.update_integration(session, integration_id, enabled=not integration.enabled)
    if updated is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    if wants_partial(request):
        row = _build_integration_row(updated)
        return templates.TemplateResponse(
            request,
            "partials/integration_row.html",
            {"row": row, "field_prefix": _integration_field_prefix, "rule_slot_range": range(ROUTING_RULE_SLOTS)},
        )
    return RedirectResponse(url="/integrations", status_code=303)


@router.post("/integrations/{integration_id}/update", response_model=None, dependencies=[Depends(require_login)])
async def update_integration_submit(
    integration_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> HTMLResponse | RedirectResponse:
    integration = await crud.get_integration(session, integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    channel_class = CHANNEL_CLASSES.get(integration.channel_type)
    form = await request.form()
    updates = {}
    if channel_class is not None:
        for field in channel_class.fields:
            value = str(form.get(_integration_field_prefix(integration.channel_type, field["name"]), "")).strip()
            # Blank means "keep the existing value" — most relevant for a
            # secret field that's shown masked and shouldn't be clobbered
            # just because the user didn't retype it.
            if value:
                updates[field["name"]] = value
    # Routing rules live on the /routing tab now, not this form — pass
    # routing_rules=None (crud.update_integration's "don't touch" sentinel)
    # so editing a channel's config here can never clobber its rules.
    updated = await crud.update_integration(session, integration_id, config_updates=updates or None)
    if updated is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    if wants_partial(request):
        row = _build_integration_row(updated)
        return templates.TemplateResponse(
            request,
            "partials/integration_row.html",
            {"row": row, "field_prefix": _integration_field_prefix},
        )
    return RedirectResponse(url="/integrations", status_code=303)


@router.post("/integrations/{integration_id}/delete", response_model=None, dependencies=[Depends(require_login)])
async def delete_integration_submit(
    integration_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> HTMLResponse | RedirectResponse:
    await crud.delete_integration(session, integration_id)
    if wants_partial(request):
        # Empty body + outerHTML swap removes the row from the table in place.
        return HTMLResponse("")
    return RedirectResponse(url="/integrations", status_code=303)


@router.post("/integrations/{integration_id}/test", response_model=None, dependencies=[Depends(require_login)])
async def test_integration_submit(
    integration_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> HTMLResponse | RedirectResponse:
    integration = await crud.get_integration(session, integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    channel_class = CHANNEL_CLASSES.get(integration.channel_type)
    if channel_class is None:
        result = {"ok": False, "display_name": integration.channel_type, "detail": "Unknown channel type"}
    else:
        try:
            channel = channel_class(**integration.config)
            # Bypasses post_json's normal "never raise" contract for this
            # one deliberate case — see raise_send_errors' docstring — so a
            # bad credential surfaces here instead of being silently logged.
            with raise_send_errors():
                await channel.send(_test_event())
            result = {"ok": True, "display_name": channel_class.display_name, "detail": ""}
        except Exception as exc:
            result = {"ok": False, "display_name": channel_class.display_name, "detail": str(exc)}
    if wants_partial(request):
        # Rendered straight into the row's result slot — no page reload, no
        # need for the session-flash banner that the no-JS fallback below uses.
        return templates.TemplateResponse(request, "partials/integration_test_result.html", {"result": result})
    request.session[TEST_RESULT_SESSION_KEY] = result
    return RedirectResponse(url="/integrations", status_code=303)
