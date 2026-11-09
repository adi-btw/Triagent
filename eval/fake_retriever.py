"""Offline stand-in retriever for smoke tests: real corpus chunks, naive keyword overlap.

Used only by the hidden ``--fake-retriever`` flag of ``eval.run_eval``. It exists so
the whole harness (retrieve -> generate -> validate -> judge -> metrics -> report) can
be exercised with no index, no embedding model and no API key. Its scores are NOT a
retrieval result and must never be reported as one; the run metadata labels it.

Chunking mirrors the rule in app/schemas.py (``doc_id#sN`` = Nth ``## `` heading),
like tests/test_corpus.py does, so the chunk ids match the eval labels.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import yaml

from app.config import RetrievalMode
from app.schemas import Evidence

_TOKEN = re.compile(r"[a-z0-9_]{3,}")
_STOP = {
    "the", "and", "for", "with", "that", "this", "are", "was", "from", "not", "but",
    "have", "has", "had", "you", "our", "its", "into", "than", "then", "when", "after",
    "since", "about", "all", "any", "can", "per", "out", "one", "two", "via", "see",
}


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOP}


def load_corpus_chunks(corpus_dir: Path) -> list[Evidence]:
    chunks: list[Evidence] = []
    for path in sorted(corpus_dir.rglob("*.md")):
        lines = path.read_text(encoding="utf-8").split("\n")
        end = lines.index("---", 1)
        meta = yaml.safe_load("\n".join(lines[1:end])) or {}
        doc_id, title = meta.get("doc_id", path.stem), meta.get("title", path.stem)
        sections: list[tuple[str, list[str]]] = []  # (heading, body lines)
        for line in lines[end + 1:]:
            if line.startswith("## "):
                sections.append((line[3:].strip(), []))
            elif sections:
                sections[-1][1].append(line)
        chunks += [
            Evidence(
                chunk_id=f"{doc_id}#s{n}", doc_id=doc_id, title=title, heading=heading,
                content="\n".join(body).strip(), score=0.0, method="keyword",
            )
            for n, (heading, body) in enumerate(sections, 1)
        ]
    return chunks


class KeywordOverlapRetriever:
    """``Retriever`` protocol: score = |query ∩ chunk tokens| / sqrt(|chunk tokens|)."""

    label = "FAKE keyword-overlap over data/corpus (smoke test only, NOT a real retriever)"

    def __init__(self, corpus_dir: Path, *, default_k: int = 5) -> None:
        self._chunks = load_corpus_chunks(corpus_dir)
        self._tokens = [_tokens(f"{c.title} {c.heading} {c.content}") for c in self._chunks]
        self._k = default_k

    def retrieve(
        self, query: str, k: int | None = None, mode: RetrievalMode | None = None
    ) -> list[Evidence]:
        q = _tokens(query)
        scored = [
            (len(q & toks) / math.sqrt(len(toks) or 1), i)
            for i, toks in enumerate(self._tokens)
        ]
        scored.sort(key=lambda s: (-s[0], s[1]))
        top = [(s, i) for s, i in scored[: k or self._k] if s > 0]
        return [self._chunks[i].model_copy(update={"score": round(s, 4)}) for s, i in top]
