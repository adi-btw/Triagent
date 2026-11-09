"""Okapi BM25, written out so every term is explainable.

    score(q, d) = sum over query terms t of
        idf(t) * tf(t,d) * (k1 + 1) / (tf(t,d) + k1 * (1 - b + b * |d| / avgdl))

    idf(t) = ln(1 + (N - n_t + 0.5) / (n_t + 0.5))      (Lucene's always-positive variant)

* tf saturates: the 5th "timeout" in a chunk adds far less than the 1st (k1 controls how
  fast; 1.5 is a common default).
* Long chunks are penalised relative to the average length (b=0.75: mostly normalised).
* Rare terms dominate via idf. That is exactly why BM25 shines on logs: `EAI_AGAIN`
  appears in one chunk, so it carries enormous weight, while an embedding model sees
  it as an opaque string of subword pieces.

Query terms are OR-combined: a chunk matching any term gets a score. Log excerpts contain
many terms that no runbook mentions (timestamps, pod names); requiring all would match
nothing.
"""

from __future__ import annotations

import math
from collections import Counter

from app.retrieval.tokenizer import tokenize


class BM25Index:
    def __init__(self, docs: dict[str, str], k1: float = 1.5, b: float = 0.75) -> None:
        """`docs` maps id -> text. Built once; rebuild after the corpus changes."""
        self.k1 = k1
        self.b = b
        self._tf: dict[str, Counter[str]] = {i: Counter(tokenize(t)) for i, t in docs.items()}
        self._len = {i: sum(tf.values()) for i, tf in self._tf.items()}
        n = len(self._tf)
        self._avgdl = (sum(self._len.values()) / n) if n else 0.0
        df: Counter[str] = Counter()
        for tf in self._tf.values():
            df.update(tf.keys())
        self._idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def score(self, query: str) -> dict[str, float]:
        """id -> BM25 score for every doc sharing at least one term with the query.
        Repeated query terms are counted once (a pasted log repeating "ERROR" ten times
        should not make "error" ten times more important)."""
        terms = set(tokenize(query))
        scores: dict[str, float] = {}
        for doc_id, tf in self._tf.items():
            norm = self.k1 * (1 - self.b + self.b * self._len[doc_id] / (self._avgdl or 1.0))
            total = 0.0
            for t in terms:
                f = tf.get(t, 0)
                if f:
                    total += self._idf[t] * f * (self.k1 + 1) / (f + norm)
            if total > 0:
                scores[doc_id] = total
        return scores
