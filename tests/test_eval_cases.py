import json
from pathlib import Path

import pytest

from eval.cases import CATEGORIES, load_cases, sha256_dir, sha256_file

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "eval" / "cases.jsonl"


def _case(**overrides):
    case = {
        "id": "case-901",
        "category": "answerable",
        "incident": "checkout-api 500s since the deploy, 20% of requests",
        "expected_severity": "SEV2",
        "expected_doc_ids": ["RB-DB-001", "POL-SEV-001"],
        "expected_chunk_ids": ["RB-DB-001#s1"],
        "should_abstain": False,
        "clarification": None,
        "notes": "",
    }
    case.update(overrides)
    return case


def _write(tmp_path: Path, *cases: dict) -> Path:
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(json.dumps(c) for c in cases) + "\n", encoding="utf-8")
    return path


def test_real_eval_set_loads():
    cases = load_cases(CASES_PATH)
    assert len(cases) == 32
    assert {c.category for c in cases} == set(CATEGORIES)


def test_filter_by_ids_and_limit():
    cases = load_cases(CASES_PATH, ids=["case-005", "case-001"])
    assert [c.id for c in cases] == ["case-001", "case-005"]  # file order, not argv order
    assert len(load_cases(CASES_PATH, limit=3)) == 3


def test_unknown_id_raises():
    with pytest.raises(ValueError, match="unknown case ids"):
        load_cases(CASES_PATH, ids=["case-999"])


@pytest.mark.parametrize(
    "overrides",
    [
        {"expected_severity": "SEV 2"},
        {"expected_chunk_ids": ["RB-DB-002#s1"]},  # doc not in expected_doc_ids
        {"category": "ambiguous"},  # no clarification
        {"clarification": "it is checkout"},  # clarification on a non-ambiguous case
        {"should_abstain": True},  # answerable must not abstain
    ],
)
def test_inconsistent_labels_raise(tmp_path, overrides):
    with pytest.raises(ValueError):
        load_cases(_write(tmp_path, _case(**overrides)))


def test_duplicate_ids_raise(tmp_path):
    with pytest.raises(ValueError, match="duplicate"):
        load_cases(_write(tmp_path, _case(), _case()))


def test_hashes_are_stable_and_content_sensitive(tmp_path):
    (tmp_path / "a.md").write_text("one", encoding="utf-8")
    (tmp_path / "b.md").write_text("two", encoding="utf-8")
    first = sha256_dir(tmp_path)
    assert sha256_dir(tmp_path) == first
    (tmp_path / "b.md").write_text("two!", encoding="utf-8")
    assert sha256_dir(tmp_path) != first
    assert len(sha256_file(tmp_path / "a.md")) == 64
