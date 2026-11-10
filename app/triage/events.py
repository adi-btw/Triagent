"""Progress events from inside a triage run, for streaming (``POST /triage/stream``).

The pipelines call ``emit(...)`` at the points a person waiting would care about: the
evidence is in, a model call started, a step finished. With no listener installed,
which covers ``/triage``, the eval and the CLI, ``emit`` does nothing. So the pipelines
take no new parameter and behave the same everywhere.

The listener lives in a ``ContextVar``, so it belongs to one request even with many
requests running in the server's thread pool at once.

What is streamed is **progress, not the report's text.** A report is only shown after the
validator accepts it, and streaming tokens as they arrive would put unvalidated claims
and citations on screen. They could vanish a second later or never be accepted. So the
report arrives once, validated, in the final ``result`` event. See docs/streaming.md.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from app.schemas import Evidence, TraceStep

Listener = Callable[[str, dict[str, Any]], None]
_listener: ContextVar[Listener | None] = ContextVar("triage_listener", default=None)


@contextmanager
def listening(fn: Listener) -> Iterator[None]:
    token = _listener.set(fn)
    try:
        yield
    finally:
        _listener.reset(token)


def emit(event: str, **data: Any) -> None:
    fn = _listener.get()
    if fn is not None:
        fn(event, data)


def step_started(name: str) -> None:
    """A model call is about to start: the slow part, worth telling the user about."""
    emit("step_started", name=name)


def step_done(step: TraceStep) -> None:
    emit("step", step=step.model_dump(mode="json"))


def evidence(items: list[Evidence]) -> None:
    """The current evidence set (titles and scores, not the full passages)."""
    emit("evidence", items=[{"chunk_id": e.chunk_id, "title": e.title, "heading": e.heading,
                             "score": round(e.score, 4), "method": e.method} for e in items])
