"""Metrics on hand-built CaseResult records (no LLM, no retriever)."""

from __future__ import annotations

import pytest

from app.schemas import RetrievedRef, Trace, TriageReport, TriageResponse, Violation
from eval import metrics as M
from eval.records import CaseResult, ClaimJudgement
from tests.fakes import valid_report


def result(
    case_id: str = "case-001",
    *,
    mode: str = "rag",
    category: str = "answerable",
    expected_severity: str | None = "SEV2",
    expected_doc_ids: list[str] | None = None,
    expected_chunk_ids: list[str] | None = None,
    should_abstain: bool = False,
    status: str = "ok",
    report: dict | None = None,
    parsed: bool = True,
    retrieved: list[str] | None = None,
    violations: list[str] | None = None,
    total_ms: float | None = 100.0,
    **extra,
) -> CaseResult:
    response = None
    if violations and status == "ok":
        status = "invalid_output"
    if status != "error":
        trace = Trace(
            mode=mode,
            model="m",
            retrieved=[
                RetrievedRef(chunk_id=c, score=1.0, method="vector") for c in retrieved or []
            ],
            violations=[Violation(type=t, detail="") for t in violations or []],
            timings_ms={"total": total_ms} if total_ms is not None else {},
            llm_calls=1,
        )
        rep = TriageReport.model_validate(report or valid_report()) if parsed else None
        response = TriageResponse(
            status=status, report=rep, trace=trace
        )
    return CaseResult(
        run_id="r",
        case_id=case_id,
        category=category,
        mode=mode,
        expected_severity=expected_severity,
        expected_doc_ids=expected_doc_ids if expected_doc_ids is not None else ["RB-DB-001"],
        expected_chunk_ids=expected_chunk_ids if expected_chunk_ids is not None else [],
        should_abstain=should_abstain,
        status=status,
        response=response,
        latency_ms=total_ms or 0.0,
        llm_calls=0 if status == "error" else 1,
        **extra,
    )


# --------------------------------------------------------------------------- severity


def test_severity_exact_within_one_and_null_prediction():
    results = [
        result("case-001", report=valid_report(severity="SEV2")),  # exact
        result("case-002", report=valid_report(severity="SEV3")),  # off by one
        result("case-003", report=valid_report(severity="SEV4")),  # off by two
        result("case-004", report=valid_report(severity=None, insufficient_evidence=True)),
        result("case-005", expected_severity=None),  # unlabelled: excluded
        result("case-006", parsed=False, violations=["schema_error"]),  # no report: excluded
        result("case-007", status="error"),  # excluded
    ]
    sev = M.severity_accuracy(results)
    assert (sev["exact"]["k"], sev["exact"]["n"]) == (1, 4)
    assert (sev["within_one"]["k"], sev["within_one"]["n"]) == (2, 4)
    lo, hi = sev["exact"]["ci"]
    assert 0 <= lo <= 0.25 <= hi <= 1


def test_confusion_matrix_has_null_column():
    results = [
        result(report=valid_report(severity="SEV3")),
        result(report=valid_report(severity=None, insufficient_evidence=True)),
    ]
    cm = M.confusion_matrix(results)
    assert cm["cols"][-1] == "null"
    row = cm["matrix"][M.SEVERITY_LEVELS.index("SEV2")]
    assert row[M.SEVERITY_LEVELS.index("SEV3")] == 1 and row[-1] == 1


def test_empty_inputs_give_none_not_zero():
    sev = M.severity_accuracy([])
    assert sev["exact"]["value"] is None and sev["exact"]["ci"] is None
    assert M.citation_validity([])["value"] is None
    assert M.latency([])["p50_ms"] is None
    m = M.mode_metrics([])
    assert m["n_results"] == 0 and m["claim_support"] is None


# --------------------------------------------------------------------------- validity


def test_output_validity_counts_statuses_and_violations():
    results = [
        result(),
        result(violations=["unknown_citation", "unknown_citation", "missing_citation"]),
        result(status="needs_clarification", parsed=False),
        result(status="error"),
    ]
    v = M.output_validity(results)
    assert v["n"] == 4
    assert [v["status"][s]["k"] for s in M.STATUSES] == [1, 1, 1, 1]
    assert v["violations"]["unknown_citation"] == 2
    assert v["results_with"]["unknown_citation"] == 1
    assert M.citation_validity(results)["k"] == 1 and M.citation_validity(results)["n"] == 2


# --------------------------------------------------------------------------- retrieval


def test_retrieval_recall_doc_and_chunk_level():
    r1 = result(
        expected_doc_ids=["RB-DB-001", "POL-SEV-001"],
        expected_chunk_ids=["RB-DB-001#s1", "RB-DB-001#s3"],
        retrieved=["RB-DB-001#s1", "INC-2025-014#s2"],
    )
    r2 = result(expected_doc_ids=[], expected_chunk_ids=[], retrieved=["RB-DB-001#s1"])
    rec = M.retrieval_recall([r1, r2])
    assert rec["doc"] == {"mean": 0.5, "n": 1}  # r2 skipped: nothing expected
    assert rec["chunk"] == {"mean": 0.5, "n": 1}


def test_retrieval_recall_is_none_for_no_retrieval():
    assert M.retrieval_recall([result(mode="no_retrieval")]) is None


def test_citation_precision_proxy():
    # valid_report cites POL-SEV-001, RB-DB-001, INC-2025-014 -> 1 of 3 docs expected.
    rec = M.citation_precision([result(expected_doc_ids=["RB-DB-001"])])
    assert rec["mean"] == pytest.approx(1 / 3)
    no_cites = valid_report(
        severity=None, severity_citations=[], likely_causes=[], next_steps=[],
        insufficient_evidence=True,
    )
    assert M.citation_precision([result(report=no_cites)])["n"] == 0


# --------------------------------------------------------------------------- abstention


def test_abstention_rates_and_ambiguous_excluded():
    abstain = valid_report(severity=None, severity_citations=[], insufficient_evidence=True)
    results = [
        result("case-021", category="insufficient_evidence", should_abstain=True, report=abstain),
        result("case-022", category="insufficient_evidence", should_abstain=True),  # missed
        result("case-001"),  # answered, correct
        result("case-002", report=abstain),  # false abstention
        result("case-028", category="ambiguous", report=abstain),  # excluded from accuracy
    ]
    a = M.abstention(results)
    assert (a["correct_abstention"]["k"], a["correct_abstention"]["n"]) == (1, 2)
    assert (a["false_abstention"]["k"], a["false_abstention"]["n"]) == (1, 2)
    assert (a["accuracy"]["k"], a["accuracy"]["n"]) == (2, 4)


def test_zero_cases_in_a_category():
    a = M.abstention([result()])
    assert a["correct_abstention"]["n"] == 0 and a["correct_abstention"]["value"] is None


def test_clarification_and_over_asking_agent_only():
    results = [
        result("case-028", mode="agent", category="ambiguous", asked_clarification=True),
        result("case-029", mode="agent", category="ambiguous"),
        result("case-001", mode="agent", asked_clarification=True),
        result("case-002", mode="agent"),
        result("case-003", mode="agent", status="error"),  # never answered: excluded
    ]
    m = M.mode_metrics(results)
    c = m["clarification"]
    assert (c["clarification_rate"]["k"], c["clarification_rate"]["n"]) == (1, 2)
    assert (c["over_asking"]["k"], c["over_asking"]["n"]) == (1, 2)
    assert M.mode_metrics([result()])["clarification"] is None


# --------------------------------------------------------------------------- judge


def _claim(i: int, verdict: str | None) -> ClaimJudgement:
    return ClaimJudgement(
        claim_id=i, kind="cause", text="t", verdict=verdict, source="judge"
    )


def test_claim_support_shares_and_unjudged():
    results = [
        result("case-001", judged=True, claims=[_claim(0, "supported"), _claim(1, None)]),
        result(
            "case-002",
            judged=True,
            claims=[_claim(0, "partially_supported"), _claim(1, "not_supported")],
        ),
        result("case-003"),  # judge did not run: ignored
    ]
    cs = M.claim_support(results)
    assert cs["claims"] == 3 and cs["unjudged"] == 1 and cs["reports"] == 2
    assert cs["supported"]["k"] == 1 and cs["supported"]["n"] == 3
    assert cs["partially_supported"]["k"] == 1
    assert cs["supported"]["ci"] is not None
    assert M.claim_support([result()]) is None


# --------------------------------------------------------------------------- latency


def test_latency_percentiles_and_wall_fallback():
    results = [result(total_ms=float(ms)) for ms in (100, 200, 300, 400)]
    results.append(result(status="error"))
    results[0].latency_source = "wall"
    lat = M.latency(results)
    assert lat["n"] == 4 and lat["p50_ms"] == 250 and lat["mean_ms"] == 250
    assert lat["p95_ms"] == pytest.approx(385)
    assert lat["mean_llm_calls"] == 1 and lat["wall_fallbacks"] == 1


# --------------------------------------------------------------------------- bootstrap


def test_bootstrap_is_deterministic_with_seed():
    clusters = [(float(i % 3 == 0), 1.0) for i in range(32)]
    a = M.bootstrap_ci(clusters, seed=7)
    assert a == M.bootstrap_ci(clusters, seed=7)
    assert a != M.bootstrap_ci(clusters, seed=8)
    lo, hi = a
    point = sum(c[0] for c in clusters) / len(clusters)
    assert lo < point < hi
    assert hi - lo > 0.2  # n=32: intervals are wide, which is the honest answer


def test_bootstrap_edge_cases():
    assert M.bootstrap_ci([]) is None
    assert M.bootstrap_ci([(0.0, 0.0)]) is None
    assert M.bootstrap_ci([(1.0, 1.0)] * 5) == (1.0, 1.0)


def test_repeats_are_clustered_by_case():
    units = [("case-001", 1.0, 1.0), ("case-001", 0.0, 1.0), ("case-002", 1.0, 1.0)]
    assert sorted(M.cluster_units(units)) == [(1.0, 1.0), (1.0, 2.0)]


def test_compute_all_shapes_and_failures():
    results = [
        result("case-001"),
        result("case-001", mode="agent", status="error", error_type="AgentNotAvailable"),
        result("case-021", category="insufficient_evidence", should_abstain=True),
    ]
    out = M.compute_all(results, ["rag", "agent"])
    assert set(out["by_mode"]) == {"rag", "agent"}
    assert set(out["by_category"]) == {"answerable", "insufficient_evidence"}
    assert out["by_category"]["insufficient_evidence"]["agent"]["n_results"] == 0
    assert [f["error_type"] for f in out["failures"]] == ["AgentNotAvailable"]
