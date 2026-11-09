"""Retrieval-only eval with a mode-dependent fake retriever (no index, no LLM)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.config import Settings
from eval import retrieval_eval as R
from eval.cases import load_cases
from tests.fakes import make_evidence

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "eval" / "cases.jsonl"


class ModeRetriever:
    """vector: always returns a distractor first, then POL-SEV-001.
    hybrid: returns the case's expected chunks (found via the query) in order.
    keyword: raises, to exercise error capture."""

    def __init__(self) -> None:
        self.by_incident = {c.incident: c for c in load_cases(CASES_PATH)}
        self.calls: list[tuple[str, int | None, str | None]] = []

    def retrieve(self, query, k=None, mode=None):
        self.calls.append((query, k, mode))
        if mode == "keyword":
            raise RuntimeError("index missing")
        if mode == "vector":
            return [make_evidence("RB-DISTRACTOR-001#s1"), make_evidence("POL-SEV-001#s1")][:k]
        case = next((c for inc, c in self.by_incident.items() if query.startswith(inc)), None)
        ids = case.expected_chunk_ids if case else []
        return [make_evidence(cid) for cid in ids][:k]


def test_score_ranking_metrics():
    s = R.score_ranking(
        ["POL-SEV-001#s1", "RB-DB-001#s3", "RB-DB-001#s1"],
        ["RB-DB-001", "POL-SEV-001", "INC-2025-014"],
        ["RB-DB-001#s1", "INC-2025-014#s2"],
        "RB-DB-001",
    )
    assert s["doc_recall"] == pytest.approx(2 / 3)
    assert s["chunk_recall"] == 0.5
    assert s["primary_hit"] == 1.0 and s["primary_rank"] == 2
    assert s["mrr"] == pytest.approx(1 / 3)
    miss = R.score_ranking([], ["RB-DB-001"], ["RB-DB-001#s1"], "RB-DB-001")
    assert miss["primary_hit"] == 0.0 and miss["mrr"] == 0.0 and miss["primary_rank"] is None


def test_primary_doc_skips_policy_and_scoring_filter():
    cases = {c.id: c for c in load_cases(CASES_PATH)}
    assert R.primary_doc(cases["case-001"]) == "RB-DB-001"
    skipped = [c for c in cases.values() if not R.is_scored(c)]
    assert skipped and all(c.category == "insufficient_evidence" for c in skipped)


def test_ambiguous_cases_yield_two_queries():
    case = load_cases(CASES_PATH, ids=["case-028"])[0]
    (s1, q1), (s2, q2) = R.queries_for(case)
    assert (s1, q1) == ("ambiguous (vague)", case.incident)
    assert s2 == "ambiguous (+clarification)" and case.clarification in q2


def test_evaluate_separates_modes_slices_and_errors():
    cases = load_cases(CASES_PATH)
    retr = ModeRetriever()
    out = R.evaluate(cases, retr, ["vector", "keyword", "hybrid"], 5)

    assert {k for _, k, _ in retr.calls} == {5}
    hybrid, vector, keyword = (out["overall"][m] for m in ("hybrid", "vector", "keyword"))
    assert hybrid["primary_hit"]["mean"] == 1.0 and hybrid["mrr"]["mean"] == 1.0
    assert vector["primary_hit"]["mean"] == 0.0
    assert keyword["errors"] == keyword["n"] > 0 and keyword["doc_recall"]["mean"] == 0.0
    # Ambiguous cases scored twice; vague text does not match -> hybrid gets nothing.
    assert out["by_slice"]["ambiguous (vague)"]["hybrid"]["primary_hit"]["mean"] == 0.0
    assert out["by_slice"]["ambiguous (+clarification)"]["hybrid"]["primary_hit"]["mean"] == 1.0
    assert out["skipped"] and all("vector" in s["top"] for s in out["skipped"])


def test_main_writes_markdown_and_summary(tmp_path):
    settings = Settings(_env_file=None, corpus_dir=ROOT / "data" / "corpus")
    code = R.main(["--modes", "vector", "hybrid", "--k", "3", "--out", str(tmp_path)],
                  settings=settings, retriever=ModeRetriever(),
                  now=datetime(2026, 11, 9, tzinfo=UTC))
    assert code == 0
    md = (tmp_path / "retrieval-latest.md").read_text(encoding="utf-8")
    assert "| Metric | vector | hybrid |" in md and "Primary-doc hit@k" in md
    assert "ambiguous (+clarification)" in md and "TEST RUN" in md
    summary = json.loads(next((tmp_path / "runs").glob("*-retrieval/summary.json")).read_text())
    assert summary["metadata"]["k"] == 3 and summary["metadata"]["n_cases_skipped"] > 0


def test_main_without_index_is_setup_error(tmp_path):
    # build_retriever is a stub on this branch; on main it fails until ingest has run.
    code = R.main(["--out", str(tmp_path)], settings=Settings(_env_file=None))
    assert code == 2
