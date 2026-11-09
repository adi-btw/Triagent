"""Postgres + pgvector store: same contract as MemoryStore, production-shaped storage.

* Vector search uses pgvector's cosine distance operator `<=>` (0 = same direction,
  2 = opposite). We report score = 1 - distance, i.e. cosine similarity, so scores mean
  the same thing in both backends.
* Keyword search uses the generated `tsv` column (to_tsvector('english', content)) with
  a GIN index, ranked by ts_rank_cd (cover density: rewards query terms that appear
  close together).
* The keyword query is an OR of the query's tokens, built with websearch_to_tsquery,
  which never raises on odd punctuation. With the default AND semantics of
  plainto_tsquery, a pasted log line would need *every* token (timestamps, pod names)
  to appear in one chunk, and would match nothing.
* No ANN index: see migrations/001_init.sql. Exact scan at this scale is sub-millisecond
  and returns the true nearest neighbours.

Caveat: unlike MemoryStore, the schema does not record which embedder produced the
vectors (only their dimension, enforced by VECTOR(384)). Switching embedders requires
`python -m scripts.ingest --backend postgres --rebuild`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

from app.retrieval.tokenizer import tokenize
from app.schemas import Chunk, Document, Evidence
from app.store.base import IndexMismatchError

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "001_init.sql"

_SELECT = "SELECT c.chunk_id, c.doc_id, d.title, c.heading, c.content"


class PostgresStore:
    """Implements VectorStore on psycopg 3. One connection per store instance; every
    write method runs in its own transaction."""

    def __init__(self, database_url: str, dim: int, *, apply_schema: bool = True) -> None:
        self.dim = dim
        self._conn = psycopg.connect(database_url, autocommit=True)
        if apply_schema:
            # Idempotent (IF NOT EXISTS everywhere). Must run before register_vector,
            # which needs the `vector` type to exist.
            self._conn.execute(MIGRATION.read_text(encoding="utf-8"))
        register_vector(self._conn)
        self._check_dim()

    def _check_dim(self) -> None:
        # For the pgvector `vector(n)` type, atttypmod stores n.
        row = self._conn.execute(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
        ).fetchone()
        if row and row[0] > 0 and row[0] != self.dim:
            raise IndexMismatchError(
                f"chunks.embedding is vector({row[0]}) but the embedder produces dim {self.dim}"
            )

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ writes
    def upsert_documents(self, docs: list[Document]) -> None:
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO documents (doc_id, doc_type, title, metadata) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (doc_id) DO UPDATE SET "
                "doc_type = EXCLUDED.doc_type, title = EXCLUDED.title, "
                "metadata = EXCLUDED.metadata",
                [(d.doc_id, d.doc_type, d.title, Jsonb(d.metadata)) for d in docs],
            )

    def upsert_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        rows = [
            (c.chunk_id, c.doc_id, c.ordinal, c.heading, c.content,
             np.asarray(v, dtype=np.float32), c.content_hash)
            for c, v in zip(chunks, embeddings, strict=True)
        ]  # fmt: skip
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks (chunk_id, doc_id, ordinal, heading, content, embedding, "
                "content_hash) VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (chunk_id) DO UPDATE SET doc_id = EXCLUDED.doc_id, "
                "ordinal = EXCLUDED.ordinal, heading = EXCLUDED.heading, "
                "content = EXCLUDED.content, embedding = EXCLUDED.embedding, "
                "content_hash = EXCLUDED.content_hash",
                rows,
            )

    def existing_hashes(self) -> dict[str, str]:
        rows = self._conn.execute("SELECT chunk_id, content_hash FROM chunks").fetchall()
        return {r[0]: r[1] for r in rows}

    def document_ids(self) -> set[str]:
        return {r[0] for r in self._conn.execute("SELECT doc_id FROM documents").fetchall()}

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        if chunk_ids:
            self._conn.execute("DELETE FROM chunks WHERE chunk_id = ANY(%s)", [chunk_ids])

    def delete_documents(self, doc_ids: list[str]) -> None:
        if doc_ids:  # chunks go with them via ON DELETE CASCADE
            self._conn.execute("DELETE FROM documents WHERE doc_id = ANY(%s)", [doc_ids])

    def clear(self) -> None:
        self._conn.execute("TRUNCATE chunks, documents")

    def flush(self) -> None:
        """Every write already committed (autocommit / per-method transactions)."""

    # ------------------------------------------------------------------ search
    @staticmethod
    def _to_evidence(rows: list[Any], method: str) -> list[Evidence]:
        return [
            Evidence(chunk_id=r[0], doc_id=r[1], title=r[2], heading=r[3], content=r[4],
                     score=float(r[5]), method=method)  # type: ignore[arg-type]
            for r in rows
        ]  # fmt: skip

    def vector_search(self, query_vec: list[float], k: int) -> list[Evidence]:
        vec = np.asarray(query_vec, dtype=np.float32)
        rows = self._conn.execute(
            f"{_SELECT}, 1 - (c.embedding <=> %(q)s) AS score "
            "FROM chunks c JOIN documents d USING (doc_id) "
            "ORDER BY c.embedding <=> %(q)s, c.chunk_id LIMIT %(k)s",
            {"q": vec, "k": k},
        ).fetchall()
        return self._to_evidence(rows, "vector")

    @staticmethod
    def or_query(query_text: str) -> str:
        """'pool.acquire timed out' -> '"pool.acquire" or "timed" or "out"' for
        websearch_to_tsquery. Each token is quoted so Postgres's own parser can split it
        (EAI_AGAIN -> 'eai' <-> 'again') consistently with how `tsv` was built."""
        tokens = dict.fromkeys(t.replace('"', "") for t in tokenize(query_text))
        return " or ".join(f'"{t}"' for t in tokens if t)

    def keyword_search(self, query_text: str, k: int) -> list[Evidence]:
        q = self.or_query(query_text)
        if not q:
            return []
        rows = self._conn.execute(
            f"{_SELECT}, ts_rank_cd(c.tsv, query) AS score "
            "FROM chunks c JOIN documents d USING (doc_id), "
            "websearch_to_tsquery('english', %(q)s) AS query "
            "WHERE c.tsv @@ query "
            "ORDER BY score DESC, c.chunk_id LIMIT %(k)s",
            {"q": q, "k": k},
        ).fetchall()
        return self._to_evidence(rows, "keyword")

    def stats(self) -> dict[str, int | str]:
        row = self._conn.execute(
            "SELECT (SELECT count(*) FROM documents), (SELECT count(*) FROM chunks)"
        ).fetchone()
        assert row is not None
        return {"docs": int(row[0]), "chunks": int(row[1])}
