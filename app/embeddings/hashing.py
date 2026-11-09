"""A deterministic toy embedder for tests: feature-hashed bag of words.

Each token is hashed into one of `dim` buckets with a +/-1 sign (the "hashing trick").
The sign makes collisions cancel out on average instead of always adding up. No model,
no download, microseconds per text, so unit tests stay fast and offline.

Quality is poor on purpose: it only knows exact token overlap, so it is a lexical
matcher in vector clothing. Never use it to judge retrieval quality.

Why `hashlib` and not `hash()`: Python salts `hash()` for strings per process
(PYTHONHASHSEED), so vectors would change between runs and a persisted index would be
garbage on reload.
"""

from __future__ import annotations

import hashlib

import numpy as np

from app.retrieval.tokenizer import tokenize


class HashingEmbedder:
    """Implements the Embedder protocol. Queries and passages are encoded identically
    (the asymmetry hook exists for BGE, not for this)."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self.name = f"hashing-{dim}"

    def _embed(self, text: str) -> list[float]:
        vec = np.zeros(self.dim, dtype=np.float64)
        for token in tokenize(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "little")
            sign = 1.0 if value & 1 else -1.0
            vec[(value >> 1) % self.dim] += sign
        norm = np.linalg.norm(vec)
        # An all-stopword text has no features; a zero vector scores 0 against everything.
        return (vec / norm).tolist() if norm > 0 else vec.tolist()

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)
