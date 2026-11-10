"""HTTP routes for integrations.

    POST /webhooks/alert   Alertmanager / Grafana / generic JSON -> triage -> Slack channel
    POST /slack/commands   ``/triage <incident>`` slash command -> triage -> reply in Slack

Both endpoints answer quickly and triage afterwards. Alertmanager retries slow webhooks,
and Slack gives up on a slash command after 3 seconds, but one triage takes seconds to
a minute. So the route checks auth, parses, deduplicates, replies (202, or Slack's
ephemeral ack) and hands the work to a background task. The background task runs the
same ``run_triage`` as ``/triage`` and posts the formatted result.
``/webhooks/alert?wait=true`` triages inline and returns the results, which is handy
with curl and in tests.

Both endpoints are off (503) until their secret is configured, so a deployment that
never set them, like the public demo, exposes nothing new.
"""

from __future__ import annotations

import hmac
import json
import logging
from typing import Annotated, Any
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.demo import RateLimited, SlidingWindowLimiter
from app.deps import LLMDep, RetrieverProviderDep, SettingsDep
from app.integrations import alerts, slack
from app.llm.base import LLMClient
from app.observability import WEBHOOK_EVENTS, record_triage
from app.retrieval.base import Retriever
from app.schemas import TriageRequest, TriageResponse
from app.triage.service import run_triage

log = logging.getLogger("triagent.integrations")
router = APIRouter(tags=["integrations"])

_state: dict[str, Any] = {}


def reset_state() -> None:
    """Forget dedupe history and rate-limit windows (tests)."""
    _state.clear()


def _deduper(settings: Settings) -> alerts.Deduper:
    d = _state.get("deduper")
    if d is None or d.ttl_s != settings.alert_dedupe_ttl_s:
        d = _state["deduper"] = alerts.Deduper(settings.alert_dedupe_ttl_s)
    return d


def _limiter(settings: Settings) -> SlidingWindowLimiter:
    lim = _state.get("limiter")
    if lim is None or lim.limit != settings.integration_triages_per_hour:
        lim = _state["limiter"] = SlidingWindowLimiter(settings.integration_triages_per_hour)
    return lim


def get_notifier(settings: SettingsDep) -> slack.SlackNotifier:
    return slack.SlackNotifier(settings.slack_webhook_url)


NotifierDep = Annotated[slack.SlackNotifier, Depends(get_notifier)]


def _triage(text: str, *, settings: Settings, llm: LLMClient,
            retriever: Retriever) -> TriageResponse:
    request = TriageRequest(incident=text, mode=settings.integration_mode)
    response = run_triage(request, retriever=retriever, llm=llm, settings=settings)
    record_triage(response, settings)
    return response


def _deliver(source: str, message: dict[str, Any], notifier: slack.SlackNotifier,
             url: str | None = None) -> bool:
    try:
        posted = notifier.post(message, url)
    except Exception as exc:  # Slack down or URL revoked: log it, never crash the worker
        WEBHOOK_EVENTS.labels(source, "delivery_failed").inc()
        log.warning("slack delivery failed: %s", exc)
        return False
    WEBHOOK_EVENTS.labels(source, "delivered" if posted else "not_configured").inc()
    if not posted:
        log.info("no SLACK_WEBHOOK_URL set; triage result: %s", message.get("text"))
    return posted


def _error_message(title: str, exc: Exception) -> dict[str, Any]:
    return {"text": f"Triage failed: {slack.escape(title)}", "blocks": [slack._section(
        f":warning: *Triage failed* for *{slack.escape(title)}*\n"
        f"`{type(exc).__name__}`: {slack.escape(str(exc)[:300])}")]}


def triage_and_post(incident: alerts.Incident, source: str, *, settings: Settings,
                    llm: LLMClient, retriever: Retriever, notifier: slack.SlackNotifier,
                    url: str | None = None,
                    extra: dict[str, Any] | None = None) -> tuple[TriageResponse | None, bool]:
    try:
        response = _triage(incident.text, settings=settings, llm=llm, retriever=retriever)
        message = slack.format_report(response, title=incident.title)
    except Exception as exc:  # provider down, etc.: tell the channel instead of going silent
        log.exception("integration triage failed")
        response, message = None, _error_message(incident.title, exc)
    return response, _deliver(source, {**message, **(extra or {})}, notifier, url)


# --------------------------------------------------------------------------- alerts


def _check_token(settings: Settings, authorization: str | None) -> None:
    if not settings.webhook_token:
        raise HTTPException(503, "Alert webhook disabled: set WEBHOOK_TOKEN to enable it.")
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(given.encode(), settings.webhook_token.encode()):
        WEBHOOK_EVENTS.labels("alert", "unauthorized").inc()
        raise HTTPException(401, "Missing or wrong bearer token.",
                            headers={"WWW-Authenticate": "Bearer"})


@router.post("/webhooks/alert", status_code=202)
async def alert_webhook(
    request: Request,
    background: BackgroundTasks,
    settings: SettingsDep,
    llm: LLMDep,
    retriever_provider: RetrieverProviderDep,
    notifier: NotifierDep,
    authorization: Annotated[str | None, Header()] = None,
    wait: bool = False,
) -> Any:
    _check_token(settings, authorization)
    try:
        payload = json.loads(await request.body())
        if not isinstance(payload, dict):
            raise ValueError("body must be a JSON object")
        incidents = alerts.parse(payload)
    except ValueError as exc:  # JSONDecodeError is a ValueError
        raise HTTPException(400, f"Unrecognised alert payload: {exc}") from exc
    source = "alertmanager" if "alerts" in payload else "generic"
    if not incidents:
        WEBHOOK_EVENTS.labels(source, "ignored").inc()
        return {"accepted": [], "duplicates": 0, "detail": "no firing alerts"}

    dedupe = _deduper(settings)
    fresh = [i for i in incidents if dedupe.first_time(i.key)]
    duplicates = len(incidents) - len(fresh)
    if duplicates:
        WEBHOOK_EVENTS.labels(source, "duplicate").inc(duplicates)
    limiter = _limiter(settings)
    for _ in fresh:
        try:
            limiter.hit("integrations")
        except RateLimited as exc:
            WEBHOOK_EVENTS.labels(source, "rate_limited").inc()
            return JSONResponse(status_code=429, headers={"Retry-After": str(exc.retry_after_s)},
                                content={"detail": "Integration triage limit reached "
                                         f"({settings.integration_triages_per_hour}/hour)."})
    WEBHOOK_EVENTS.labels(source, "accepted").inc(len(fresh))
    retriever = retriever_provider() if fresh else None  # 503 now, not in the background

    accepted = [{"title": i.title, "key": i.key} for i in fresh]
    if wait:
        results = []
        for i in fresh:
            resp, posted = triage_and_post(i, source, settings=settings, llm=llm,
                                           retriever=retriever, notifier=notifier)
            results.append({"title": i.title, "posted_to_slack": posted,
                            "response": resp.model_dump(mode="json") if resp else None})
        return JSONResponse(status_code=200, content={"accepted": accepted,
                                                      "duplicates": duplicates,
                                                      "results": results})
    for i in fresh:
        background.add_task(triage_and_post, i, source, settings=settings, llm=llm,
                            retriever=retriever, notifier=notifier)
    return {"accepted": accepted, "duplicates": duplicates}


# --------------------------------------------------------------------------- slack


USAGE = ("Usage: `/triage <what is happening>`, for example "
         "`/triage checkout-api 500s, FATAL: too many clients already`")


@router.post("/slack/commands")
async def slack_command(
    request: Request,
    background: BackgroundTasks,
    settings: SettingsDep,
    llm: LLMDep,
    retriever_provider: RetrieverProviderDep,
    notifier: NotifierDep,
    x_slack_request_timestamp: Annotated[str | None, Header()] = None,
    x_slack_signature: Annotated[str | None, Header()] = None,
) -> Any:
    if not settings.slack_signing_secret:
        raise HTTPException(503, "Slack commands disabled: set SLACK_SIGNING_SECRET.")
    body = await request.body()  # the raw bytes are what Slack signed
    if not slack.verify_signature(settings.slack_signing_secret, x_slack_request_timestamp,
                                  body, x_slack_signature):
        WEBHOOK_EVENTS.labels("slack", "unauthorized").inc()
        raise HTTPException(401, "Bad or expired Slack signature.")
    form = {k: v[0] for k, v in parse_qs(body.decode("utf-8")).items()}
    text = form.get("text", "").strip()
    response_url = form.get("response_url", "")
    if len(text) < 10:
        return {"response_type": "ephemeral", "text": USAGE}
    if not slack.is_slack_response_url(response_url):
        WEBHOOK_EVENTS.labels("slack", "bad_response_url").inc()
        raise HTTPException(400, "response_url must be https://hooks.slack.com/...")
    try:
        _limiter(settings).hit("integrations")
    except RateLimited:
        WEBHOOK_EVENTS.labels("slack", "rate_limited").inc()
        return {"response_type": "ephemeral",
                "text": "Triage limit reached for this hour. Try again later."}
    retriever = retriever_provider()
    WEBHOOK_EVENTS.labels("slack", "accepted").inc()
    incident = alerts.Incident(title=text[:150], text=text[:alerts.MAX_INCIDENT_CHARS],
                               key="slack")
    # The result replaces the ephemeral ack and is visible to the whole channel.
    background.add_task(triage_and_post, incident, "slack", settings=settings, llm=llm,
                        retriever=retriever, notifier=notifier, url=response_url,
                        extra={"response_type": "in_channel", "replace_original": True})
    return slack.slash_ack(text)
