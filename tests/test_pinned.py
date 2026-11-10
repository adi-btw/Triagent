"""Pinned context: the severity policy is always in the evidence, never ranked."""

import pytest

from app.config import Settings
from app.retrieval.pinned import pinned_evidence, with_pinned
from app.triage.pipeline import run_rag
from eval.metrics import retrieval_recall
from tests.fakes import FakeRetriever, ScriptedLLM, make_evidence, valid_report


def settings(**kw) -> Settings:
    return Settings(_env_file=None, llm_provider="fake", **kw)  # type: ignore[call-arg]


def test_pinned_evidence_loads_every_policy_section():
    pinned = pinned_evidence(settings())
    assert [e.chunk_id for e in pinned] == ["POL-SEV-001#s1", "POL-SEV-001#s2"]
    assert all(e.method == "pinned" and e.score == 0.0 for e in pinned)
    assert "SEV2" in pinned[0].content


def test_no_pinned_docs_configured():
    assert pinned_evidence(settings(pinned_doc_ids=[])) == []


def test_unknown_pinned_doc_fails_loudly():
    with pytest.raises(ValueError, match="POL-NOPE"):
        pinned_evidence(settings(pinned_doc_ids=["POL-NOPE"]))


def test_with_pinned_keeps_retrieved_copy_and_order():
    retrieved = [make_evidence("RB-DB-001#s2", "x"), make_evidence("POL-SEV-001#s1", "y")]
    merged = with_pinned(retrieved, pinned_evidence(settings()))
    assert [e.chunk_id for e in merged] == ["RB-DB-001#s2", "POL-SEV-001#s1", "POL-SEV-001#s2"]
    assert merged[1].method != "pinned"  # search found it itself; that stays visible


def test_rag_can_cite_policy_even_when_search_misses_it():
    retriever = FakeRetriever([make_evidence("INC-2025-014#s2", "pool of 15 per pod")])
    report = valid_report(
        severity_citations=["POL-SEV-001#s1"],
        likely_causes=[{"description": "pool exhaustion", "confidence": "high",
                        "citations": ["INC-2025-014#s2"]}],
        next_steps=[{"action": "scale back", "citations": ["INC-2025-014#s2"]}],
    )
    resp = run_rag("checkout 500s, too many clients", retriever=retriever,
                   llm=ScriptedLLM([report]), settings=settings())
    assert resp.status == "ok", resp.trace.violations


def test_recall_metric_ignores_pinned_chunks():
    from tests.test_eval_metrics import result  # shared builder for CaseResult fixtures

    r = result("case-001", expected_doc_ids=["RB-DB-001", "POL-SEV-001"],
               retrieved=["RB-DB-001#s1", "POL-SEV-001#s1"])
    assert retrieval_recall([r])["doc"]["mean"] == 1.0  # both found by search
    r.response.trace.retrieved[1].method = "pinned"
    assert retrieval_recall([r])["doc"]["mean"] == 0.5  # pinned doesn't count
