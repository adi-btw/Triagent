"""Public-demo guardrails (app/demo.py) and their wiring into the API and LLM factory."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

import app.main as main
from app.config import Settings
from app.demo import (
    BudgetedLLM,
    DailyBudget,
    RateLimited,
    SlidingWindowLimiter,
    client_key,
)
from app.deps import get_llm, get_retriever_provider, get_settings
from app.llm.base import LLMResult
from app.llm.cache import CachingLLM
from app.llm.factory import with_cache
from tests.fakes import DemoLLM, FakeRetriever

INCIDENT = "checkout-api returning 500s: FATAL: sorry, too many clients already"


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_limiter_blocks_after_limit_and_reopens_after_window():
    clock = Clock()
    lim = SlidingWindowLimiter(2, window_s=60, clock=clock)
    lim.hit("a")
    lim.hit("a")
    with pytest.raises(RateLimited) as exc:
        lim.hit("a")
    assert 1 <= exc.value.retry_after_s <= 60
    lim.hit("b")  # keys are independent
    clock.t += 61
    lim.hit("a")


def test_rejected_hits_are_not_recorded():
    clock = Clock()
    lim = SlidingWindowLimiter(1, window_s=60, clock=clock)
    lim.hit("a")
    for _ in range(5):
        with pytest.raises(RateLimited):
            lim.hit("a")
    clock.t += 61
    lim.hit("a")  # hammering while blocked did not extend the block


def test_daily_budget_resets_at_utc_midnight():
    now = [datetime(2026, 11, 9, 23, 59, tzinfo=UTC)]
    budget = DailyBudget(2, now=lambda: now[0])
    budget.take()
    budget.take()
    assert budget.remaining == 0
    with pytest.raises(RateLimited) as exc:
        budget.take()
    assert 0 < exc.value.retry_after_s <= 61
    now[0] += timedelta(minutes=2)
    assert budget.remaining == 2
    budget.take()


class Out(BaseModel):
    a: int


class Counting:
    model_name = "m"

    def __init__(self) -> None:
        self.calls = 0

    def generate_json(self, **kw) -> LLMResult:
        self.calls += 1
        return LLMResult(text='{"a": 1}', parsed={"a": 1}, model="m", latency_ms=1)


def test_cache_hits_do_not_spend_the_budget(tmp_path):
    inner = Counting()
    budget = DailyBudget(1)
    llm = CachingLLM(BudgetedLLM(inner, budget), tmp_path)
    for _ in range(5):
        llm.generate_json(system="s", user="u", schema=Out)
    assert inner.calls == 1 and budget.remaining == 0
    with pytest.raises(RateLimited):
        llm.generate_json(system="s", user="new", schema=Out)


def test_factory_wraps_cache_then_budget_in_demo_mode(tmp_path):
    inner = Counting()
    llm = with_cache(inner, Settings(_env_file=None, demo_mode=True, demo_cache_dir=tmp_path))
    assert isinstance(llm, CachingLLM) and llm.cache_dir == tmp_path
    assert isinstance(llm.inner, BudgetedLLM) and llm.inner.inner is inner


@pytest.mark.parametrize("host,xff,hops,expected", [
    ("10.0.0.1", None, 1, "10.0.0.1"),
    ("10.0.0.1", "203.0.113.7", 1, "203.0.113.7"),
    # A client-supplied spoofed entry sits left of the one the proxy appended.
    ("10.0.0.1", "1.2.3.4, 203.0.113.7", 1, "203.0.113.7"),
    ("10.0.0.1", "203.0.113.7, 10.0.0.9", 2, "203.0.113.7"),
    ("10.0.0.1", "203.0.113.7", 0, "10.0.0.1"),
    (None, None, 1, "unknown"),
])
def test_client_key(host, xff, hops, expected):
    assert client_key(host, xff, hops) == expected


@pytest.fixture
def demo_client():
    settings = Settings(_env_file=None, llm_provider="fake", demo_mode=True,
                        demo_requests_per_ip_per_hour=2)
    main._limiter = None
    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_retriever_provider] = lambda: lambda: FakeRetriever()
    main.app.dependency_overrides[get_llm] = DemoLLM
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()
    main._limiter = None


def test_api_returns_429_with_retry_after_past_the_limit(demo_client):
    for _ in range(2):
        assert demo_client.post("/triage", json={"incident": INCIDENT, "mode": "rag"}).is_success
    resp = demo_client.post("/triage", json={"incident": INCIDENT, "mode": "rag"})
    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) > 0 and "per hour" in resp.json()["detail"]
    assert demo_client.get("/health").status_code == 200  # health is never limited


def test_health_reports_demo_mode(demo_client):
    body = demo_client.get("/health").json()
    assert body["demo_mode"] is True and body["demo_requests_per_hour"] == 2


def test_no_limit_outside_demo_mode():
    settings = Settings(_env_file=None, llm_provider="fake")
    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_retriever_provider] = lambda: lambda: FakeRetriever()
    main.app.dependency_overrides[get_llm] = DemoLLM
    try:
        c = TestClient(main.app)
        for _ in range(30):
            assert c.post("/triage", json={"incident": INCIDENT, "mode": "rag"}).is_success
    finally:
        main.app.dependency_overrides.clear()
