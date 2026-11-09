"""End-to-end retrieval quality check on the real corpus with the real embedding model.

Marked slow: the first run downloads bge-small-en-v1.5 (~130 MB) into .cache/fastembed.
Run with:  pytest -m slow tests/test_retrieval_demo.py

Assertions are doc-level ("some chunk of RB-DB-001 is in the top 5"), not exact
positions, so they keep holding as the corpus grows.
"""

from pathlib import Path

import pytest

from app.config import Settings
from app.ingest.pipeline import ingest
from app.retrieval.search import SearchRetriever
from app.schemas import Evidence
from app.store.memory import MemoryStore

pytestmark = pytest.mark.slow

DEMO = Path("data/demo_incident.txt")


@pytest.fixture(scope="module")
def retriever() -> SearchRetriever:
    from app.embeddings.fastembed_embedder import FastEmbedEmbedder

    embedder = FastEmbedEmbedder()
    store = MemoryStore(embedder.name, embedder.dim)
    ingest(Path("data/corpus"), store, embedder)
    return SearchRetriever(store, embedder, Settings(_env_file=None))  # type: ignore[call-arg]


def _best_rank(hits: list[Evidence], doc_id: str) -> int:
    """1-based rank of the doc's best chunk, or a huge number if absent."""
    return next((i for i, h in enumerate(hits, start=1) if h.doc_id == doc_id), 10**9)


@pytest.mark.parametrize("mode", ["vector", "keyword", "hybrid"])
def test_demo_incident_top5_contains_runbook_and_past_incident(
    retriever: SearchRetriever, mode: str
) -> None:
    hits = retriever.retrieve(DEMO.read_text(encoding="utf-8"), k=5, mode=mode)  # type: ignore[arg-type]
    docs = {h.doc_id for h in hits}
    assert {"RB-DB-001", "INC-2025-014"} <= docs, [h.chunk_id for h in hits]


def test_vector_ranks_db_runbook_above_dns_runbook(retriever: SearchRetriever) -> None:
    # The demo log says "timed out after 5000ms", which is literally RB-NET-002's symptom
    # line. A good embedding must still prefer the connection-exhaustion runbook.
    n = retriever.store.stats()["chunks"]
    hits = retriever.retrieve(DEMO.read_text(encoding="utf-8"), k=int(n), mode="vector")
    assert _best_rank(hits, "RB-DB-001") < _best_rank(hits, "RB-NET-002")


def test_query_prefix_applied_once(retriever: SearchRetriever) -> None:
    from app.embeddings.fastembed_embedder import BGE_QUERY_PREFIX

    emb = retriever.embedder
    q = "too many clients"
    assert emb.embed_query(q) == pytest.approx(emb.embed_passages([BGE_QUERY_PREFIX + q])[0])
