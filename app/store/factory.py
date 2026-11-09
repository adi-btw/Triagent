"""Build the configured store for a given embedder."""

from __future__ import annotations

from app.config import Settings
from app.embeddings.base import Embedder
from app.store.base import VectorStore


def build_store(settings: Settings, embedder: Embedder, *, create: bool = False) -> VectorStore:
    """Return the store selected by `settings.store_backend`.

    The embedder is passed in because the store must know which model produced its
    vectors (memory: name + dim are checked on load; Postgres: dim is checked).

    create=False (serving): the memory index must already exist, otherwise
    IndexNotFoundError tells you to run `python -m scripts.ingest`.
    create=True (ingestion): start an empty memory index if there is none.
    """
    if settings.store_backend == "memory":
        from app.store.memory import MemoryStore

        if create:
            return MemoryStore.open(settings.index_path, embedder.name, embedder.dim)
        return MemoryStore.load(settings.index_path, embedder.name, embedder.dim)
    if settings.store_backend == "postgres":
        from app.store.postgres import PostgresStore

        return PostgresStore(settings.database_url, embedder.dim)
    raise ValueError(f"unknown store backend {settings.store_backend!r}")
