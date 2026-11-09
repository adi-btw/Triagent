"""Integration tests against a real Postgres + pgvector (docker compose up -d).

Run with:  DATABASE_URL=postgresql://triage:triage@localhost:5432/triage pytest -m postgres
Tests run in a throwaway schema, so they never touch the app's own tables.
"""

import os
from collections.abc import Iterator

import pytest

from app.embeddings.hashing import HashingEmbedder
from app.ingest.chunker import chunk_document
from app.schemas import Document

pytestmark = pytest.mark.postgres

psycopg = pytest.importorskip("psycopg")

URL = os.environ.get("DATABASE_URL", "postgresql://triage:triage@localhost:5432/triage")
SCHEMA = "triage_test"
EMB = HashingEmbedder()


@pytest.fixture
def store() -> Iterator[object]:
    from app.store.postgres import PostgresStore

    try:
        admin = psycopg.connect(URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not reachable at DATABASE_URL: {exc}")
    admin.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    admin.execute(f"CREATE SCHEMA {SCHEMA}")
    admin.execute("CREATE EXTENSION IF NOT EXISTS vector")  # lives in public
    sep = "&" if "?" in URL else "?"
    s = PostgresStore(f"{URL}{sep}options=-csearch_path%3D{SCHEMA},public", EMB.dim)
    yield s
    s.close()
    admin.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    admin.close()


def _fill(store) -> None:  # type: ignore[no-untyped-def]
    docs = [
        (Document(doc_id="RB-A", doc_type="runbook", title="DNS"),
         "## Symptoms\ngetaddrinfo EAI_AGAIN\n## Fix\nrestart coredns\n"),
        (Document(doc_id="RB-B", doc_type="runbook", title="Pool"),
         "## Symptoms\ntoo many clients already 53300\n"),
    ]  # fmt: skip
    store.upsert_documents([d for d, _ in docs])
    chunks = [c for d, b in docs for c in chunk_document(d, b)]
    store.upsert_chunks(chunks, EMB.embed_passages([c.content for c in chunks]))


def test_roundtrip_search_and_delete(store) -> None:  # type: ignore[no-untyped-def]
    _fill(store)
    assert store.stats() == {"docs": 2, "chunks": 3}
    assert len(store.existing_hashes()) == 3

    hits = store.vector_search(EMB.embed_query("too many clients already"), 2)
    assert hits[0].chunk_id == "RB-B#s1"
    assert 0.0 < hits[0].score <= 1.0 + 1e-6  # 1 - cosine distance

    kw = store.keyword_search("2026-11-09 ERROR getaddrinfo EAI_AGAIN pod-xyz", 5)
    assert kw[0].chunk_id == "RB-A#s1"  # OR-query: unmatched log tokens don't block it
    assert store.keyword_search("53300", 5)[0].chunk_id == "RB-B#s1"

    store.delete_chunks(["RB-A#s2"])
    store.delete_documents(["RB-B"])  # cascades to its chunks
    assert set(store.existing_hashes()) == {"RB-A#s1"}
    assert store.document_ids() == {"RB-A"}


def test_upsert_is_idempotent(store) -> None:  # type: ignore[no-untyped-def]
    _fill(store)
    _fill(store)
    assert store.stats() == {"docs": 2, "chunks": 3}
