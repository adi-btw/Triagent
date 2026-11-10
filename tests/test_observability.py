"""Request ids, structured logs, Prometheus metrics and OTel spans (app/observability.py)."""

from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import app.observability as obs
from app.config import Settings
from app.deps import get_llm, get_retriever_provider, get_settings
from app.main import app
from tests.fakes import DemoLLM, FakeRetriever

INCIDENT = "checkout-api returning 500s: FATAL: sorry, too many clients already"


def sample(name: str, labels: dict[str, str] | None = None) -> float:
    return obs.REGISTRY.get_sample_value(name, labels or {}) or 0.0


@pytest.fixture
def settings():
    return Settings(_env_file=None, llm_provider="fake")


@pytest.fixture
def client(settings):
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_retriever_provider] = lambda: lambda: FakeRetriever()
    app.dependency_overrides[get_llm] = DemoLLM
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_request_id_is_minted_or_echoed(client):
    minted = client.get("/health").headers["x-request-id"]
    assert len(minted) == 16
    assert client.get("/health", headers={"X-Request-ID": "abc-123"}).headers[
        "x-request-id"] == "abc-123"
    # Malformed ids (header injection, absurd length) are replaced, not echoed.
    bad = client.get("/health", headers={"X-Request-ID": "x" * 200}).headers["x-request-id"]
    assert bad != "x" * 200


def test_triage_updates_metrics(client):
    before = sample("triagent_triage_requests_total", {"mode": "rag", "status": "ok"})
    calls = sample("triagent_llm_calls_total", {"mode": "rag"})
    resp = client.post("/triage", json={"incident": INCIDENT, "mode": "rag"})
    assert resp.status_code == 200
    assert sample("triagent_triage_requests_total", {"mode": "rag", "status": "ok"}) == before + 1
    assert sample("triagent_llm_calls_total", {"mode": "rag"}) == calls + 1
    assert sample("triagent_triage_duration_seconds_count", {"mode": "rag"}) >= 1
    assert sample("triagent_step_duration_seconds_count", {"step": "validate"}) >= 1


def test_metrics_endpoint_exposes_prometheus_text(client):
    client.post("/triage", json={"incident": INCIDENT, "mode": "rag"})
    body = client.get("/metrics").text
    assert "# TYPE triagent_triage_requests_total counter" in body
    assert "triagent_triage_duration_seconds_bucket" in body


def test_http_errors_are_counted(client):
    before = sample("triagent_http_errors_total", {"route": "/triage", "status": "422"})
    client.post("/triage", json={"incident": "short"})  # fails request validation
    assert sample("triagent_http_errors_total",
                  {"route": "/triage", "status": "422"}) == before + 1


def test_json_log_event_has_fields_but_no_incident_text(client, capsys):
    obs.configure_logging(Settings(_env_file=None, log_format="json"))
    try:
        client.post("/triage", json={"incident": INCIDENT, "mode": "rag"},
                    headers={"X-Request-ID": "req-42"})
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()
                 if line.startswith("{")]
    finally:
        obs.configure_logging(Settings(_env_file=None))
    done = next(r for r in lines if r.get("event") == "triage_completed")
    assert done["request_id"] == "req-42"
    assert done["mode"] == "rag" and done["status"] == "ok" and done["llm_calls"] == 1
    assert {"latency_ms", "tokens_in", "tokens_out", "violations", "severity"} <= done.keys()
    assert all("too many clients" not in json.dumps(r) for r in lines)
    access = next(r for r in lines if r.get("event") == "http_request")
    assert access["status_code"] == 200 and access["route"] == "/triage"


def test_cost_only_when_prices_are_configured():
    s = Settings(_env_file=None)
    assert obs.estimate_cost(1000, 1000, s) is None
    priced = Settings(_env_file=None, llm_price_input_per_mtok=0.1,
                      llm_price_output_per_mtok=0.4)
    assert obs.estimate_cost(1_000_000, 500_000, priced) == pytest.approx(0.3)


def test_otel_spans_mirror_the_trace(client, settings):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    obs.set_tracer(provider.get_tracer("test"))
    traced = settings.model_copy(update={"otel_enabled": True})
    app.dependency_overrides[get_settings] = lambda: traced
    try:
        body = client.post("/triage", json={"incident": INCIDENT, "mode": "rag"}).json()
    finally:
        obs.set_tracer(None)
    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert set(spans) == {"triage", *(step["name"] for step in body["trace"]["steps"])}
    root = spans["triage"]
    assert root.attributes["triagent.mode"] == "rag"
    for name in ("retrieve", "generate", "validate"):
        child = spans[name]
        assert child.parent.span_id == root.context.span_id
        assert root.start_time <= child.start_time <= child.end_time <= root.end_time
    assert spans["generate"].attributes["prompt_version"]


def test_logging_setup_is_idempotent():
    obs.configure_logging(Settings(_env_file=None))
    obs.configure_logging(Settings(_env_file=None))
    ours = [h for h in logging.getLogger("triagent").handlers if getattr(h, "_triagent", False)]
    assert len(ours) == 1
