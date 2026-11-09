"""Integrity checks for the synthetic corpus and the evaluation set.

Pure file checks: no chunker, retriever or LLM. The section counting below mirrors the chunk ID
rule in app/schemas.py (doc_id#sN = Nth `## ` heading, 1-based) on purpose, so a disagreement
with the real chunker shows up as a failing test somewhere rather than silently.
"""

import json
from pathlib import Path
from typing import get_args

import pytest
import yaml

from app.schemas import DocType, Severity

ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = ROOT / "data" / "corpus"
CASES_PATH = ROOT / "data" / "eval" / "cases.jsonl"
DEMO_PATH = ROOT / "data" / "demo_incident.txt"

SEVERITIES = {s.value for s in Severity}
CATEGORIES = {"answerable", "insufficient_evidence", "ambiguous"}
CASE_FIELDS = {
    "id", "category", "incident", "expected_severity", "expected_doc_ids",
    "expected_chunk_ids", "should_abstain", "clarification", "notes",
}
# Topics no corpus doc may cover; they back the insufficient_evidence cases.
UNCOVERED_TERMS = ["kafka", "elasticsearch", "crashlytics", "bgp", "gpu", "cuda"]


def _parse(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    assert lines[0] == "---", f"{path.name}: must start with a '---' line"
    end = lines.index("---", 1)  # ValueError (test failure) if unterminated
    meta = yaml.safe_load("\n".join(lines[1:end])) or {}
    return meta, "\n".join(lines[end + 1:])


def _headings(body: str) -> list[str]:
    return [line[3:].strip() for line in body.split("\n") if line.startswith("## ")]


CORPUS_FILES = sorted(CORPUS_DIR.rglob("*.md"))
DOCS = {p.stem: _parse(p) for p in CORPUS_FILES}


def _chunk_ids() -> set[str]:
    return {
        f"{doc_id}#s{n}"
        for doc_id, (_, body) in DOCS.items()
        for n in range(1, len(_headings(body)) + 1)
    }


def _load_cases() -> list[dict]:
    lines = CASES_PATH.read_text(encoding="utf-8").split("\n")
    return [json.loads(line) for line in lines if line.strip()]


# --------------------------------------------------------------------------- corpus


def test_corpus_is_not_empty():
    assert len(CORPUS_FILES) >= 20


def test_files_use_lf_line_endings():
    for path in [*CORPUS_FILES, CASES_PATH]:
        assert b"\r\n" not in path.read_bytes(), f"{path.name} has CRLF line endings"


@pytest.mark.parametrize("path", CORPUS_FILES, ids=lambda p: p.stem)
def test_doc_front_matter(path: Path):
    meta, body = DOCS[path.stem]
    assert meta.get("doc_id") == path.stem
    assert meta.get("type") in get_args(DocType)
    assert isinstance(meta.get("title"), str) and meta["title"].strip()
    if meta["type"] == "incident":
        assert meta.get("severity") in SEVERITIES
    if "services" in meta:
        assert isinstance(meta["services"], list) and meta["services"]


@pytest.mark.parametrize("path", CORPUS_FILES, ids=lambda p: p.stem)
def test_doc_has_sections(path: Path):
    _, body = DOCS[path.stem]
    headings = _headings(body)
    assert headings, f"{path.stem} has no '## ' sections"
    assert all(headings), f"{path.stem} has an empty heading"


def test_doc_ids_unique():
    stems = [p.stem for p in CORPUS_FILES]
    assert len(stems) == len(set(stems))


def test_uncovered_topics_stay_uncovered():
    for doc_id, (_, body) in DOCS.items():
        text = body.lower()
        for term in UNCOVERED_TERMS:
            assert term not in text, f"{doc_id} mentions uncovered topic '{term}'"


def test_existing_chunk_ids_other_tests_rely_on():
    ids = _chunk_ids()
    for cid in ["RB-DB-001#s1", "RB-DB-001#s2", "RB-DB-001#s3", "POL-SEV-001#s2",
                "INC-2025-014#s3", "RB-NET-002#s3"]:
        assert cid in ids


# --------------------------------------------------------------------------- eval set


CASES = _load_cases()


def test_case_ids_unique_and_fields_present():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids))
    for c in CASES:
        assert set(c) == CASE_FIELDS, f"{c['id']}: fields {sorted(set(c) ^ CASE_FIELDS)}"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_case_labels_valid(case: dict):
    assert case["category"] in CATEGORIES
    assert case["expected_severity"] is None or case["expected_severity"] in SEVERITIES
    assert isinstance(case["incident"], str) and len(case["incident"]) >= 10
    assert isinstance(case["should_abstain"], bool)
    for doc_id in case["expected_doc_ids"]:
        assert doc_id in DOCS, f"unknown doc {doc_id}"
    chunk_ids = _chunk_ids()
    for cid in case["expected_chunk_ids"]:
        assert cid in chunk_ids, f"unknown chunk {cid}"
        assert cid.split("#")[0] in case["expected_doc_ids"], f"{cid} doc not in expected_doc_ids"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_case_category_rules(case: dict):
    if case["category"] == "insufficient_evidence":
        assert case["should_abstain"] is True
        assert set(case["expected_doc_ids"]) <= {"POL-SEV-001"}
    elif case["category"] == "ambiguous":
        assert case["should_abstain"] is False
        assert isinstance(case["clarification"], str) and case["clarification"].strip()
        assert case["expected_severity"] is not None
    else:
        assert case["should_abstain"] is False
        assert case["expected_severity"] is not None
        assert 1 <= len(case["expected_doc_ids"]) <= 4
        assert case["expected_chunk_ids"]


def test_case_001_is_the_demo_incident():
    case = CASES[0]
    assert case["id"] == "case-001"
    assert case["incident"] == DEMO_PATH.read_text(encoding="utf-8").strip()
    assert case["expected_severity"] == "SEV2"
    assert {"RB-DB-001", "INC-2025-014", "POL-SEV-001"} <= set(case["expected_doc_ids"])


def test_all_severities_represented():
    assert {c["expected_severity"] for c in CASES} >= SEVERITIES
