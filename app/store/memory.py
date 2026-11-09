"""In-memory store: numpy for vectors, BM25 for keywords, one JSON file on disk.

Why this exists next to Postgres: the whole project runs with zero infrastructure
(`pip install` and go), and unit tests run in milliseconds. At ~100 chunks an exact
brute-force scan (one matrix-vector product) is faster than any network round trip.

Persistence is a single JSON file that also records the embedder name and dimension,
so an index built with one model is never queried with another (see IndexMismatchError).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np

from app.schemas import Chunk, Document, Evidence
from app.store.base import IndexMismatchError, IndexNotFoundError
from app.store.bm25 import BM25Index

FORMAT_VERSION = 1


class MemoryStore:
    """Implements VectorStore. `path=None` means purely in-memory (flush is a no-op)."""

    def __init__(self, embedder_name: str, dim: int, path: Path | None = None) -> None:
        self.embedder_name = embedder_name
        self.dim = dim
        self.path = path
        self._docs: dict[str, Document] = {}
        self._chunks: dict[str, Chunk] = {}
        self._vectors: dict[str, list[float]] = {}
        # Search structures are derived data, rebuilt lazily after any write.
        self._matrix: np.ndarray | None = None
        self._matrix_ids: list[str] = []
        self._bm25: BM25Index | None = None

    # ------------------------------------------------------------------ persistence
    @classmethod
    def load(cls, path: Path, embedder_name: str, dim: int) -> MemoryStore:
        """Load an existing index, refusing one built with a different embedder."""
        if not path.exists():
            raise IndexNotFoundError(
                f"No index at {path}. Build it first: python -m scripts.ingest"
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("embedder") != embedder_name or data.get("dim") != dim:
            raise IndexMismatchError(
                f"Index at {path} was built with embedder {data.get('embedder')!r} "
                f"(dim {data.get('dim')}), but the configured embedder is {embedder_name!r} "
                f"(dim {dim}). Vectors from different models are not comparable. Rebuild: "
                f"python -m scripts.ingest --rebuild"
            )
        store = cls(embedder_name, dim, path)
        store._docs = {d["doc_id"]: Document.model_validate(d) for d in data["documents"]}
        for row in data["chunks"]:
            vec = row.pop("embedding")
            chunk = Chunk.model_validate(row)
            store._chunks[chunk.chunk_id] = chunk
            store._vectors[chunk.chunk_id] = vec
        return store

    @classmethod
    def open(cls, path: Path, embedder_name: str, dim: int) -> MemoryStore:
        """Load if the file exists, else start empty (what ingestion wants)."""
        if path.exists():
            return cls.load(path, embedder_name, dim)
        return cls(embedder_name, dim, path)

    def flush(self) -> None:
        if self.path is None:
            return
        data: dict[str, Any] = {
            "format": FORMAT_VERSION,
            "embedder": self.embedder_name,
            "dim": self.dim,
            "documents": [self._docs[i].model_dump() for i in sorted(self._docs)],
            "chunks": [
                {**self._chunks[i].model_dump(), "embedding": self._vectors[i]}
                for i in sorted(self._chunks)
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: a crash mid-write never leaves a half-written index behind.
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    # ------------------------------------------------------------------ writes
    def _invalidate(self) -> None:
        self._matrix = None
        self._bm25 = None

    def upsert_documents(self, docs: list[Document]) -> None:
        for doc in docs:
            self._docs[doc.doc_id] = doc
        self._invalidate()

    def upsert_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        for chunk, vec in zip(chunks, embeddings, strict=True):
            if len(vec) != self.dim:
                raise ValueError(
                    f"{chunk.chunk_id}: embedding has dim {len(vec)}, expected {self.dim}"
                )
            if chunk.doc_id not in self._docs:
                raise ValueError(f"{chunk.chunk_id}: unknown doc_id {chunk.doc_id!r}")
            self._chunks[chunk.chunk_id] = chunk
            self._vectors[chunk.chunk_id] = list(vec)
        self._invalidate()

    def existing_hashes(self) -> dict[str, str]:
        return {i: c.content_hash for i, c in self._chunks.items()}

    def document_ids(self) -> set[str]:
        return set(self._docs)

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        for chunk_id in chunk_ids:
            self._chunks.pop(chunk_id, None)
            self._vectors.pop(chunk_id, None)
        self._invalidate()

    def delete_documents(self, doc_ids: list[str]) -> None:
        doomed = set(doc_ids)
        self.delete_chunks([i for i, c in self._chunks.items() if c.doc_id in doomed])
        for doc_id in doomed:
            self._docs.pop(doc_id, None)

    def clear(self) -> None:
        self._docs.clear()
        self._chunks.clear()
        self._vectors.clear()
        self._invalidate()

    # ------------------------------------------------------------------ search
    def _evidence(self, chunk_id: str, score: float, method: str) -> Evidence:
        chunk = self._chunks[chunk_id]
        return Evidence(
            chunk_id=chunk_id,
            doc_id=chunk.doc_id,
            title=self._docs[chunk.doc_id].title,
            heading=chunk.heading,
            content=chunk.content,
            score=score,
            method=method,  # type: ignore[arg-type]
        )

    @staticmethod
    def _top_k(scores: dict[str, float], k: int) -> list[tuple[str, float]]:
        # Sort by score desc, then chunk_id asc, so ties never depend on dict order.
        return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:k]

    def vector_search(self, query_vec: list[float], k: int) -> list[Evidence]:
        """Exact cosine search. Vectors are unit length, so cosine == dot product and the
        whole search is one (n x d) @ (d,) matrix-vector product."""
        if not self._chunks:
            return []
        if self._matrix is None:
            self._matrix_ids = sorted(self._chunks)
            self._matrix = np.asarray([self._vectors[i] for i in self._matrix_ids], np.float32)
        sims = self._matrix @ np.asarray(query_vec, dtype=np.float32)
        scores = {i: float(s) for i, s in zip(self._matrix_ids, sims, strict=True)}
        return [self._evidence(i, s, "vector") for i, s in self._top_k(scores, k)]

    def keyword_search(self, query_text: str, k: int) -> list[Evidence]:
        if self._bm25 is None:
            self._bm25 = BM25Index({i: c.content for i, c in self._chunks.items()})
        scores = self._bm25.score(query_text)
        return [self._evidence(i, s, "keyword") for i, s in self._top_k(scores, k)]

    def stats(self) -> dict[str, int | str]:
        return {
            "docs": len(self._docs),
            "chunks": len(self._chunks),
            "embedder": self.embedder_name,
        }
