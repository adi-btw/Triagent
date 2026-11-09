from pathlib import Path

import pytest

from app.embeddings.hashing import HashingEmbedder
from app.ingest.chunker import chunk_document
from app.schemas import Document
from app.store.base import IndexMismatchError, IndexNotFoundError
from app.store.bm25 import BM25Index
from app.store.memory import MemoryStore

EMB = HashingEmbedder()
DOC_A = Document(doc_id="RB-A", doc_type="runbook", title="DNS failures")
DOC_B = Document(doc_id="RB-B", doc_type="runbook", title="Pool exhaustion")
BODY_A = "## Symptoms\ngetaddrinfo EAI_AGAIN\n## Fix\nrestart coredns\n"
BODY_B = "## Symptoms\ntoo many clients already\n"


def _filled(path: Path | None = None) -> MemoryStore:
    store = MemoryStore(EMB.name, EMB.dim, path)
    store.upsert_documents([DOC_A, DOC_B])
    chunks = chunk_document(DOC_A, BODY_A) + chunk_document(DOC_B, BODY_B)
    store.upsert_chunks(chunks, EMB.embed_passages([c.content for c in chunks]))
    return store


def test_persist_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "idx" / "index.json"
    store = _filled(path)
    store.flush()
    loaded = MemoryStore.load(path, EMB.name, EMB.dim)
    assert loaded.existing_hashes() == store.existing_hashes()
    assert loaded.stats() == store.stats() == {"docs": 2, "chunks": 3, "embedder": EMB.name}
    q = EMB.embed_query("EAI_AGAIN")
    assert loaded.vector_search(q, 3) == store.vector_search(q, 3)


def test_refuses_index_from_another_embedder(tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    _filled(path).flush()
    with pytest.raises(IndexMismatchError, match="hashing-384"):
        MemoryStore.load(path, "fastembed:BAAI/bge-small-en-v1.5", 384)


def test_missing_index_says_how_to_build_it(tmp_path: Path) -> None:
    with pytest.raises(IndexNotFoundError, match="python -m scripts.ingest"):
        MemoryStore.load(tmp_path / "nope.json", EMB.name, EMB.dim)


def test_stale_deletion() -> None:
    store = _filled()
    store.delete_chunks(["RB-A#s2"])
    assert set(store.existing_hashes()) == {"RB-A#s1", "RB-B#s1"}
    store.delete_documents(["RB-A"])
    assert set(store.existing_hashes()) == {"RB-B#s1"}
    assert store.document_ids() == {"RB-B"}
    assert all(e.doc_id == "RB-B" for e in store.vector_search(EMB.embed_query("x"), 5))


def test_keyword_search_exact_identifier_and_no_zero_scores() -> None:
    hits = _filled().keyword_search("ERROR getaddrinfo EAI_AGAIN", 5)
    assert [h.chunk_id for h in hits] == ["RB-A#s1"]
    assert hits[0].method == "keyword" and hits[0].title == "DNS failures"


def test_vector_scores_are_cosine_and_sorted() -> None:
    hits = _filled().vector_search(EMB.embed_query("too many clients already"), 3)
    assert hits[0].chunk_id == "RB-B#s1"
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)
    assert -1.0 <= hits[-1].score <= hits[0].score <= 1.0 + 1e-6


def test_bm25_rare_term_beats_common_term() -> None:
    idx = BM25Index({"a": "error timeout error", "b": "error eai_again", "c": "error"})
    scores = idx.score("error eai_again")
    assert max(scores, key=scores.__getitem__) == "b"
    assert set(scores) == {"a", "b", "c"}
