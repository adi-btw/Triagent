"""HTTP contract for mode="agent", and the demo UI mount. Fakes only."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.deps import get_llm, get_retriever_provider, get_settings
from app.main import STATIC_DIR, app
from tests.fakes import DemoLLM, FakeRetriever, ScriptedLLM, valid_report

INCIDENT = "checkout-api returning 500s: FATAL: sorry, too many clients already"
DRAFT = {"action": "draft_report", "rationale": "Evidence matches.",
         "rewritten_query": None, "clarifying_question": None}
ASK = {"action": "ask_clarifying_question", "rationale": "Too vague.",
       "rewritten_query": None, "clarifying_question": "Which service is affected?"}


@pytest.fixture
def client():
    settings = Settings(_env_file=None, llm_provider="fake")
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_retriever_provider] = lambda: lambda: FakeRetriever()
    app.dependency_overrides[get_llm] = DemoLLM
    yield TestClient(app)
    app.dependency_overrides.clear()


def use_llm(llm):
    app.dependency_overrides[get_llm] = lambda: llm


def post_agent(client, **extra):
    return client.post("/triage", json={"incident": INCIDENT, "mode": "agent", **extra})


def test_agent_ok_returns_200_with_trace(client):
    use_llm(ScriptedLLM([DRAFT, valid_report()]))
    resp = post_agent(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok" and body["report"]["severity"] == "SEV2"
    assert [s["name"] for s in body["trace"]["steps"]] == ["retrieve", "decide", "draft",
                                                         "validate"]
    assert body["trace"]["steps"][1]["detail"]["rationale"] == "Evidence matches."
    assert body["trace"]["llm_calls"] == 2


def test_needs_clarification_is_200_with_question(client):
    use_llm(ScriptedLLM([ASK]))
    resp = post_agent(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "needs_clarification" and body["report"] is None
    assert body["clarifying_question"] == "Which service is affected?"


def test_resubmit_with_clarification_cannot_ask_again(client):
    llm = ScriptedLLM([ASK, valid_report()])
    use_llm(llm)
    resp = post_agent(client, clarification="checkout-api, 18% errors")
    body = resp.json()
    assert resp.status_code == 200 and body["status"] == "ok"
    assert "override" in [s["name"] for s in body["trace"]["steps"]]
    assert "Additional information from reporter: checkout-api, 18% errors" in llm.calls[0].user


def test_invalid_after_repair_is_422_with_full_response(client):
    bad = valid_report(next_steps=[{"action": "Do X", "citations": []}])
    use_llm(ScriptedLLM([DRAFT, bad, bad]))
    resp = post_agent(client)
    assert resp.status_code == 422
    body = resp.json()
    assert body["status"] == "invalid_output" and body["report"] is not None
    assert body["trace"]["violations"][0]["type"] == "missing_citation"
    assert [s["name"] for s in body["trace"]["steps"]][-2:] == ["repair", "validate"]


def test_demo_llm_agent_end_to_end(client):
    body = post_agent(client).json()
    assert body["status"] == "ok" and body["report"]["summary"].startswith("[fake LLM]")


def test_root_serves_the_demo_ui(client):
    assert (STATIC_DIR / "index.html").exists()
    resp = client.get("/")
    assert resp.status_code == 200 and "text/html" in resp.headers["content-type"]
    assert "Incident Triage Assistant" in resp.text and 'src="app.js"' in resp.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/app.css").status_code == 200


def test_static_mount_does_not_shadow_api_routes(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200
