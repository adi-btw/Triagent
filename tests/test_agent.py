"""Agent workflow tests: scripted decisions in, trace and status out. No network."""

import pytest

from app.agent.prompts import AGENT_PROMPT_VERSION, DECIDE_SYSTEM
from app.agent.schemas import AgentDecision
from app.agent.workflow import merge_evidence, run_agent
from app.config import Settings
from app.llm.prompts import TRIAGE_SYSTEM
from app.schemas import TriageReport
from tests.fakes import (
    DEMO_EVIDENCE,
    DemoLLM,
    FakeRetriever,
    ScriptedLLM,
    make_evidence,
    valid_report,
)

INCIDENT = "checkout-api returning 500s: FATAL: sorry, too many clients already"
EXTRA = make_evidence("RB-K8S-002#s2", "HPA scaled out", heading="Diagnosis", score=0.9)


def draft(rationale="Evidence matches."):
    return {"action": "draft_report", "rationale": rationale,
            "rewritten_query": None, "clarifying_question": None}


def rewrite(query, rationale="Evidence misses the scale-out."):
    return {"action": "rewrite_query", "rationale": rationale,
            "rewritten_query": query, "clarifying_question": None}


def ask(question="Which service is affected?"):
    return {"action": "ask_clarifying_question", "rationale": "Too vague.",
            "rewritten_query": None, "clarifying_question": question}


@pytest.fixture
def settings():
    return Settings(_env_file=None, llm_provider="fake", top_k=4, retrieval_mode="hybrid")


def by_query(query):
    """First query gets the demo evidence; any rewrite gets one new chunk plus an overlap."""
    if query == INCIDENT:
        return list(DEMO_EVIDENCE)
    return [EXTRA, make_evidence("RB-DB-001#s1", score=0.95, heading="Symptoms")]


def run(llm, settings, *, retriever=None, clarification_given=False, incident=INCIDENT):
    retriever = retriever or FakeRetriever(by_query)
    resp = run_agent(incident, retriever=retriever, llm=llm, settings=settings,
                     clarification_given=clarification_given)
    return resp, retriever


def names(resp):
    return [s.name for s in resp.trace.steps]


def overrides(resp):
    return [s.detail for s in resp.trace.steps if s.name == "override"]


def test_draft_immediately(settings):
    llm = ScriptedLLM([draft(), valid_report()])
    resp, retriever = run(llm, settings)
    assert resp.status == "ok" and resp.report is not None
    assert names(resp) == ["retrieve", "decide", "draft", "validate"]
    assert resp.trace.llm_calls == 2 and resp.trace.mode == "agent"
    assert (retriever.calls[0].k, retriever.calls[0].mode) == (4, "hybrid")
    decide_call, draft_call = llm.calls
    assert decide_call.system == DECIDE_SYSTEM and decide_call.schema is AgentDecision
    assert draft_call.system == TRIAGE_SYSTEM and draft_call.schema is TriageReport
    decide = resp.trace.steps[1].detail
    assert decide["decision"] == "draft_report" and decide["rationale"] == "Evidence matches."
    assert decide["prompt_version"] == AGENT_PROMPT_VERSION
    assert set(resp.trace.timings_ms) == {"retrieval", "generation", "validation", "total"}


def test_decide_prompt_has_summary_not_full_passages(settings):
    long = make_evidence("RB-X-001#s1", "word " * 500)
    llm = ScriptedLLM([draft(), valid_report(severity_citations=[], severity=None,
                                             insufficient_evidence=True,
                                             likely_causes=[], next_steps=[])])
    run(llm, settings, retriever=FakeRetriever([long]))
    prompt = llm.calls[0].user
    assert 'id="RB-X-001#s1"' in prompt and "word " * 60 not in prompt
    assert "Allowed actions: draft_report, rewrite_query, ask_clarifying_question" in prompt


def test_rewrite_then_draft_merges_evidence(settings):
    report = valid_report(next_steps=[{"action": "Check HPA", "citations": ["RB-K8S-002#s2"]}])
    llm = ScriptedLLM([rewrite("hpa scale out connection pool"), draft(), report])
    resp, retriever = run(llm, settings)
    assert resp.status == "ok", resp.trace.violations
    assert names(resp) == ["retrieve", "decide", "rewrite_query", "retrieve", "decide",
                           "draft", "validate"]
    assert [c.query for c in retriever.calls] == [INCIDENT, "hpa scale out connection pool"]
    assert resp.trace.queries == [INCIDENT, "hpa scale out connection pool"]
    ids = [e.chunk_id for e in resp.evidence]
    # Union of both retrievals, de-duplicated, best score kept, ordered by score.
    assert ids == ["RB-DB-001#s1", "RB-K8S-002#s2", "RB-DB-001#s3", "INC-2025-014#s2",
                   "POL-SEV-001#s1"]
    assert resp.evidence[0].score == 0.95
    assert [r.chunk_id for r in resp.trace.retrieved] == ids
    # The allow-list given to the validator covers chunks from both queries.
    allowed = resp.trace.steps[-1].detail["allowed_ids"]
    assert "RB-K8S-002#s2" in allowed and "POL-SEV-001#s1" in allowed
    assert resp.trace.steps[3].detail["new_chunk_ids"] == ["RB-K8S-002#s2"]
    assert resp.trace.llm_calls == 3


def test_merge_is_capped_at_cap():
    a = [make_evidence(f"A#s{i}", score=i / 10) for i in range(1, 6)]
    b = [make_evidence(f"B#s{i}", score=i / 10 + 0.05) for i in range(1, 6)]
    merged = merge_evidence(a, b, cap=4)
    assert [e.chunk_id for e in merged] == ["B#s5", "A#s5", "B#s4", "A#s4"]


def test_second_rewrite_is_overridden_to_draft(settings):
    llm = ScriptedLLM([rewrite("query two"), rewrite("query three"), valid_report()])
    resp, retriever = run(llm, settings)
    assert resp.status == "ok"
    assert len(retriever.calls) == 2
    assert names(resp) == ["retrieve", "decide", "rewrite_query", "retrieve", "decide",
                           "override", "draft", "validate"]
    (detail,) = overrides(resp)
    assert detail["overridden"] is True and detail["requested_action"] == "rewrite_query"
    assert "rewrite limit" in detail["reason"]
    # The second decide call was told rewrite was no longer allowed.
    assert "Allowed actions: draft_report, ask_clarifying_question" in llm.calls[1].user


def test_rewrite_repeating_a_query_is_overridden(settings):
    llm = ScriptedLLM([rewrite("  " + INCIDENT.upper() + " "), valid_report()])
    resp, retriever = run(llm, settings)
    assert len(retriever.calls) == 1
    assert "repeats a query" in overrides(resp)[0]["reason"]


def test_ask_returns_needs_clarification(settings):
    llm = ScriptedLLM([ask("Which service, and what error rate?")])
    resp, _ = run(llm, settings)
    assert resp.status == "needs_clarification"
    assert resp.clarifying_question == "Which service, and what error rate?"
    assert resp.report is None and resp.evidence
    assert names(resp) == ["retrieve", "decide", "ask_clarifying_question"]
    assert resp.trace.llm_calls == 1


def test_ask_after_clarification_is_overridden(settings):
    llm = ScriptedLLM([ask(), valid_report()])
    resp, _ = run(llm, settings, clarification_given=True)
    assert resp.status == "ok" and resp.clarifying_question is None
    assert names(resp) == ["retrieve", "decide", "override", "draft", "validate"]
    assert "clarification was already given" in overrides(resp)[0]["reason"]
    assert "ask_clarifying_question" not in llm.calls[0].user.split("Allowed actions:")[1]


@pytest.mark.parametrize(
    "bad",
    ["not json at all", {"action": "delete_database", "rationale": "x"},
     {"action": "rewrite_query", "rationale": "x", "rewritten_query": "  "}],
)
def test_malformed_decision_falls_back_to_draft(settings, bad):
    llm = ScriptedLLM([bad, valid_report()])
    resp, _ = run(llm, settings)
    assert resp.status == "ok"
    assert names(resp) == ["retrieve", "decide", "override", "draft", "validate"]
    assert resp.trace.steps[1].detail["decision"] is None
    assert overrides(resp)[0]["reason"].startswith("malformed decision output")
    assert resp.trace.llm_calls == 2


def test_invalid_draft_then_valid_repair(settings):
    bad = valid_report(next_steps=[{"action": "Do X", "citations": ["RB-FAKE-999#s1"]}])
    llm = ScriptedLLM([draft(), bad, valid_report()])
    resp, _ = run(llm, settings)
    assert resp.status == "ok" and resp.trace.violations == []
    assert names(resp) == ["retrieve", "decide", "draft", "validate", "repair", "validate"]
    assert resp.trace.llm_calls == 3
    repair_prompt = llm.calls[2].user
    assert "RB-FAKE-999#s1" in repair_prompt and "unknown_citation" in repair_prompt
    assert resp.trace.steps[4].detail["violations_fed_back"][0]["type"] == "unknown_citation"


def test_invalid_twice_is_invalid_output(settings):
    bad = valid_report(next_steps=[{"action": "Do X", "citations": []}])
    llm = ScriptedLLM([draft(), bad, bad])
    resp, _ = run(llm, settings)
    assert resp.status == "invalid_output" and resp.report is not None
    assert [v.type for v in resp.trace.violations] == ["missing_citation"]
    assert names(resp).count("repair") == 1 and resp.trace.llm_calls == 3


def test_worst_case_uses_exactly_the_budget(settings):
    bad = valid_report(likely_causes=[])
    llm = ScriptedLLM([rewrite("q2"), draft(), bad, bad])
    resp, _ = run(llm, settings)
    assert resp.trace.llm_calls == settings.agent_max_steps == 4
    assert names(resp) == ["retrieve", "decide", "rewrite_query", "retrieve", "decide",
                           "draft", "validate", "repair", "validate"]


def test_step_budget_exhaustion_forces_draft(settings):
    tight = settings.model_copy(update={"agent_max_steps": 3, "agent_max_query_rewrites": 5})
    llm = ScriptedLLM([rewrite("q2"), valid_report()])
    resp, retriever = run(llm, tight)
    assert len(retriever.calls) == 2
    assert names(resp) == ["retrieve", "decide", "rewrite_query", "retrieve", "override",
                           "draft", "validate"]
    assert overrides(resp)[0]["requested_action"] is None
    assert "step budget" in overrides(resp)[0]["reason"]
    assert resp.trace.llm_calls == 2


def test_tiny_budget_skips_decide_and_repair(settings):
    tiny = settings.model_copy(update={"agent_max_steps": 1})
    llm = ScriptedLLM([valid_report(likely_causes=[])])
    resp, _ = run(llm, tiny)
    assert resp.status == "invalid_output" and resp.trace.llm_calls == 1
    assert names(resp) == ["retrieve", "override", "draft", "validate"]
    assert resp.trace.steps[-1].detail["repair"].startswith("skipped")


def test_long_rationale_is_trimmed_to_two_sentences(settings):
    llm = ScriptedLLM([draft("One. Two. Three. Four."), valid_report()])
    resp, _ = run(llm, settings)
    assert resp.trace.steps[1].detail["rationale"] == "One. Two."


def test_demo_llm_drafts_for_a_real_incident(settings):
    resp, _ = run(DemoLLM(), settings, retriever=FakeRetriever())
    assert resp.status == "ok"
    assert names(resp) == ["retrieve", "decide", "draft", "validate"]


def test_demo_llm_asks_for_a_vague_incident_only_once(settings):
    resp, _ = run(DemoLLM(), settings, retriever=FakeRetriever(), incident="Payments seem flaky?")
    assert resp.status == "needs_clarification" and resp.clarifying_question
    again, _ = run(DemoLLM(), settings, retriever=FakeRetriever(),
                   incident="Payments seem flaky?", clarification_given=True)
    assert again.status == "ok" and "override" not in names(again)
