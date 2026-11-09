"""Single entry point used by the API, the CLI and the eval harness.

Keeping dispatch here (not in the FastAPI route) means every caller gets identical
behaviour, and the route stays a thin HTTP adapter.
"""

from __future__ import annotations

from app.config import Settings
from app.llm.base import LLMClient
from app.retrieval.base import Retriever
from app.schemas import TriageRequest, TriageResponse
from app.triage.pipeline import run_no_retrieval, run_rag


class AgentNotAvailable(RuntimeError):
    """Raised for mode="agent" until stage 2 lands (the API maps it to HTTP 501)."""


def incident_text(request: TriageRequest) -> str:
    """The text the pipelines see: the incident, plus the reporter's clarification."""
    if request.clarification:
        return f"{request.incident}\n\nAdditional information from reporter: " + (
            request.clarification
        )
    return request.incident


def run_triage(
    request: TriageRequest,
    *,
    retriever: Retriever | None,
    llm: LLMClient,
    settings: Settings,
) -> TriageResponse:
    """Run the pipeline for ``request.mode``.

    ``retriever`` may be None for ``no_retrieval`` (so the baseline works without an
    index); RAG requires one.
    """
    incident = incident_text(request)
    if request.mode == "no_retrieval":
        return run_no_retrieval(incident, llm=llm, settings=settings)
    if request.mode == "rag":
        if retriever is None:
            raise ValueError("mode='rag' needs a retriever")
        return run_rag(incident, retriever=retriever, llm=llm, settings=settings)
    if request.mode == "agent":
        # Stage 2 seam: replace this line with the agent loop.
        raise AgentNotAvailable("mode='agent' is not implemented yet (stage 2)")
    raise ValueError(f"unknown mode: {request.mode!r}")
