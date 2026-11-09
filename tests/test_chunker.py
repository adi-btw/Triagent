import logging

import pytest

from app.ingest.chunker import chunk_document, content_hash
from app.schemas import Document

DOC = Document(doc_id="RB-X-001", doc_type="runbook", title="Example runbook")
BODY = (
    "Preamble that is not a chunk.\n\n"
    "## Symptoms\nIt breaks.\n\n### Detail\nmore\n"
    "## Fix\nRestart it.\n"
)


def test_ids_ordinals_and_headings() -> None:
    chunks = chunk_document(DOC, BODY)
    assert [c.chunk_id for c in chunks] == ["RB-X-001#s1", "RB-X-001#s2"]
    assert [c.ordinal for c in chunks] == [1, 2]
    assert [c.heading for c in chunks] == ["Symptoms", "Fix"]
    assert all(c.doc_id == "RB-X-001" for c in chunks)


def test_content_prefix_and_preamble_dropped() -> None:
    first = chunk_document(DOC, BODY)[0]
    assert first.content.startswith("RB-X-001 · Example runbook · Symptoms\n")
    assert "Preamble" not in first.content
    assert "### Detail" in first.content  # sub-headings stay inside their section
    assert first.content_hash == content_hash(first.content)


def test_crlf_body_gives_identical_chunks() -> None:
    assert chunk_document(DOC, BODY.replace("\n", "\r\n")) == chunk_document(DOC, BODY)


def test_no_headings_means_no_chunks() -> None:
    assert chunk_document(DOC, "just text") == []


def test_long_section_warns_but_stays_one_chunk(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        chunks = chunk_document(DOC, "## Huge\n" + "word " * 500)
    assert len(chunks) == 1
    assert "consider splitting" in caplog.text
