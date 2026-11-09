"""The Retriever: vector, keyword, or hybrid search over a VectorStore.

Hybrid = Reciprocal Rank Fusion (Cormack et al., 2009):

    rrf(d) = sum over rankings r containing d of  1 / (K + rank_r(d)),   K = 60, rank 1-based

Why fuse *ranks* and not scores: cosine similarities (~0.5-0.9) and BM25 scores (0-30+,
unbounded, corpus-dependent) live on incomparable scales. Normalising them is fiddly and
fragile; ranks are always comparable. K=60 flattens the curve so that being #1 in one list
is not overwhelmingly better than #3, which rewards chunks that *both* methods like.
"""

from __future__ import annotations

from app.config import RetrievalMode, Settings
from app.embeddings.base import Embedder
from app.schemas import Evidence
from app.store.base import VectorStore

RRF_K = 60
HYBRID_CANDIDATES = 20  # depth taken from each method before fusing


def rrf_fuse(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Fuse ranked id lists. Returns (id, fused_score) best first; ties broken by id so the
    output never depends on input order or dict iteration."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


class SearchRetriever:
    """Implements app.retrieval.base.Retriever."""

    def __init__(self, store: VectorStore, embedder: Embedder, settings: Settings) -> None:
        self.store = store
        self.embedder = embedder
        self.settings = settings

    def retrieve(
        self, query: str, k: int | None = None, mode: RetrievalMode | None = None
    ) -> list[Evidence]:
        """Up to k chunks, best first. k/mode default to settings.top_k/retrieval_mode.

        Evidence.score is cosine similarity (vector), BM25/ts_rank (keyword) or the RRF
        score (hybrid). Scores are only comparable within one mode.
        """
        k = self.settings.top_k if k is None else k
        mode = mode or self.settings.retrieval_mode
        if k <= 0 or not query.strip():
            return []
        if mode == "vector":
            return self.store.vector_search(self.embedder.embed_query(query), k)
        if mode == "keyword":
            return self.store.keyword_search(query, k)
        if mode == "hybrid":
            return self._hybrid(query, k)
        raise ValueError(f"unknown retrieval mode {mode!r}")

    def _hybrid(self, query: str, k: int) -> list[Evidence]:
        depth = max(HYBRID_CANDIDATES, k)
        vector = self.store.vector_search(self.embedder.embed_query(query), depth)
        keyword = self.store.keyword_search(query, depth)
        by_id = {e.chunk_id: e for e in vector + keyword}
        fused = rrf_fuse([[e.chunk_id for e in vector], [e.chunk_id for e in keyword]])
        return [
            by_id[chunk_id].model_copy(update={"score": score, "method": "hybrid"})
            for chunk_id, score in fused[:k]
        ]
