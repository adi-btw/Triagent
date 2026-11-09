"""Tokenizer for keyword search (BM25) and the hashing embedder.

Incident text is full of *identifiers*: `EAI_AGAIN`, `53300`, `max_connections`,
`pool.acquire`, `v2.31.0`. A generic word tokenizer splits these on `_` and `.` and
throws away exactly the signal that makes keyword search worth having. So:

* lowercase everything (log casing is inconsistent: `ERROR` vs `error`);
* a token is a run of word characters (letters, digits, `_`) optionally joined by
  `.`, `-`, `/` or `:` (so `pool.acquire`, `v2.31.0`, `kube-system` survive whole);
* compound tokens also emit their parts (`pool.acquire` -> `pool`, `acquire`), so a
  log line still matches prose that says "pool acquire". `_` is *not* a split point:
  `max_connections` is one name, and `connections` alone is a much weaker signal;
* a short stopword list drops words that only add noise to an OR-style query.
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"\w+(?:[.\-/:]\w+)*")
_SPLIT = re.compile(r"[.\-/:]")

STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the this to "
    "was were will with we our after since".split()
)


def tokenize(text: str) -> list[str]:
    """Lowercased identifier-preserving tokens, in order, with duplicates kept (BM25
    needs term frequencies)."""
    tokens: list[str] = []
    for match in _TOKEN.finditer(text.lower()):
        token = match.group()
        if token in STOPWORDS:
            continue
        tokens.append(token)
        parts = [p for p in _SPLIT.split(token) if p and p not in STOPWORDS]
        if len(parts) > 1:
            tokens.extend(parts)
    return tokens
