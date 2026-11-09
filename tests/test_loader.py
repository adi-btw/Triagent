from pathlib import Path

import pytest

from app.ingest.loader import CorpusError, load_corpus, parse_document

GOOD = "---\ndoc_id: RB-X-001\ntype: runbook\ntitle: Example\nservices: [a, b]\n---\n## One\nbody\n"


def test_parse_maps_type_and_keeps_extra_keys_as_metadata() -> None:
    doc, body = parse_document(GOOD, source="x.md")
    assert doc.doc_id == "RB-X-001"
    assert doc.doc_type == "runbook"
    assert doc.title == "Example"
    assert doc.metadata == {"services": ["a", "b"]}
    assert body.startswith("## One")


def test_crlf_is_normalised() -> None:
    doc, body = parse_document(GOOD.replace("\n", "\r\n"), source="x.md")
    assert doc.doc_id == "RB-X-001"
    assert "\r" not in body


@pytest.mark.parametrize(
    "text",
    [
        "no front matter\n## A\n",
        "---\ndoc_id: X\ntype: runbook\ntitle: T\n## never closed\n",
        "---\ndoc_id: X\ntitle: T\n---\n",  # missing type
        "---\ndoc_id: X\ntype: novel\ntitle: T\n---\n",  # invalid type
        "---\n[unbalanced\n---\n",  # broken YAML
        "---\n- a list\n---\n",  # not a mapping
    ],
)
def test_malformed_input_names_the_file(text: str) -> None:
    with pytest.raises(CorpusError, match="bad-file.md"):
        parse_document(text, source="bad-file.md")


def test_load_corpus_sorted_and_rejects_duplicates(tmp_path: Path) -> None:
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "RB-X-001.md").write_text(GOOD, encoding="utf-8")
    (tmp_path / "RB-Y-001.md").write_text(GOOD.replace("RB-X-001", "RB-Y-001"), encoding="utf-8")
    docs = load_corpus(tmp_path)
    assert [d.doc_id for d, _ in docs] == ["RB-Y-001", "RB-X-001"]  # case-sensitive path order

    (tmp_path / "dup.md").write_text(GOOD, encoding="utf-8")
    with pytest.raises(CorpusError, match="duplicate doc_id"):
        load_corpus(tmp_path)


def test_repo_corpus_loads() -> None:
    ids = {d.doc_id for d, _ in load_corpus(Path("data/corpus"))}
    assert {"RB-DB-001", "RB-NET-002", "INC-2025-014", "POL-SEV-001"} <= ids
