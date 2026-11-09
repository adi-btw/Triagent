"""Idempotent, incremental ingestion: corpus on disk -> chunks + vectors in a store.

Algorithm (a tiny "diff and apply"):
1. Load and chunk the whole corpus (cheap: it's text processing).
2. Ask the store for chunk_id -> content_hash of what it already has.
3. Embed only chunks that are new or whose hash changed (embedding is the slow part).
4. Delete chunks and documents that no longer exist on disk.

Running it twice on an unchanged corpus embeds nothing; editing one section re-embeds
exactly that one chunk. This makes "just re-run ingest" always safe, which is the point.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.embeddings.base import Embedder
from app.ingest.chunker import chunk_document
from app.ingest.loader import load_corpus
from app.schemas import Chunk
from app.store.base import VectorStore


@dataclass(frozen=True)
class IngestStats:
    docs: int
    chunks: int
    embedded: int
    unchanged: int
    deleted: int  # stale chunks removed

    def __str__(self) -> str:
        return (
            f"docs={self.docs} chunks={self.chunks} embedded={self.embedded} "
            f"unchanged={self.unchanged} deleted={self.deleted}"
        )


def ingest(corpus_dir: Path | str, store: VectorStore, embedder: Embedder) -> IngestStats:
    """Bring `store` in sync with `corpus_dir`, re-embedding only what changed."""
    loaded = load_corpus(corpus_dir)
    chunks: list[Chunk] = [c for doc, body in loaded for c in chunk_document(doc, body)]

    existing = store.existing_hashes()
    todo = [c for c in chunks if existing.get(c.chunk_id) != c.content_hash]
    current_ids = {c.chunk_id for c in chunks}
    stale_chunks = sorted(set(existing) - current_ids)
    current_docs = {doc.doc_id for doc, _ in loaded}
    stale_docs = sorted(store.document_ids() - current_docs)

    # Order matters for Postgres foreign keys: documents before their chunks.
    store.upsert_documents([doc for doc, _ in loaded])  # cheap; picks up metadata edits
    if todo:
        store.upsert_chunks(todo, embedder.embed_passages([c.content for c in todo]))
    store.delete_chunks(stale_chunks)
    store.delete_documents(stale_docs)
    store.flush()

    return IngestStats(
        docs=len(loaded),
        chunks=len(chunks),
        embedded=len(todo),
        unchanged=len(chunks) - len(todo),
        deleted=len(stale_chunks),
    )
