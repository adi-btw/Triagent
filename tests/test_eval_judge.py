from app.config import Settings
from app.schemas import Trace, TriageReport, TriageResponse
from eval.judge import (
    JUDGE_SYSTEM,
    EvalSettings,
    JudgeOutput,
    extract_claims,
    judge_model_name,
    judge_response,
)
from tests.fakes import DEMO_EVIDENCE, ScriptedLLM, valid_report


def _response(report: dict, evidence=DEMO_EVIDENCE, mode="rag") -> TriageResponse:
    return TriageResponse(
        status="ok",
        report=TriageReport.model_validate(report),
        evidence=list(evidence),
        trace=Trace(mode=mode, model="m"),
    )


def test_extract_claims_numbers_causes_then_steps():
    claims = extract_claims(TriageReport.model_validate(valid_report()))
    assert [(c.claim_id, c.kind) for c in claims] == [(0, "cause"), (1, "step")]


def test_judge_batches_claims_and_sees_only_claims_and_passages():
    llm = ScriptedLLM(
        [
            {
                "verdicts": [
                    {"claim_id": 0, "verdict": "supported", "reason": "Passage says so."},
                    {"claim_id": 1, "verdict": "partially_supported", "reason": "Half."},
                ]
            }
        ]
    )
    report = valid_report()
    out = judge_response(_response(report), llm)
    assert out.calls == 1 and out.error is None
    assert [c.verdict for c in out.claims] == ["supported", "partially_supported"]

    call = llm.calls[0]
    assert call.schema is JudgeOutput and call.system == JUDGE_SYSTEM
    # The cited passages' full text is there...
    assert DEMO_EVIDENCE[0].content in call.user  # RB-DB-001#s1, cited by the cause
    assert DEMO_EVIDENCE[1].content in call.user  # RB-DB-001#s3, cited by the step
    # ...but not the rest of the report, nor uncited evidence.
    assert report["summary"] not in call.user
    assert DEMO_EVIDENCE[3].content not in call.user  # POL-SEV-001#s1 only backs severity


def test_uncited_and_unknown_citations_are_ruled_without_llm():
    report = valid_report(
        likely_causes=[{"description": "x", "confidence": "low", "citations": []}],
        next_steps=[{"action": "y", "citations": ["RB-NOPE-001#s1"]}],
    )
    llm = ScriptedLLM([])  # any call would raise
    out = judge_response(_response(report), llm)
    assert out.calls == 0
    assert [(c.verdict, c.source) for c in out.claims] == [
        ("not_supported", "no_citations"),
        ("not_supported", "no_passages"),
    ]


def test_no_retrieval_is_not_supported_by_construction():
    report = valid_report(
        severity_citations=[],
        likely_causes=[{"description": "pool exhausted", "confidence": "high", "citations": []}],
        next_steps=[{"action": "scale down", "citations": []}],
    )
    out = judge_response(_response(report, evidence=[], mode="no_retrieval"), ScriptedLLM([]))
    assert out.calls == 0 and all(c.verdict == "not_supported" for c in out.claims)


def test_bad_or_partial_judge_output_is_recorded_as_unjudged():
    out = judge_response(_response(valid_report()), ScriptedLLM(["not json"]))
    assert out.error and all(c.verdict is None for c in out.claims)

    partial = ScriptedLLM(
        [{"verdicts": [{"claim_id": 0, "verdict": "supported", "reason": "ok"}]}]
    )
    out = judge_response(_response(valid_report()), partial)
    assert [c.verdict for c in out.claims] == ["supported", None]
    assert "claim ids [1]" in out.error


def test_judge_exception_does_not_raise():
    out = judge_response(_response(valid_report()), ScriptedLLM([RuntimeError("429")]))
    assert out.error.startswith("RuntimeError") and out.calls == 1


def test_judge_model_defaults_to_generation_model():
    s = Settings(_env_file=None, llm_provider="gemini", gemini_model="gen-model")
    assert judge_model_name(s, EvalSettings(_env_file=None)) == "gen-model"
    assert judge_model_name(s, EvalSettings(_env_file=None, judge_model="judge-x")) == "judge-x"
