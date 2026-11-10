"""Guardrails for running Triagent as a public demo (``DEMO_MODE=true``).

A public URL plus a paid API key is a cost exposure: anyone can script requests. Demo
mode adds three layers, cheapest first:

1. **LLM cache, pre-seeded.** The UI's sample incidents were run once through every
   mode and the answers committed under ``data/demo_cache`` (see
   ``scripts/seed_demo_cache.py``). Clicking a sample replays them: instant, free, and
   identical to a real run. Demo mode always turns the cache on.
2. **Per-client rate limit** on ``POST /triage`` (``DEMO_REQUESTS_PER_IP_PER_HOUR``),
   sliding one-hour window, HTTP 429 with ``Retry-After``.
3. **Global daily LLM budget** (``DEMO_LLM_CALLS_PER_DAY``): a hard cap on calls that
   actually reach the provider, counted *below* the cache, so replayed samples never
   spend it. When it runs out, requests that need a new call get 429 until 00:00 UTC.

State is in process memory: fine for a single small instance (the deployment target),
reset on restart. Several replicas would need a shared store such as Redis.

Client address: hosted platforms put the caller's IP in ``X-Forwarded-For``. A client
can send that header itself, but each proxy *appends* the address it saw, so the entry
added by the platform's proxy is the last one; ``DEMO_PROXY_HOPS`` says how many trusted
proxies to count back from the right. With 0, the socket address is used.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel

from app.llm.base import LLMClient, LLMResult


class RateLimited(RuntimeError):
    """Raised when a client or the global budget is over its limit. API maps to 429."""

    def __init__(self, message: str, retry_after_s: int) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class SlidingWindowLimiter:
    """At most ``limit`` events per ``window_s`` per key. Thread-safe."""

    def __init__(self, limit: int, window_s: float = 3600.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> None:
        """Record one event for ``key`` or raise ``RateLimited`` (nothing recorded)."""
        now = self._clock()
        with self._lock:
            q = self._events.setdefault(key, deque())
            while q and q[0] <= now - self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                retry = max(1, math.ceil(q[0] + self.window_s - now))
                raise RateLimited(
                    f"Demo limit: {self.limit} triage requests per hour per visitor. "
                    "The sample incidents are cached and stay instant; try again later "
                    "for a custom one.",
                    retry,
                )
            q.append(now)
            # Drop idle keys so a crawler with many IPs can't grow this without bound.
            if len(self._events) > 10_000:
                for k in [k for k, v in self._events.items() if not v]:
                    del self._events[k]


class DailyBudget:
    """Counts provider calls per UTC day; ``take()`` raises once ``limit`` is used."""

    def __init__(self, limit: int, now: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.limit = limit
        self._now = now
        self._day = self._now().date()
        self.used = 0
        self._lock = threading.Lock()

    def take(self) -> None:
        with self._lock:
            now = self._now()
            if now.date() != self._day:
                self._day, self.used = now.date(), 0
            if self.used >= self.limit:
                midnight = datetime.combine(now.date(), datetime.min.time(), UTC)
                retry = int(86400 - (now - midnight).total_seconds()) + 1
                raise RateLimited(
                    "The demo's daily model budget is used up. The sample incidents "
                    "still work (they are cached); custom incidents resume at 00:00 UTC.",
                    retry,
                )
            self.used += 1

    @property
    def remaining(self) -> int:
        with self._lock:
            if self._now().date() != self._day:
                return self.limit
            return max(0, self.limit - self.used)


class BudgetedLLM:
    """Implements ``LLMClient``: spends one unit of ``budget`` per real provider call.

    Wrap it *inside* the cache (cache -> budget -> provider) so cache hits are free.
    """

    def __init__(self, inner: LLMClient, budget: DailyBudget) -> None:
        self.inner = inner
        self.budget = budget
        self.model_name = inner.model_name

    def generate_json(self, *, system: str, user: str, schema: type[BaseModel],
                      temperature: float = 0.0) -> LLMResult:
        self.budget.take()
        return self.inner.generate_json(system=system, user=user, schema=schema,
                                        temperature=temperature)


def client_key(socket_host: str | None, forwarded_for: str | None, proxy_hops: int) -> str:
    """The caller's address, given how many trusted proxies sit in front of the app."""
    if proxy_hops > 0 and forwarded_for:
        parts = [p.strip() for p in forwarded_for.split(",") if p.strip()]
        if len(parts) >= proxy_hops:
            return parts[-proxy_hops]
    return socket_host or "unknown"
