"""Cross-encoder second stage (app/retrieval/rerank.py) with a fake scorer."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.retrieval.rerank import RerankingRetriever, passage_text
from eval.retrieval_eval import VariantRetriever
from tests.fakes import make_evidence


class KeywordReranker:
    """Scores a passage by how many times it contains ``word``."""

    name = "fake-reranker"

    def __init__(self, word: str) -> None:
        self.word = word
        self.calls: list[tuple[str, int]] = []

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        self.calls.append((query, len(passages)))
        return [float(p.count(self.word)) for p in passages]


class ListRetriever:
    label = "list"

    def __init__(self, n: int = 10) -> None:
        self.pool = [
            make_evidence(f"DOC-{i}#s1", content="needle " * (i % 4)) for i in range(n)
        ]
        self.calls: list[tuple[int | None, str | None]] = []

    def retrieve(self, query, k=None, mode=None):
        self.calls.append((k, mode))
        return self.pool[: k or 5]


def test_widens_first_stage_and_returns_top_k_by_reranker_score():
    base, rr = ListRetriever(), KeywordReranker("needle")
    out = RerankingRetriever(base, rr, candidates=8).retrieve("q", k=3, mode="hybrid")
    assert base.calls == [(8, "hybrid")]
    assert rr.calls == [("q", 8)]
    # needle counts by index: 0,1,2,3,0,1,2,3 -> best are 3 and 7 (3 each), then 2 / 6.
    assert [e.chunk_id for e in out] == ["DOC-3#s1", "DOC-7#s1", "DOC-2#s1"]
    assert [e.score for e in out] == [3.0, 3.0, 2.0]


def test_ties_keep_first_stage_order_and_method_is_preserved():
    base = ListRetriever(4)
    out = RerankingRetriever(base, KeywordReranker("absent"), candidates=4).retrieve("q", k=4)
    assert [e.chunk_id for e in out] == [e.chunk_id for e in base.pool]
    assert {e.method for e in out} == {base.pool[0].method}


def test_k_larger_than_candidates_widens_pool_to_k():
    base = ListRetriever(10)
    RerankingRetriever(base, KeywordReranker("needle"), candidates=2).retrieve("q", k=6)
    assert base.calls == [(6, None)]


@pytest.mark.parametrize("query,k", [("", 5), ("   ", 5), ("q", 0)])
def test_empty_query_or_k_returns_nothing(query, k):
    base = ListRetriever()
    assert RerankingRetriever(base, KeywordReranker("x")).retrieve(query, k=k) == []
    assert base.calls == []


def test_passage_text_includes_title_and_heading():
    e = make_evidence("RB-DB-001#s2", content="body")
    text = passage_text(e)
    assert e.title in text and e.heading in text and text.endswith("body")


def test_variant_retriever_routes_rerank_suffix():
    base, rr = ListRetriever(), KeywordReranker("needle")
    v = VariantRetriever(base, RerankingRetriever(base, rr, candidates=6))
    v.retrieve("q", k=2, mode="vector")
    v.retrieve("q", k=2, mode="hybrid+rerank")
    assert base.calls == [(2, "vector"), (6, "hybrid")]
    assert len(rr.calls) == 1


def test_variant_retriever_without_reranker_rejects_rerank_mode():
    with pytest.raises(ValueError):
        VariantRetriever(ListRetriever(), None).retrieve("q", k=2, mode="vector+rerank")


@pytest.mark.slow
def test_real_cross_encoder_prefers_the_relevant_passage():
    from app.retrieval.rerank import FastEmbedReranker

    rr = FastEmbedReranker("Xenova/ms-marco-MiniLM-L-6-v2")
    s = rr.score("postgres too many clients already",
                 ["Postgres connection exhaustion: FATAL too many clients already",
                  "Redis eviction policy and memory limits"])
    assert s[0] > s[1]
