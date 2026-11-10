"""Operational telemetry: request ids, structured logs, Prometheus metrics, OTel spans.

Every ``TriageResponse`` already carries a ``Trace`` (steps, timings, token counts,
violations, LLM calls). This module turns that one record into the three signals an
on-call engineer expects from a service, so the numbers in logs, metrics and traces
always agree with what the API returned:

* **Request id.** ``X-Request-ID`` is taken from the caller (if well-formed) or minted,
  echoed on the response, and attached to every log line of the request, so a user's
  bug report ("request 3f2a… gave SEV1") can be matched to the logs.
* **Structured logs.** One JSON object per line (``LOG_FORMAT=json``, default ``text``
  locally). Each triage emits a ``triage_completed`` event with mode, status, severity,
  latency, LLM calls, tokens, cache hits and violation types. No incident text is
  logged: it can contain customer data.
* **Prometheus metrics** at ``GET /metrics``: request counts by mode/status, latency
  histograms, LLM calls and tokens, cache hits, violations by type, HTTP errors by
  status, and estimated cost when ``LLM_PRICE_*`` are set (no default prices: a wrong
  price is worse than none).
* **OpenTelemetry spans** (optional, ``OTEL_ENABLED=true`` plus ``pip install
  opentelemetry-sdk``): one ``triage`` span per request with a child span per pipeline
  step, reconstructed from the trace's measured step latencies. The pipeline code stays
  free of tracing calls; exporting is configured by the standard ``OTEL_*`` variables.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import Settings
from app.schemas import TriageResponse

logger = logging.getLogger("triagent")
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# --------------------------------------------------------------------------- logging


class JsonFormatter(logging.Formatter):
    """One JSON object per line; ``extra={"event_fields": {...}}`` is merged in."""

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_var.get()),
        }
        out.update(getattr(record, "event_fields", {}) or {})
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging(settings: Settings) -> None:
    """Idempotent: installs one handler on the ``triagent`` logger."""
    for h in list(logger.handlers):
        if getattr(h, "_triagent", False):
            logger.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler._triagent = True  # type: ignore[attr-defined]
    handler.addFilter(_RequestIdFilter())
    if settings.log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(message)s")
        )
    logger.addHandler(handler)
    logger.setLevel(settings.log_level.upper())
    logger.propagate = False


# --------------------------------------------------------------------------- metrics

REGISTRY = CollectorRegistry()
LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 15, 30, 60)

TRIAGE_REQUESTS = Counter(
    "triagent_triage_requests", "Completed triage requests", ["mode", "status"],
    registry=REGISTRY)
TRIAGE_LATENCY = Histogram(
    "triagent_triage_duration_seconds", "End-to-end triage latency (server side)", ["mode"],
    buckets=LATENCY_BUCKETS, registry=REGISTRY)
STEP_LATENCY = Histogram(
    "triagent_step_duration_seconds", "Latency per pipeline step", ["step"],
    buckets=LATENCY_BUCKETS, registry=REGISTRY)
LLM_CALLS = Counter(
    "triagent_llm_calls", "LLM calls made by triage requests", ["mode"], registry=REGISTRY)
LLM_CACHE_HITS = Counter(
    "triagent_llm_cache_hits", "LLM calls answered from the cache", registry=REGISTRY)
LLM_TOKENS = Counter(
    "triagent_llm_tokens", "LLM tokens reported by the provider", ["direction"],
    registry=REGISTRY)
LLM_COST = Counter(
    "triagent_llm_cost_usd", "Estimated LLM spend (only when LLM_PRICE_* are set)",
    registry=REGISTRY)
VIOLATIONS = Counter(
    "triagent_validation_violations", "Validator violations by type", ["type"],
    registry=REGISTRY)
SEVERITY = Counter(
    "triagent_reports_by_severity", "Accepted reports by severity", ["severity"],
    registry=REGISTRY)
HTTP_ERRORS = Counter(
    "triagent_http_errors", "Non-2xx responses by route and status", ["route", "status"],
    registry=REGISTRY)


def summarize(resp: TriageResponse) -> dict[str, Any]:
    """The facts about one response that logs, metrics and spans all use."""
    tokens_in = tokens_out = 0
    cache_hits = 0
    for step in resp.trace.steps:
        tokens_in += step.detail.get("input_tokens") or 0
        tokens_out += step.detail.get("output_tokens") or 0
        cache_hits += bool(step.detail.get("cached"))
    report = resp.report
    return {
        "mode": resp.trace.mode,
        "status": resp.status,
        "severity": report.severity.value if report and report.severity else None,
        "insufficient_evidence": bool(report and report.insufficient_evidence),
        "latency_ms": resp.trace.timings_ms.get("total"),
        "llm_calls": resp.trace.llm_calls,
        "llm_cache_hits": cache_hits,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "violations": [v.type for v in resp.trace.violations],
        "retrieved": len(resp.trace.retrieved),
        "model": resp.trace.model,
    }


def estimate_cost(tokens_in: int, tokens_out: int, settings: Settings) -> float | None:
    if settings.llm_price_input_per_mtok is None or settings.llm_price_output_per_mtok is None:
        return None
    return (tokens_in * settings.llm_price_input_per_mtok
            + tokens_out * settings.llm_price_output_per_mtok) / 1_000_000


def record_triage(resp: TriageResponse, settings: Settings) -> dict[str, Any]:
    """Update metrics, emit the ``triage_completed`` log event, export spans."""
    s = summarize(resp)
    TRIAGE_REQUESTS.labels(s["mode"], s["status"]).inc()
    if s["latency_ms"] is not None:
        TRIAGE_LATENCY.labels(s["mode"]).observe(s["latency_ms"] / 1000)
    for step in resp.trace.steps:
        STEP_LATENCY.labels(step.name).observe(step.latency_ms / 1000)
    LLM_CALLS.labels(s["mode"]).inc(s["llm_calls"])
    LLM_CACHE_HITS.inc(s["llm_cache_hits"])
    LLM_TOKENS.labels("input").inc(s["tokens_in"])
    LLM_TOKENS.labels("output").inc(s["tokens_out"])
    for vtype in s["violations"]:
        VIOLATIONS.labels(vtype).inc()
    if s["status"] == "ok":
        SEVERITY.labels(s["severity"] or "none").inc()
    cost = estimate_cost(s["tokens_in"], s["tokens_out"], settings)
    if cost is not None:
        LLM_COST.inc(cost)
        s["cost_usd"] = round(cost, 6)
    logger.info("triage_completed", extra={"event_fields": {"event": "triage_completed", **s}})
    if settings.otel_enabled:
        export_spans(resp, s)
    return s


# --------------------------------------------------------------------------- middleware


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Request id in/out, an access log line, and HTTP error counts."""

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        route = request.url.path if request.url.path in ("/triage", "/health") else "other"
        if response.status_code >= 400:
            HTTP_ERRORS.labels(route, str(response.status_code)).inc()
        if route != "other":
            logger.info(
                "http_request",
                extra={"request_id": rid, "event_fields": {
                    "event": "http_request", "method": request.method, "route": route,
                    "status_code": response.status_code,
                    "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                }},
            )
        return response


# --------------------------------------------------------------------------- OpenTelemetry

_tracer = None


def _get_tracer():
    """Lazily set up an OTel tracer. Without the SDK installed this is a no-op tracer."""
    global _tracer
    if _tracer is None:
        from opentelemetry import trace

        _tracer = trace.get_tracer("triagent")
    return _tracer


def set_tracer(tracer) -> None:
    """Tests inject a tracer backed by an in-memory exporter."""
    global _tracer
    _tracer = tracer


def export_spans(resp: TriageResponse, summary: dict[str, Any]) -> None:
    """One ``triage`` span plus a child per step, laid end to end from measured latencies.

    The spans are reconstructed after the request finished, so a step's start time is
    the sum of the previous steps' latencies. Total span duration is the measured total.
    """
    from opentelemetry import trace

    tracer = _get_tracer()
    end_ns = time.time_ns()
    total_ms = summary["latency_ms"] or sum(s.latency_ms for s in resp.trace.steps)
    start_ns = end_ns - int(total_ms * 1e6)
    attrs = {
        "triagent.request_id": request_id_var.get(),
        "triagent.mode": summary["mode"],
        "triagent.status": summary["status"],
        "triagent.severity": summary["severity"] or "none",
        "triagent.llm_calls": summary["llm_calls"],
        "triagent.tokens_in": summary["tokens_in"],
        "triagent.tokens_out": summary["tokens_out"],
        "triagent.violations": ",".join(summary["violations"]),
        "gen_ai.request.model": summary["model"],
    }
    root = tracer.start_span("triage", start_time=start_ns, attributes=attrs)
    ctx = trace.set_span_in_context(root)
    cursor = start_ns
    for step in resp.trace.steps:
        dur = int(step.latency_ms * 1e6)
        span = tracer.start_span(step.name, context=ctx, start_time=cursor, attributes={
            k: v for k, v in step.detail.items()
            if isinstance(v, (str, bool, int, float)) and k != "query"
        })
        span.end(end_time=cursor + dur)
        cursor += dur
    if summary["status"] == "invalid_output":
        root.set_status(trace.Status(trace.StatusCode.ERROR, summary["status"]))
    root.end(end_time=end_ns)
