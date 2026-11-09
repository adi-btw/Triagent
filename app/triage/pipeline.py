"""Stage 1 pipelines: basic RAG and the no-retrieval baseline.

RAG is three fixed steps, always in this order, each timed and recorded as a
``TraceStep`` so the UI can show exactly what happened:

    retrieve (incident text -> top-k chunks)
    generate (system prompt + evidence + incident -> JSON report)
    validate (deterministic: schema, citation allow-list, abstention consistency)

There is no loop and no model-chosen control flow here; that is stage 2 (agent).
The no-retrieval baseline skips retrieval and exists to *measure* what retrieval buys:
the eval compares the two on the same incidents.

Status contract: any violation -> ``"invalid_output"`` (the API returns 422), else
``"ok"``. An invalid report is still returned when it parsed, so a human can see what
the model wrote, but callers must not treat it as a usable answer.
"""

from __future__ import annotations

import time
from typing import Any

from app.config import Settings
from app.llm.base import LLMClient, LLMResult
from app.llm.prompts import (
    NO_RETRIEVAL_SYSTEM,
    PROMPT_VERSION,
    TRIAGE_SYSTEM,
    build_no_retrieval_user_prompt,
    build_rag_user_prompt,
)
from app.retrieval.base import Retriever
from app.schemas import (
    Evidence,
    RetrievedRef,
    Trace,
    TraceStep,
    TriageReport,
    TriageResponse,
    TriageStatus,
    Violation,
)
from app.triage.validate import validate_report


def _ms_since(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def run_rag(
    incident: str, *, retriever: Retriever, llm: LLMClient, settings: Settings
) -> TriageResponse:
    """Retrieve evidence for ``incident``, generate a cited report, validate it."""
    t_total = time.perf_counter()

    t0 = time.perf_counter()
    evidence = retriever.retrieve(incident, k=settings.top_k, mode=settings.retrieval_mode)
    retrieval_ms = _ms_since(t0)
    retrieve_step = TraceStep(
        name="retrieve",
        latency_ms=retrieval_ms,
        detail={
            "k": settings.top_k,
            "mode": settings.retrieval_mode,
            "results": [{"chunk_id": e.chunk_id, "score": round(e.score, 4)} for e in evidence],
        },
    )

    result, generate_step = _generate(
        llm,
        system=TRIAGE_SYSTEM,
        user=build_rag_user_prompt(incident, evidence),
        settings=settings,
    )

    evidence_ids = {e.chunk_id for e in evidence}
    report, violations, validate_step = _validate(result, evidence_ids, require_citations=True)

    trace = Trace(
        mode="rag",
        model=llm.model_name,
        retrieval_mode=settings.retrieval_mode,
        queries=[incident],
        retrieved=[
            RetrievedRef(chunk_id=e.chunk_id, score=e.score, method=e.method) for e in evidence
        ],
        steps=[retrieve_step, generate_step, validate_step],
        violations=violations,
        timings_ms={
            "retrieval": retrieval_ms,
            "generation": generate_step.latency_ms,
            "validation": validate_step.latency_ms,
            "total": _ms_since(t_total),
        },
        llm_calls=1,
    )
    return _response(report, violations, evidence, trace)


def run_no_retrieval(incident: str, *, llm: LLMClient, settings: Settings) -> TriageResponse:
    """Baseline: same output schema, no documents. Citations must be empty."""
    t_total = time.perf_counter()
    result, generate_step = _generate(
        llm,
        system=NO_RETRIEVAL_SYSTEM,
        user=build_no_retrieval_user_prompt(incident),
        settings=settings,
    )
    # Empty allow-list: every id the baseline cites is, by definition, invented.
    report, violations, validate_step = _validate(result, set(), require_citations=False)
    trace = Trace(
        mode="no_retrieval",
        model=llm.model_name,
        steps=[generate_step, validate_step],
        violations=violations,
        timings_ms={
            "retrieval": 0.0,
            "generation": generate_step.latency_ms,
            "validation": validate_step.latency_ms,
            "total": _ms_since(t_total),
        },
        llm_calls=1,
    )
    return _response(report, violations, [], trace)


def _generate(
    llm: LLMClient, *, system: str, user: str, settings: Settings
) -> tuple[LLMResult, TraceStep]:
    t0 = time.perf_counter()
    result = llm.generate_json(
        system=system, user=user, schema=TriageReport, temperature=settings.llm_temperature
    )
    step = TraceStep(
        name="generate",
        latency_ms=_ms_since(t0),
        detail={
            "prompt_version": PROMPT_VERSION,
            "model": result.model,
            "temperature": settings.llm_temperature,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "parsed_json": result.parsed is not None,
        },
    )
    return result, step


def _validate(
    result: LLMResult, evidence_ids: set[str], *, require_citations: bool
) -> tuple[TriageReport | None, list[Violation], TraceStep]:
    t0 = time.perf_counter()
    # Prefer the client's parse; fall back to raw text so the validator can explain why.
    raw: dict[str, Any] | str = result.parsed if result.parsed is not None else result.text
    report, violations = validate_report(raw, evidence_ids, require_citations=require_citations)
    step = TraceStep(
        name="validate",
        latency_ms=_ms_since(t0),
        detail={
            "require_citations": require_citations,
            "allowed_ids": sorted(evidence_ids),
            "violations": [v.model_dump() for v in violations],
        },
    )
    return report, violations, step


def _response(
    report: TriageReport | None,
    violations: list[Violation],
    evidence: list[Evidence],
    trace: Trace,
) -> TriageResponse:
    status: TriageStatus = "invalid_output" if violations else "ok"
    return TriageResponse(status=status, report=report, evidence=evidence, trace=trace)
