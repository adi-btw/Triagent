"""Local sentence embeddings with fastembed (ONNX Runtime, no PyTorch).

Model: BAAI/bge-small-en-v1.5, 384 dimensions, 512-token input limit, ~130 MB.
Chosen because it is small enough to run on a laptop CPU, scores well on retrieval
benchmarks for its size, and needs no API key.

Asymmetric encoding
-------------------
BGE was trained with an instruction prefix on *queries only*:
    "Represent this sentence for searching relevant passages: <query>"
Passages are encoded as-is. A short query and a long passage are different kinds of
text; the prefix tells the model which side of the search it is encoding.

Applying the prefix exactly once
--------------------------------
We checked the installed fastembed (0.9.1): `TextEmbedding.query_embed` dispatches to
`OnnxTextEmbedding`, which does not override `TextEmbeddingBase.query_embed`, and the
base implementation is a plain passthrough to `embed()`. In other words fastembed does
NOT add the BGE prefix for this model. We therefore add it ourselves and call
`embed()` (not `query_embed()`) for both sides. Calling `embed()` explicitly means a
future fastembed release that starts adding the prefix inside `query_embed` cannot
silently double it.

Normalisation
-------------
fastembed already L2-normalises this model's output, but we normalise again: it is
cheap, idempotent, and the stores rely on "dot product == cosine similarity", so the
guarantee belongs to our code, not to a library default.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
DEFAULT_CACHE_DIR = Path(".cache/fastembed")


def l2_normalise(matrix: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalisation; zero rows are left as zeros."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1.0, norms)


class FastEmbedEmbedder:
    """Implements the Embedder protocol with fastembed's TextEmbedding."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        cache_dir: Path | str = DEFAULT_CACHE_DIR,
    ) -> None:
        # Imported lazily so tests using HashingEmbedder never load onnxruntime.
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir))
        self.dim = int(self._model.embedding_size)
        self.name = f"fastembed:{model_name}"
        # Only BGE models were trained with this instruction; others get no prefix.
        self._query_prefix = BGE_QUERY_PREFIX if "bge" in model_name.lower() else ""

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        matrix = np.asarray(list(self._model.embed(texts)), dtype=np.float32)
        return l2_normalise(matrix).tolist()

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._encode([self._query_prefix + text])[0]
