import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.deps import (
    ServiceUnavailable,
    get_llm,
    get_retriever_provider,
    get_settings,
)
from app.main import app
from tests.fakes import DemoLLM, FakeRetriever, ScriptedLLM, valid_report

INCIDENT = "checkout-api returning 500s: FATAL: sorry, too many clients already"


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


def test_triage_ok_returns_200(client):
    use_llm(ScriptedLLM([valid_report()]))
    resp = client.post("/triage", json={"incident": INCIDENT, "mode": "rag"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["report"]["severity"] == "SEV2"
    assert body["evidence"] and body["trace"]["timings_ms"]["total"] >= 0


def test_demo_llm_end_to_end_is_valid(client):
    resp = client.post("/triage", json={"incident": INCIDENT})
    assert resp.status_code == 200, resp.json()
    assert resp.json()["report"]["summary"].startswith("[fake LLM]")


def test_invalid_output_returns_422_with_full_response(client):
    bad = valid_report()
    bad["next_steps"][0]["citations"] = []
    use_llm(ScriptedLLM([bad]))
    resp = client.post("/triage", json={"incident": INCIDENT})
    assert resp.status_code == 422
    body = resp.json()
    assert body["status"] == "invalid_output"
    assert body["trace"]["violations"] == [
        {"type": "missing_citation", "detail": "next_steps[0] has no citations"}
    ]
    assert body["report"] is not None and body["evidence"]


def test_agent_mode_is_served(client):
    # Was 501 before stage 2; agent API behaviour is in tests/test_agent_api.py.
    resp = client.post("/triage", json={"incident": INCIDENT, "mode": "agent"})
    assert resp.status_code == 200 and resp.json()["trace"]["mode"] == "agent"


def test_retriever_build_failure_returns_503(client):
    def broken():
        raise ServiceUnavailable("Retriever unavailable (FileNotFoundError: index.json)")

    app.dependency_overrides[get_retriever_provider] = lambda: broken
    resp = client.post("/triage", json={"incident": INCIDENT, "mode": "rag"})
    assert resp.status_code == 503
    assert "index.json" in resp.json()["detail"]


def test_no_retrieval_works_without_an_index(client):
    def broken():
        raise ServiceUnavailable("no index")

    app.dependency_overrides[get_retriever_provider] = lambda: broken
    resp = client.post("/triage", json={"incident": INCIDENT, "mode": "no_retrieval"})
    assert resp.status_code == 200


def test_real_dependencies_without_key_return_503(monkeypatch):
    """No overrides: provider=gemini with no key must give a helpful 503, not a crash."""
    import app.deps as deps

    settings = Settings(_env_file=None, llm_provider="gemini", gemini_api_key=None)
    monkeypatch.setattr(deps, "_get_settings", lambda: settings)
    deps._cached_llm.cache_clear()
    try:
        resp = TestClient(app).post("/triage", json={"incident": INCIDENT})
    finally:
        deps._cached_llm.cache_clear()
    assert resp.status_code == 503
    assert "GEMINI_API_KEY" in resp.json()["detail"]


def test_bad_request_is_fastapi_422(client):
    resp = client.post("/triage", json={"incident": "short"})
    assert resp.status_code == 422 and "detail" in resp.json()


def test_health_reports_config_and_index(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_provider"] == "fake" and body["index_ok"] is True
    assert {"backend", "embedder", "model"} <= body.keys()


def test_health_when_index_missing(client):
    def broken():
        raise ServiceUnavailable("no index")

    app.dependency_overrides[get_retriever_provider] = lambda: broken
    body = client.get("/health").json()
    assert body["index_ok"] is False and body["index_error"] == "no index"
