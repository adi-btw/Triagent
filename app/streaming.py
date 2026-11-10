"""Server-Sent Events for ``POST /triage/stream``: watch a triage happen.

    event: started       {"mode", "model"}
    event: evidence      {"items": [{chunk_id, title, heading, score, method}]}
    event: step_started  {"name": "generate" | "decide" | "draft" | "repair"}
    event: step          {"step": TraceStep}
    event: result        {"http_status": 200 | 422, "response": TriageResponse}
    event: error         {"http_status": 403 | 429 | 502 | 503 | 500, "detail": str}

Every stream ends with exactly one ``result`` or ``error``. ``result`` carries the same
body ``/triage`` would return, and ``http_status`` is the code ``/triage`` would use. The
stream itself is always ``200``, because the status line goes out before the work starts.

**Why a thread and a queue.** Triage is blocking code (LLM SDK calls). It runs in a
worker thread, like the sync ``/triage`` handler. Its events cross to the event loop
through ``loop.call_soon_threadsafe`` into an ``asyncio.Queue``, so the loop never
blocks. The worker runs in a copy of the request's context, so the request id in logs
stays the same.

**Keep-alive.** A ``: ping`` comment goes out every 15 s, so proxies that drop idle
connections (Render's included) don't cut a slow local model off mid-run.

**Client goes away.** The stream stops writing. The worker finishes its current call and
then ends, because a blocking HTTP call to the model can't be interrupted safely. The
step budget already bounds how long that takes.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import Request

from app.demo import DemoCacheMiss, RateLimited
from app.llm.errors import LLMCallError
from app.schemas import TriageResponse
from app.triage import events

PING_EVERY_S = 15.0
_DONE = object()


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def error_status(exc: Exception) -> int:
    from app.deps import ServiceUnavailable  # local: avoid an import cycle at startup

    for kind, code in ((DemoCacheMiss, 403), (RateLimited, 429), (LLMCallError, 502),
                       (ServiceUnavailable, 503)):
        if isinstance(exc, kind):
            return code
    return 500


async def stream_triage(
    request: Request,
    work: Callable[[], TriageResponse],
    *,
    mode: str,
    model: str,
    on_result: Callable[[TriageResponse], None] | None = None,
) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Any] = asyncio.Queue()

    def put(item: Any) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, item)

    def run() -> None:
        try:
            with events.listening(lambda ev, data: put((ev, data))):
                response = work()
            if on_result is not None:
                on_result(response)
            code = 422 if response.status == "invalid_output" else 200
            put(("result", {"http_status": code, "response": response.model_dump(mode="json")}))
        except Exception as exc:  # every failure becomes one terminal error event
            put(("error", {"http_status": error_status(exc), "detail": str(exc),
                           "type": type(exc).__name__}))
        finally:
            put(_DONE)

    ctx = contextvars.copy_context()
    task = loop.run_in_executor(None, ctx.run, run)
    yield sse("started", {"mode": mode, "model": model})
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=PING_EVERY_S)
            except TimeoutError:
                if await request.is_disconnected():
                    return
                yield ": ping\n\n"
                continue
            if item is _DONE:
                break
            yield sse(*item)
    finally:
        # Let the worker finish in the background, but don't leave its exception unread.
        task.add_done_callback(lambda t: t.exception())
