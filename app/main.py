"""HTTP API. Run with ``uvicorn app.main:app --reload``.

The route is a thin adapter: parse ``TriageRequest``, call ``run_triage``, map the
result to a status code. All triage logic lives in ``app.triage``.

Status codes:
    200  status "ok" or "needs_clarification" (agent mode: ``clarifying_question`` is
         set; resubmit the same incident with ``clarification``)
    422  status "invalid_output": the body is the *full* TriageResponse (report as
         written, violations, trace), so a client can show why it was rejected.
         (FastAPI also uses 422 for a malformed *request*; that body is {"detail": [...]}.
         Tell them apart by the presence of "status".)
    502  the LLM provider failed after retries
    503  the retriever or LLM could not be built (no index, no API key)
    429  demo mode only: per-visitor rate limit or daily model budget (``Retry-After``)

Handlers are plain ``def`` (not ``async def``): the LLM SDK call is blocking, and
FastAPI runs sync handlers in a thread pool so one slow call doesn't block the server.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.demo import RateLimited, SlidingWindowLimiter, client_key
from app.deps import (
    LLMDep,
    RetrieverProviderDep,
    ServiceUnavailable,
    SettingsDep,
)
from app.llm.errors import LLMCallError
from app.retrieval.base import Retriever
from app.schemas import TriageRequest, TriageResponse
from app.triage.service import run_triage

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="Triagent",
    version="0.1.0",
    description="Paste an incident; get a severity, likely causes and next steps, "
    "each citing retrieved runbook/incident passages.",
)


@app.exception_handler(ServiceUnavailable)
def _service_unavailable(_: Request, exc: ServiceUnavailable) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(RateLimited)
def _rate_limited(_: Request, exc: RateLimited) -> JSONResponse:
    return JSONResponse(status_code=429, content={"detail": str(exc)},
                        headers={"Retry-After": str(exc.retry_after_s)})


_limiter: SlidingWindowLimiter | None = None


def demo_rate_limit(request: Request, settings: SettingsDep) -> None:
    """Per-visitor sliding-window limit on /triage; a no-op unless DEMO_MODE is on."""
    global _limiter
    if not settings.demo_mode:
        return
    if _limiter is None or _limiter.limit != settings.demo_requests_per_ip_per_hour:
        _limiter = SlidingWindowLimiter(settings.demo_requests_per_ip_per_hour)
    host = request.client.host if request.client else None
    _limiter.hit(client_key(host, request.headers.get("x-forwarded-for"),
                            settings.demo_proxy_hops))


@app.exception_handler(LLMCallError)
def _llm_failed(_: Request, exc: LLMCallError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.post(
    "/triage",
    response_model=TriageResponse,
    responses={
        422: {"model": TriageResponse, "description": "Report failed validation"},
        502: {"description": "LLM provider failed"},
        503: {"description": "Retriever or LLM not configured"},
        429: {"description": "Demo mode: rate limit or daily budget reached"},
    },
    dependencies=[Depends(demo_rate_limit)],
)
def triage(
    request: TriageRequest,
    settings: SettingsDep,
    llm: LLMDep,
    retriever_provider: RetrieverProviderDep,
) -> Any:
    retriever: Retriever | None = (
        None if request.mode == "no_retrieval" else retriever_provider()
    )
    response = run_triage(request, retriever=retriever, llm=llm, settings=settings)
    if response.status == "invalid_output":
        return JSONResponse(status_code=422, content=response.model_dump(mode="json"))
    return response


@app.get("/health")
def health(settings: SettingsDep, retriever_provider: RetrieverProviderDep) -> dict[str, Any]:
    """Configuration at a glance, plus whether the index actually loads.

    Always 200 (the process is alive); ``index_ok`` / ``index_error`` say whether
    RAG requests will work. It does not call the LLM (that would cost a request).
    """
    try:
        retriever_provider()
        index_ok, index_error = True, None
    except ServiceUnavailable as exc:
        index_ok, index_error = False, str(exc)
    return {
        "status": "ok",
        "backend": settings.store_backend,
        "embedder": settings.embedder,
        "retrieval_mode": settings.retrieval_mode,
        "llm_provider": settings.llm_provider,
        "model": settings.gemini_model if settings.llm_provider == "gemini" else "fake-demo",
        "llm_key_present": bool(settings.gemini_api_key),
        "index_ok": index_ok,
        "index_error": index_error,
        "demo_mode": settings.demo_mode,
        "demo_requests_per_hour": settings.demo_requests_per_ip_per_hour
        if settings.demo_mode else None,
    }


# Mounted last so the API routes above take precedence over "/" (Starlette matches in
# order): /triage, /health, /docs and /openapi.json are never shadowed. Conditional, so
# the API works before the UI exists. The demo UI lives in app/static/.
if (STATIC_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
