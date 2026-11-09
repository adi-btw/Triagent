"""Build the configured embedder. The rest of the app only sees the Embedder protocol."""

from __future__ import annotations

from app.config import Settings
from app.embeddings.base import Embedder


def build_embedder(settings: Settings) -> Embedder:
    """`settings.embedder` picks the implementation: "fastembed" (real, downloads the model
    once into .cache/fastembed) or "hashing" (deterministic toy for tests)."""
    if settings.embedder == "hashing":
        from app.embeddings.hashing import HashingEmbedder

        return HashingEmbedder(dim=settings.embedding_dim)
    if settings.embedder == "fastembed":
        from app.embeddings.fastembed_embedder import FastEmbedEmbedder

        return FastEmbedEmbedder(model_name=settings.embedding_model)
    raise ValueError(f"unknown embedder {settings.embedder!r}")
