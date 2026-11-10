"""Pinned context: corpus documents included with every request, regardless of ranking.

Some documents apply to *every* incident. The severity policy (POL-SEV-001) is the
example: the model needs it to assign any severity, but it reads nothing like a log
excerpt, so similarity search often ranks it below the top-k cut-off. Leaving it to
ranking produced reports that correctly refused to guess a severity, which made the
retriever, not the model, the bottleneck.

Pinned chunks are:
* loaded once from the corpus files (backend-independent, deterministic),
* appended *after* the retrieved chunks, never displacing them,
* marked ``method="pinned"`` with score 0, so the trace and UI show they were not
  retrieved, and retrieval metrics exclude them (recall measures the retriever only),
* part of the citation allow-list, so citing the policy is valid.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.config import Settings
from app.ingest.chunker import chunk_document
from app.ingest.loader import load_corpus
from app.schemas import Evidence


@lru_cache(maxsize=8)
def _load_pinned(corpus_dir: str, doc_ids: tuple[str, ...]) -> tuple[Evidence, ...]:
    docs = {doc.doc_id: (doc, body) for doc, body in load_corpus(Path(corpus_dir))}
    missing = [d for d in doc_ids if d not in docs]
    if missing:
        raise ValueError(f"pinned_doc_ids not found in {corpus_dir}: {missing}")
    pinned: list[Evidence] = []
    for doc_id in doc_ids:
        doc, body = docs[doc_id]
        for chunk in chunk_document(doc, body):
            pinned.append(
                Evidence(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    title=doc.title,
                    heading=chunk.heading,
                    content=chunk.content,
                    score=0.0,
                    method="pinned",
                )
            )
    return tuple(pinned)


def pinned_evidence(settings: Settings) -> list[Evidence]:
    """Every chunk of each ``settings.pinned_doc_ids`` document, in corpus order."""
    if not settings.pinned_doc_ids:
        return []
    return list(_load_pinned(str(settings.corpus_dir), tuple(settings.pinned_doc_ids)))


def with_pinned(retrieved: list[Evidence], pinned: list[Evidence]) -> list[Evidence]:
    """Retrieved chunks first (unchanged), then pinned chunks that weren't retrieved.

    A pinned chunk that search also found keeps its retrieved entry, so the trace shows
    the retriever found it on its own.
    """
    seen = {e.chunk_id for e in retrieved}
    return [*retrieved, *(p for p in pinned if p.chunk_id not in seen)]
