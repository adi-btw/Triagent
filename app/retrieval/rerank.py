"""Second-stage reranking with a cross-encoder.

    first stage  (vector / keyword / hybrid)  ->  top ``rerank_candidates`` chunks
    second stage (cross-encoder)              ->  rescored, top k returned

Why two stages: a bi-encoder (the embedder) encodes the query and each passage
*separately*, so it can pre-compute every passage vector and search all of them in one
matrix product, but it never sees query and passage together. A cross-encoder reads
the pair ``(query, passage)`` jointly and outputs one relevance score, which is far more
accurate (it can tell that "too many clients already" in a log line is exactly what
the connection-exhaustion runbook's symptoms section describes) but costs one model
pass per pair. So the cheap retriever narrows 79 chunks to ~20 and the expensive model
orders those 20.

Model: ``Xenova/ms-marco-MiniLM-L-6-v2`` via fastembed (ONNX, CPU, ~80 MB). Trained on
MS MARCO web-search relevance; small enough to rerank 20 passages in well under a
second on a laptop. Scores are raw logits: higher is more relevant, only comparable
within one query.

What the reranker sees: the chunk's title and heading followed by its content, the same
fields the LLM sees, so a section titled "Symptoms" under "Postgres connection
exhaustion" is scored with that context.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from app.config import RetrievalMode
from app.retrieval.base import Retriever
from app.schemas import Evidence

DEFAULT_CACHE_DIR = Path(".cache/fastembed")


class Reranker(Protocol):
    name: str

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        """One relevance score per passage, in input order. Higher is more relevant."""
        ...


class FastEmbedReranker:
    """Implements Reranker with fastembed's ``TextCrossEncoder``."""

    def __init__(self, model_name: str, cache_dir: Path | str = DEFAULT_CACHE_DIR) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder  # lazy: tests never load it

        self._model = TextCrossEncoder(model_name=model_name, cache_dir=str(cache_dir))
        self.name = f"fastembed:{model_name}"

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        return [float(s) for s in self._model.rerank(query, list(passages))]


def passage_text(e: Evidence) -> str:
    return f"{e.title} - {e.heading}\n{e.content}"


class RerankingRetriever:
    """Implements Retriever: first-stage ``base`` search, then cross-encoder reorder.

    ``Evidence.score`` becomes the reranker score; ``method`` keeps the first-stage
    mode so the trace still says how the chunk was found.
    """

    def __init__(self, base: Retriever, reranker: Reranker, *, candidates: int = 20) -> None:
        self.base = base
        self.reranker = reranker
        self.candidates = candidates
        self.label = f"{getattr(base, 'label', type(base).__name__)} + {reranker.name}"

    def retrieve(
        self, query: str, k: int | None = None, mode: RetrievalMode | None = None
    ) -> list[Evidence]:
        settings = getattr(self.base, "settings", None)
        k = (settings.top_k if settings else 5) if k is None else k
        if k <= 0 or not query.strip():
            return []
        pool = self.base.retrieve(query, k=max(self.candidates, k), mode=mode)
        scores = self.reranker.score(query, [passage_text(e) for e in pool])
        # Stable tie-break on first-stage order, so equal scores never shuffle.
        order = sorted(range(len(pool)), key=lambda i: (-scores[i], i))
        return [pool[i].model_copy(update={"score": scores[i]}) for i in order[:k]]
