"""Disk cache for LLM calls (app/llm/cache.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.config import Settings
from app.llm.base import LLMResult
from app.llm.cache import CachingLLM, cache_key
from app.llm.errors import LLMCallError
from app.llm.factory import with_cache


class Out(BaseModel):
    answer: str


class Other(BaseModel):
    value: int


class CountingLLM:
    model_name = "count-1"

    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def generate_json(self, *, system, user, schema, temperature=0.0) -> LLMResult:
        self.calls += 1
        if self.fail:
            raise LLMCallError("429 quota")
        text = json.dumps({"answer": user})
        return LLMResult(text=text, parsed={"answer": user}, model=self.model_name,
                         latency_ms=1234.0, input_tokens=10, output_tokens=5)


def call(llm, user="u", system="s", schema=Out, temperature=0.0) -> LLMResult:
    return llm.generate_json(system=system, user=user, schema=schema, temperature=temperature)


def test_second_identical_call_is_served_from_disk(tmp_path: Path):
    inner = CountingLLM()
    llm = CachingLLM(inner, tmp_path)
    first, second = call(llm), call(llm)
    assert inner.calls == 1
    assert (llm.hits, llm.misses) == (1, 1)
    assert not first.cached and second.cached
    assert second.parsed == first.parsed and second.input_tokens == 10


def test_cache_survives_a_new_wrapper(tmp_path: Path):
    call(CachingLLM(CountingLLM(), tmp_path))
    inner = CountingLLM()
    assert call(CachingLLM(inner, tmp_path)).cached
    assert inner.calls == 0


@pytest.mark.parametrize("change", [
    {"user": "other"}, {"system": "other"}, {"schema": Other}, {"temperature": 0.7},
])
def test_any_input_change_is_a_miss(tmp_path: Path, change):
    inner = CountingLLM()
    llm = CachingLLM(inner, tmp_path)
    call(llm)
    call(llm, **change)
    assert inner.calls == 2


def test_model_and_extra_key_are_part_of_the_key():
    base = dict(system="s", user="u", schema=Out, temperature=0.0)
    assert cache_key(model="a", **base) != cache_key(model="b", **base)
    assert cache_key(model="a", **base) != cache_key(model="a", extra_key="thinking=low", **base)
    assert cache_key(model="a", **base) == cache_key(model="a", **base)


def test_errors_are_not_cached(tmp_path: Path):
    with pytest.raises(LLMCallError):
        call(CachingLLM(CountingLLM(fail=True), tmp_path))
    inner = CountingLLM()
    assert not call(CachingLLM(inner, tmp_path)).cached
    assert inner.calls == 1


def test_unparsed_output_is_cached_too(tmp_path: Path):
    class Garbage(CountingLLM):
        def generate_json(self, **kw) -> LLMResult:
            self.calls += 1
            return LLMResult(text="not json", parsed=None, model="g", latency_ms=1.0)

    inner = Garbage()
    llm = CachingLLM(inner, tmp_path)
    call(llm)
    replay = call(llm)
    assert inner.calls == 1 and replay.parsed is None and replay.text == "not json"


def test_corrupt_entry_is_a_miss_and_gets_rewritten(tmp_path: Path):
    inner = CountingLLM()
    llm = CachingLLM(inner, tmp_path)
    call(llm)
    for f in tmp_path.rglob("*.json"):
        f.write_text("{truncated", encoding="utf-8")
    assert not call(llm).cached
    assert call(llm).cached
    assert inner.calls == 2


def test_with_cache_respects_the_setting(tmp_path: Path):
    inner = CountingLLM()
    assert with_cache(inner, Settings(llm_cache=False)) is inner
    wrapped = with_cache(inner, Settings(llm_cache=True, llm_cache_dir=tmp_path))
    assert isinstance(wrapped, CachingLLM) and wrapped.model_name == "count-1"
