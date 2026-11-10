"""Disk cache for LLM calls: identical request in, identical recorded answer out.

    CachingLLM(GeminiClient(...), cache_dir=Path(".cache/llm"))

Why: the eval makes ~100 LLM calls per full run, and a free-tier key allows 20 a day.
With the cache, a run that stops on a quota error can be resumed the next day and only
the missing calls go to the provider; re-rendering a report or re-scoring with a new
metric costs nothing. Combined with temperature 0, a cached run is also reproducible.

What makes up the key (any change is a miss, never a stale hit):
model name, system prompt, user prompt, the JSON schema of the requested output type,
temperature, and ``extra_key`` (callers pass provider settings such as the thinking
level). The prompt version needs no special handling: a changed prompt is changed text.

What is cached: every *returned* result, including ones whose text did not parse,
because a malformed answer is the model's answer for that input. Exceptions (rate
limits, timeouts) are never cached, so a failed call is retried on the next run.

Latency caveat: a cache hit returns in microseconds. ``LLMResult.cached`` is set on
hits and copied into the trace, so the eval can report how many calls were replayed
and flag that latency numbers for those units do not include model time.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.llm.base import LLMClient, LLMResult

CACHE_FORMAT = 1


def cache_key(
    *, model: str, system: str, user: str, schema: type[BaseModel], temperature: float,
    extra_key: str = "",
) -> str:
    """SHA-256 over a canonical JSON encoding of everything that determines the answer."""
    payload = {
        "format": CACHE_FORMAT,
        "model": model,
        "system": system,
        "user": user,
        "schema": schema.model_json_schema(),
        "temperature": temperature,
        "extra": extra_key,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class CachingLLM:
    """Implements ``LLMClient`` by wrapping another one. Counts hits and misses."""

    def __init__(self, inner: LLMClient, cache_dir: Path, *, extra_key: str = "") -> None:
        self.inner = inner
        self.model_name = inner.model_name
        self.cache_dir = Path(cache_dir)
        self.extra_key = extra_key
        self.hits = 0
        self.misses = 0

    def _path(self, key: str) -> Path:
        # Two-level fan-out keeps any one directory small.
        return self.cache_dir / key[:2] / f"{key}.json"

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        temperature: float = 0.0,
    ) -> LLMResult:
        key = cache_key(model=self.model_name, system=system, user=user, schema=schema,
                        temperature=temperature, extra_key=self.extra_key)
        path = self._path(key)
        cached = self._read(path)
        if cached is not None:
            self.hits += 1
            return cached.model_copy(update={"cached": True})

        result = self.inner.generate_json(
            system=system, user=user, schema=schema, temperature=temperature
        )
        self.misses += 1
        self._write(path, result)
        return result

    @staticmethod
    def _read(path: Path) -> LLMResult | None:
        try:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            return LLMResult.model_validate(data["result"])
        except (OSError, ValueError, KeyError):
            return None  # missing or corrupt entry: treat as a miss

    @staticmethod
    def _write(path: Path, result: LLMResult) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps({"format": CACHE_FORMAT, "result": result.model_dump()}, indent=1)
        # Write-then-rename so an interrupted run never leaves a half-written entry.
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(body, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
