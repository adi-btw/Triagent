import pytest

from app.config import Settings
from app.llm.prompts import NO_RETRIEVAL_SYSTEM, PROMPT_VERSION, TRIAGE_SYSTEM
from app.schemas import TriageReport, TriageRequest
from app.triage.pipeline import run_no_retrieval, run_rag
from app.triage.service import run_triage
from tests.fakes import DEMO_EVIDENCE, FakeRetriever, ScriptedLLM, valid_report

INCIDENT = "checkout-api returning 500s, FATAL: sorry, too many clients already"


@pytest.fixture
def settings():
    return Settings(_env_file=None, llm_provider="fake", top_k=4, retrieval_mode="hybrid")


def test_rag_happy_path(settings):
    retriever = FakeRetriever()
    llm = ScriptedLLM([valid_report()])
    resp = run_rag(INCIDENT, retriever=retriever, llm=llm, settings=settings)

    assert resp.status == "ok"
    assert resp.report is not None and resp.report.severity is not None
    assert [e.chunk_id for e in resp.evidence] == [e.chunk_id for e in DEMO_EVIDENCE]
    # Retriever was asked with the incident text and the configured k / mode.
    assert retriever.calls[0].query == INCIDENT
    assert (retriever.calls[0].k, retriever.calls[0].mode) == (4, "hybrid")
    # The LLM saw the RAG system prompt, every evidence tag, and the TriageReport schema.
    call = llm.calls[0]
    assert call.system == TRIAGE_SYSTEM and call.schema is TriageReport
    assert all(f'id="{e.chunk_id}"' in call.user for e in DEMO_EVIDENCE)


def test_rag_trace_fields_are_populated(settings):
    resp = run_rag(INCIDENT, retriever=FakeRetriever(), llm=ScriptedLLM([valid_report()]),
                   settings=settings)
    trace = resp.trace
    assert trace.mode == "rag" and trace.model == "scripted" and trace.llm_calls == 1
    assert trace.queries == [INCIDENT] and trace.retrieval_mode == "hybrid"
    assert [r.chunk_id for r in trace.retrieved] == [e.chunk_id for e in DEMO_EVIDENCE]
    assert [s.name for s in trace.steps] == ["retrieve", "generate", "validate"]
    assert set(trace.timings_ms) == {"retrieval", "generation", "validation", "total"}
    assert trace.timings_ms["total"] >= trace.timings_ms["generation"]
    retrieve, generate, validate = trace.steps
    assert retrieve.detail["results"][0] == {"chunk_id": "RB-DB-001#s1", "score": 0.82}
    assert generate.detail["prompt_version"] == PROMPT_VERSION
    assert generate.detail["input_tokens"] is not None
    assert validate.detail["violations"] == []


def test_rag_invalid_output_path(settings):
    bad = valid_report()
    bad["likely_causes"][0]["citations"] = ["RB-FAKE-999#s1"]
    resp = run_rag(INCIDENT, retriever=FakeRetriever(), llm=ScriptedLLM([bad]),
                   settings=settings)
    assert resp.status == "invalid_output"
    assert resp.report is not None  # kept for inspection
    assert [v.type for v in resp.trace.violations] == ["unknown_citation"]
    assert resp.trace.steps[2].detail["violations"][0]["type"] == "unknown_citation"


def test_rag_unparseable_output_is_schema_error(settings):
    resp = run_rag(INCIDENT, retriever=FakeRetriever(), llm=ScriptedLLM(["I think it's DNS"]),
                   settings=settings)
    assert resp.status == "invalid_output" and resp.report is None
    assert resp.trace.violations[0].type == "schema_error"
    assert resp.trace.steps[1].detail["parsed_json"] is False


def test_no_retrieval_never_calls_retriever(settings):
    retriever = FakeRetriever(error=AssertionError("must not be called"))
    llm = ScriptedLLM([valid_report(severity_citations=[], likely_causes=[
        {"description": "DB connection limit", "confidence": "medium"}], next_steps=[])])
    resp = run_triage(TriageRequest(incident=INCIDENT, mode="no_retrieval"),
                      retriever=retriever, llm=llm, settings=settings)
    assert retriever.calls == []
    assert resp.status == "ok" and resp.evidence == []
    assert llm.calls[0].system == NO_RETRIEVAL_SYSTEM
    assert [s.name for s in resp.trace.steps] == ["generate", "validate"]
    assert resp.trace.timings_ms["retrieval"] == 0.0


def test_no_retrieval_hallucinated_ids_are_invalid(settings):
    resp = run_no_retrieval(INCIDENT, llm=ScriptedLLM([valid_report()]), settings=settings)
    assert resp.status == "invalid_output"
    assert {v.type for v in resp.trace.violations} == {"unknown_citation"}


def test_service_appends_clarification(settings):
    llm = ScriptedLLM([valid_report()])
    retriever = FakeRetriever()
    run_triage(TriageRequest(incident=INCIDENT, clarification="error rate is 18%"),
               retriever=retriever, llm=llm, settings=settings)
    expected = f"{INCIDENT}\n\nAdditional information from reporter: error rate is 18%"
    assert retriever.calls[0].query == expected
    assert "Additional information from reporter: error rate is 18%" in llm.calls[0].user


def test_service_agent_mode_runs_the_agent(settings):
    # Detailed agent behaviour lives in tests/test_agent.py; this checks the dispatch.
    decision = {"action": "draft_report", "rationale": "ok", "rewritten_query": None,
                "clarifying_question": None}
    resp = run_triage(TriageRequest(incident=INCIDENT, mode="agent"),
                      retriever=FakeRetriever(), llm=ScriptedLLM([decision, valid_report()]),
                      settings=settings)
    assert resp.status == "ok" and resp.trace.mode == "agent"
