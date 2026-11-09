"""Single entry point used by the API, the CLI and the eval harness.

Keeping dispatch here (not in the FastAPI route) means every caller gets identical
behaviour, and the route stays a thin HTTP adapter.
"""

from __future__ import annotations

from app.agent.workflow import run_agent
from app.config import Settings
from app.llm.base import LLMClient
from app.retrieval.base import Retriever
from app.schemas import TriageRequest, TriageResponse
from app.triage.pipeline import run_no_retrieval, run_rag


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
    index); RAG and agent require one.

    For the agent, ``clarification_given`` is what enforces "one clarifying round-trip":
    a request that already carries the reporter's answer may not ask again.
    """
    incident = incident_text(request)
    if request.mode == "no_retrieval":
        return run_no_retrieval(incident, llm=llm, settings=settings)
    if retriever is None:
        raise ValueError(f"mode={request.mode!r} needs a retriever")
    if request.mode == "rag":
        return run_rag(incident, retriever=retriever, llm=llm, settings=settings)
    if request.mode == "agent":
        return run_agent(
            incident,
            retriever=retriever,
            llm=llm,
            settings=settings,
            clarification_given=bool(request.clarification and request.clarification.strip()),
        )
    raise ValueError(f"unknown mode: {request.mode!r}")
