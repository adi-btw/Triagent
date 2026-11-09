"""Runner: ambiguous-case resubmission, per-case error handling, end-to-end main()."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.config import Settings
from app.schemas import Trace, TriageReport, TriageRequest, TriageResponse
from app.store.base import IndexNotFoundError
from app.triage import service
from eval import run_eval
from eval.cases import EvalCase, load_cases
from eval.fake_retriever import KeywordOverlapRetriever, load_corpus_chunks
from eval.judge import EvalSettings
from eval.records import CaseResult
from tests.fakes import DemoLLM, FakeRetriever, ScriptedLLM, valid_report

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "eval" / "cases.jsonl"
CORPUS_DIR = ROOT / "data" / "corpus"


@pytest.fixture
def settings():
    return Settings(_env_file=None, llm_provider="fake", top_k=5, corpus_dir=CORPUS_DIR)


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    """EvalSettings reads .env / JUDGE_MODEL; keep tests independent of the dev machine."""
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    monkeypatch.setattr(run_eval, "EvalSettings", lambda: EvalSettings(_env_file=None))


def _case(case_id: str) -> EvalCase:
    return load_cases(CASES_PATH, ids=[case_id])[0]


def _agent_response(status: str, report: dict | None = None, **trace) -> TriageResponse:
    return TriageResponse(
        status=status,
        report=TriageReport.model_validate(report) if report else None,
        clarifying_question="Which service, and what error rate?"
        if status == "needs_clarification" else None,
        trace=Trace(mode="agent", model="scripted", llm_calls=1,
                    timings_ms={"total": 10.0}, **trace),
    )


# --------------------------------------------------------------------------- ambiguous


def test_agent_clarification_is_resubmitted_and_final_response_scored(settings):
    case = _case("case-028")  # ambiguous: "The site feels slow today."
    requests: list[TriageRequest] = []

    def fake_run(request, *, retriever, llm, settings):
        requests.append(request)
        if request.clarification is None:
            return _agent_response("needs_clarification")
        return _agent_response("ok", valid_report())

    res = run_eval.run_case(case, "agent", retriever=FakeRetriever(), llm=DemoLLM(),
                            settings=settings, run_fn=fake_run)
    assert res.asked_clarification and res.resubmitted_with_clarification
    assert res.clarifying_question.startswith("Which service")
    assert [r.clarification for r in requests] == [None, case.clarification]
    assert all(r.incident == case.incident for r in requests)
    assert res.status == "ok" and res.response.report is not None
    assert res.llm_calls == 2 and res.latency_ms == 20.0


def test_monkeypatched_run_triage_is_used(settings, monkeypatch):
    """The harness looks up app.triage.service.run_triage at call time."""
    calls = []

    def fake_run(request, **_):
        calls.append(request.mode)
        return _agent_response("needs_clarification")

    monkeypatch.setattr(service, "run_triage", fake_run)
    res = run_eval.run_case(_case("case-001"), "agent", retriever=None, llm=DemoLLM(),
                            settings=settings)
    # Non-ambiguous case: no scripted answer, so scored as-is and counted as over-asking.
    assert calls == ["agent"]
    assert res.asked_clarification and not res.resubmitted_with_clarification
    assert res.status == "needs_clarification"


def test_rag_runs_ambiguous_case_on_incident_alone(settings):
    llm = ScriptedLLM([valid_report()])
    res = run_eval.run_case(_case("case-028"), "rag", retriever=FakeRetriever(), llm=llm,
                            settings=settings)
    assert len(llm.calls) == 1 and "Additional information" not in llm.calls[0].user
    assert not res.asked_clarification and res.response is not None


# --------------------------------------------------------------------------- errors


def test_retriever_exception_is_recorded_as_error(settings):
    boom = FakeRetriever(error=ConnectionError("index unavailable"))
    res = run_eval.run_case(_case("case-001"), "agent", retriever=boom,
                            llm=DemoLLM(), settings=settings)
    assert res.status == "error" and res.error_type == "ConnectionError"
    assert res.response is None and res.latency_source == "wall"


def test_agent_clarifies_ambiguous_case_then_is_scored(settings):
    # DemoLLM asks a question for short, digit-free incidents like case-028.
    res = run_eval.run_case(_case("case-028"), "agent", retriever=FakeRetriever(),
                            llm=DemoLLM(), settings=settings)
    assert res.asked_clarification and res.status == "ok"


def test_llm_exception_is_recorded(settings):
    llm = ScriptedLLM([RuntimeError("429 RESOURCE_EXHAUSTED")])
    res = run_eval.run_case(_case("case-001"), "rag", retriever=FakeRetriever(), llm=llm,
                            settings=settings)
    assert res.status == "error" and "429" in res.error_message


# --------------------------------------------------------------------------- end to end


def test_main_end_to_end_writes_parseable_files(tmp_path, settings):
    now = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
    code = run_eval.main(
        ["--modes", "no_retrieval", "rag", "agent",
         "--cases", "case-001,case-021,case-028", "--out", str(tmp_path)],
        settings=settings, llm=DemoLLM(), retriever=FakeRetriever(), now=now,
    )
    assert code == 0
    run_dirs = list((tmp_path / "runs").iterdir())
    assert len(run_dirs) == 1 and run_dirs[0].name.startswith("20261109T120000Z-")

    lines = (run_dirs[0] / "raw.jsonl").read_text(encoding="utf-8").splitlines()
    results = [CaseResult.model_validate_json(line) for line in lines]
    assert len(results) == 9  # 3 cases x 3 modes, none dropped
    assert all(r.status != "error" for r in results), [r.error_message for r in results]
    agent = {r.case_id: r for r in results if r.mode == "agent"}
    assert agent["case-028"].asked_clarification  # vague case -> question -> resubmit
    # Judge ran on reports (DemoLLM as judge returns no verdicts -> unjudged, not crash).
    assert any(r.judged for r in results if r.mode == "rag")

    summary = json.loads((run_dirs[0] / "summary.json").read_text(encoding="utf-8"))
    meta = summary["metadata"]
    assert meta["n_cases"] == 3 and meta["smoke"] is True
    assert "triage-v1" in meta["prompt_versions"]
    assert len(meta["cases_sha256"]) == 64 and len(meta["corpus_sha256"]) == 64
    assert summary["metrics"]["by_mode"]["agent"]["validity"]["status"]["error"]["k"] == 0

    report = (tmp_path / f"{run_dirs[0].name}.md").read_text(encoding="utf-8")
    assert report == (tmp_path / "latest.md").read_text(encoding="utf-8")
    assert "SMOKE TEST" in report and "| Metric | no_retrieval | rag | agent |" in report
    assert "AgentNotAvailable" not in report


def test_main_bad_case_id_is_setup_error(tmp_path, settings):
    code = run_eval.main(["--cases", "case-999", "--out", str(tmp_path)],
                         settings=settings, llm=DemoLLM())
    assert code == 2


def test_main_records_retriever_build_failure_per_case(tmp_path, settings, monkeypatch):
    def no_index(_settings):
        raise IndexNotFoundError("no index; run: python -m scripts.ingest")

    monkeypatch.setattr(run_eval, "build_retriever", no_index)
    code = run_eval.main(["--modes", "rag", "--limit", "2", "--no-judge",
                          "--out", str(tmp_path)], settings=settings, llm=DemoLLM())
    assert code == 0  # retriever can't be built -> every rag unit is recorded as an error
    summary = json.loads(next((tmp_path / "runs").glob("*/summary.json")).read_text())
    assert summary["metadata"]["retriever_build_error"].startswith("IndexNotFoundError")
    assert summary["metrics"]["by_mode"]["rag"]["validity"]["status"]["error"]["k"] == 2


# --------------------------------------------------------------------------- fake retriever


def test_fake_retriever_serves_real_chunk_ids():
    chunks = load_corpus_chunks(CORPUS_DIR)
    ids = {c.chunk_id for c in chunks}
    assert "RB-DB-001#s3" in ids and "POL-SEV-001#s1" in ids
    hits = KeywordOverlapRetriever(CORPUS_DIR).retrieve(_case("case-001").incident, k=5)
    assert 0 < len(hits) <= 5 and all(h.method == "keyword" for h in hits)
