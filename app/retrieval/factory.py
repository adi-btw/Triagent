"""Wire embedder + store + retriever from Settings. This is what the API layer calls."""

from __future__ import annotations

from app.config import Settings
from app.embeddings.factory import build_embedder
from app.retrieval.base import Retriever
from app.retrieval.search import SearchRetriever
from app.store.base import IndexNotFoundError
from app.store.factory import build_store


def build_retriever(settings: Settings) -> Retriever:
    """Build a ready-to-query retriever.

    Memory backend: fails fast with IndexNotFoundError if the index file is missing, and
    the check runs *before* the embedding model loads, so the error is instant.
    """
    if settings.store_backend == "memory" and not settings.index_path.exists():
        raise IndexNotFoundError(
            f"No retrieval index at {settings.index_path}. Build it first, run: "
            "python -m scripts.ingest"
        )
    embedder = build_embedder(settings)
    store = build_store(settings, embedder)
    return SearchRetriever(store, embedder, settings)
