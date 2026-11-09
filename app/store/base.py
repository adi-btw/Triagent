"""The storage contract shared by the in-memory and Postgres backends.

The store owns *both* search methods (vector and keyword) because each backend has its
own best implementation: numpy + hand-written BM25 in memory, pgvector + tsvector in
Postgres. The retriever above it only fuses and formats results, so it does not care
which backend it talks to.
"""

from __future__ import annotations

from typing import Protocol

from app.schemas import Chunk, Document, Evidence


class IndexNotFoundError(FileNotFoundError):
    """The memory index file has not been built yet."""


class IndexMismatchError(ValueError):
    """The stored vectors were produced by a different embedder than the one configured.

    Vectors from two different models live in unrelated coordinate systems: cosine
    similarity between them is meaningless, and the failure would be silent (just bad
    rankings). So we refuse loudly instead.
    """


class VectorStore(Protocol):
    # ----------------------------------------------------------------- ingestion
    def upsert_documents(self, docs: list[Document]) -> None: ...

    def upsert_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """Insert or replace chunks (by chunk_id) together with their vectors."""
        ...

    def existing_hashes(self) -> dict[str, str]:
        """chunk_id -> content_hash of everything stored; drives incremental ingestion."""
        ...

    def document_ids(self) -> set[str]: ...

    def delete_chunks(self, chunk_ids: list[str]) -> None: ...

    def delete_documents(self, doc_ids: list[str]) -> None:
        """Delete documents and all their chunks."""
        ...

    def clear(self) -> None:
        """Remove everything (used by `ingest --rebuild`)."""
        ...

    def flush(self) -> None:
        """Make writes durable (memory: write the JSON file; Postgres: no-op)."""
        ...

    # ----------------------------------------------------------------- search
    def vector_search(self, query_vec: list[float], k: int) -> list[Evidence]:
        """Top-k chunks by cosine similarity, best first, method="vector"."""
        ...

    def keyword_search(self, query_text: str, k: int) -> list[Evidence]:
        """Top-k chunks by lexical relevance, best first, method="keyword". Chunks that
        share no term with the query are not returned."""
        ...

    def stats(self) -> dict[str, int | str]:
        """At least {"docs": n, "chunks": m}."""
        ...
