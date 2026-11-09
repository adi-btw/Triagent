"""HTTP API. Run with ``uvicorn app.main:app --reload``.

The route is a thin adapter: parse ``TriageRequest``, call ``run_triage``, map the
result to a status code. All triage logic lives in ``app.triage``.

Status codes:
    200  status "ok" or "needs_clarification"
    422  status "invalid_output": the body is the *full* TriageResponse (report as
         written, violations, trace), so a client can show why it was rejected.
         (FastAPI also uses 422 for a malformed *request*; that body is {"detail": [...]}.
         Tell them apart by the presence of "status".)
    501  mode "agent" before stage 2 exists
    502  the LLM provider failed after retries
    503  the retriever or LLM could not be built (no index, no API key)

Handlers are plain ``def`` (not ``async def``): the LLM SDK call is blocking, and
FastAPI runs sync handlers in a thread pool so one slow call doesn't block the server.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.deps import (
    LLMDep,
    RetrieverProviderDep,
    ServiceUnavailable,
    SettingsDep,
)
from app.llm.errors import LLMCallError
from app.retrieval.base import Retriever
from app.schemas import TriageRequest, TriageResponse
from app.triage.service import AgentNotAvailable, run_triage

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="AI Incident Triage Assistant",
    version="0.1.0",
    description="Paste an incident; get a severity, likely causes and next steps, "
    "each citing retrieved runbook/incident passages.",
)


@app.exception_handler(ServiceUnavailable)
def _service_unavailable(_: Request, exc: ServiceUnavailable) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(LLMCallError)
def _llm_failed(_: Request, exc: LLMCallError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.post(
    "/triage",
    response_model=TriageResponse,
    responses={
        422: {"model": TriageResponse, "description": "Report failed validation"},
        501: {"description": "Mode not implemented yet"},
        502: {"description": "LLM provider failed"},
        503: {"description": "Retriever or LLM not configured"},
    },
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
    try:
        response = run_triage(request, retriever=retriever, llm=llm, settings=settings)
    except AgentNotAvailable as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
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
    }


# Mounted last so the API routes above take precedence over "/" (Starlette matches in
# order). Conditional, so the API works before the UI exists.
if (STATIC_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
