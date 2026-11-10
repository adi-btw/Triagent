"""POST /triage/stream: event order, final body parity with /triage, errors. Fakes only."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.deps import ServiceUnavailable, get_llm, get_retriever_provider, get_settings
from app.llm.errors import LLMCallError
from app.main import app
from app.triage import events
from tests.fakes import DemoLLM, FakeRetriever, ScriptedLLM, valid_report

INCIDENT = "checkout-api returning 500s: FATAL: sorry, too many clients already"
DRAFT = {"action": "draft_report", "rationale": "Evidence matches.",
         "rewritten_query": None, "clarifying_question": None}


@pytest.fixture
def client():
    settings = Settings(_env_file=None, llm_provider="fake")
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_retriever_provider] = lambda: lambda: FakeRetriever()
    app.dependency_overrides[get_llm] = DemoLLM
    yield TestClient(app)
    app.dependency_overrides.clear()


def stream(client, **body) -> list[tuple[str, dict]]:
    out, event = [], None
    with client.stream("POST", "/triage/stream", json={"incident": INCIDENT, **body}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                out.append((event, json.loads(line[5:])))
    return out


def names(evts):
    return [e for e, _ in evts]


def test_rag_events_arrive_in_pipeline_order(client):
    evts = stream(client, mode="rag")
    assert names(evts) == ["started", "step", "evidence", "step_started", "step", "step",
                           "result"]
    steps = [d["step"]["name"] for e, d in evts if e == "step"]
    assert steps == ["retrieve", "generate", "validate"]
    assert evts[0][1] == {"mode": "rag", "model": "fake-demo"}
    assert evts[2][1]["items"][0].keys() >= {"chunk_id", "title", "score"}


def test_agent_streams_decide_and_draft(client):
    app.dependency_overrides[get_llm] = lambda: ScriptedLLM([DRAFT, valid_report()])
    evts = stream(client, mode="agent")
    started = [d["name"] for e, d in evts if e == "step_started"]
    assert started == ["decide", "draft"]
    assert evts[-1][0] == "result" and evts[-1][1]["http_status"] == 200


def test_final_result_matches_plain_endpoint(client):
    plain = client.post("/triage", json={"incident": INCIDENT, "mode": "rag"}).json()
    final = stream(client, mode="rag")[-1][1]["response"]
    for key in ("status", "report", "evidence"):
        assert final[key] == plain[key]
    assert [s["name"] for s in final["trace"]["steps"]] == [
        s["name"] for s in plain["trace"]["steps"]]


def test_rejected_report_reports_422_inside_the_stream(client):
    bad = valid_report(likely_causes=[{"description": "x", "confidence": "high",
                                       "citations": ["NOPE#s1"]}])
    app.dependency_overrides[get_llm] = lambda: ScriptedLLM([bad])
    event, data = stream(client, mode="rag")[-1]
    assert event == "result" and data["http_status"] == 422
    assert data["response"]["status"] == "invalid_output"


def test_provider_failure_is_a_terminal_error_event(client):
    class DownLLM:
        model_name = "down"

        def generate_json(self, **_):
            raise LLMCallError("503 from provider after 3 attempts")

    app.dependency_overrides[get_llm] = DownLLM
    event, data = stream(client, mode="rag")[-1]
    assert event == "error" and data["http_status"] == 502
    assert data["type"] == "LLMCallError"


def test_missing_index_is_503_in_the_stream(client):
    def broken():
        raise ServiceUnavailable("no index")
    app.dependency_overrides[get_retriever_provider] = lambda: broken
    event, data = stream(client, mode="rag")[-1]
    assert event == "error" and data["http_status"] == 503 and "no index" in data["detail"]


def test_bad_request_is_a_plain_422_before_streaming(client):
    r = client.post("/triage/stream", json={"incident": "short"})
    assert r.status_code == 422 and "detail" in r.json()


def test_emit_without_listener_is_a_no_op_and_listeners_nest():
    events.emit("step", x=1)  # nothing installed: must not raise
    seen = []
    with events.listening(lambda e, d: seen.append(("outer", e))):
        with events.listening(lambda e, d: seen.append(("inner", e))):
            events.emit("a")
        events.emit("b")
    events.emit("c")
    assert seen == [("inner", "a"), ("outer", "b")]
