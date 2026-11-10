"""Stage 2: the agent. A bounded state machine whose transitions the model chooses.

    retrieve(incident) -> decide --draft_report------------> draft -> validate -> done
                            |  ^                                          |
                            |  +-- retrieve(new query) + merge            +-> repair (once)
                            |         ^                                         -> validate
                            +--rewrite_query
                            +--ask_clarifying_question -> done (needs_clarification)

Who decides what (the core design choice, see docs/agent.md):

* The MODEL picks one of three actions per ``decide`` call and explains why.
* The APPLICATION owns everything else: how many LLM calls a request may make
  (``agent_max_steps``), how many rewrites (``agent_max_query_rewrites``), whether a
  clarifying question is still allowed (never after the reporter already answered one),
  retrieval k and mode, how evidence from several queries is merged, the citation
  allow-list, and the single repair attempt. An action the model is not allowed to take
  any more is *overridden* to ``draft_report`` and the override is written into the
  trace, so nothing the code does behind the model's back is invisible.

Why not an open-ended tool loop ("call tools until you feel done"): with a fixed set of
transitions and hard budgets the worst-case cost and latency are known before the
request starts, every path can be unit-tested with scripted decisions, and the loop
cannot run forever whatever the model says.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.agent.prompts import (
    AGENT_PROMPT_VERSION,
    DECIDE_SYSTEM,
    build_decide_user_prompt,
    build_repair_user_prompt,
)
from app.agent.schemas import ACTIONS, AgentAction, AgentDecision
from app.config import Settings
from app.llm.base import LLMClient
from app.llm.prompts import TRIAGE_SYSTEM, build_rag_user_prompt
from app.retrieval.base import Retriever
from app.retrieval.pinned import pinned_evidence, with_pinned
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
from app.triage import events
from app.triage.pipeline import generate_report, guards_for, ms_since, validate_output

# LLM calls held back for the draft and its one repair. A new ``decide`` call is only
# made if it leaves room for both, so exploring can never starve the report.
RESERVED_CALLS = 2
RATIONALE_MAX_CHARS = 300


@dataclass
class _Run:
    """Mutable state of one request. Lives only for the duration of ``run_agent``."""

    incident: str
    settings: Settings
    budget: int
    clarification_given: bool
    steps: list[TraceStep] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    llm_calls: int = 0
    rewrites: int = 0
    timings: dict[str, float] = field(
        default_factory=lambda: {"retrieval": 0.0, "generation": 0.0, "validation": 0.0}
    )

    def add(self, step: TraceStep, timing: str | None = None) -> None:
        """Record a step and, if given, add its latency to a timings bucket."""
        self.steps.append(step)
        events.step_done(step)
        if timing is not None:
            self.timings[timing] = round(self.timings[timing] + step.latency_ms, 2)


def run_agent(
    incident: str,
    *,
    retriever: Retriever,
    llm: LLMClient,
    settings: Settings,
    clarification_given: bool,
) -> TriageResponse:
    """Triage ``incident`` with model-chosen retrieval/clarification, under app limits.

    Args:
        incident: the text to triage (already including any clarification).
        clarification_given: True when this request *is* the answer to a previous
            clarifying question. Then asking again is not allowed: one round-trip max.

    Returns:
        ``TriageResponse`` with status ``ok``, ``invalid_output`` (same 422 contract as
        RAG) or ``needs_clarification`` (``clarifying_question`` set, no report).

    Raises:
        LLMCallError: the provider failed (the API maps it to 502), as in RAG.
    """
    t_total = time.perf_counter()
    # At least one call: a request always ends in a report or a question.
    run = _Run(
        incident=incident,
        settings=settings,
        budget=max(1, settings.agent_max_steps),
        clarification_given=clarification_given,
    )
    _retrieve(run, retriever, incident)

    # range() is a second, syntactic bound: every iteration that continues spends an LLM
    # call, so the budget check below always breaks first. Belt and braces.
    for _ in range(run.budget):
        if run.llm_calls + 1 + RESERVED_CALLS > run.budget:
            _override(run, requested=None, reason="step budget: no room for another decision")
            break
        blocked = _blocked_actions(run)
        decision = _decide(run, llm, [a for a in ACTIONS if a not in blocked])
        decision = _enforce(run, decision, blocked)
        if decision.action == "draft_report":
            break
        if decision.action == "ask_clarifying_question":
            question = decision.clarifying_question or ""
            run.add(TraceStep(name="ask_clarifying_question", detail={"question": question}))
            return _respond(run, llm, t_total, "needs_clarification", question=question)
        query = decision.rewritten_query or ""
        run.rewrites += 1
        run.add(TraceStep(name="rewrite_query", detail={"query": query, "n": run.rewrites}))
        _retrieve(run, retriever, query)

    report, violations = _draft(run, llm)
    status: TriageStatus = "invalid_output" if violations else "ok"
    return _respond(run, llm, t_total, status, report=report, violations=violations)


# --------------------------------------------------------------------------- evidence


def merge_evidence(existing: list[Evidence], new: list[Evidence], *, cap: int) -> list[Evidence]:
    """Union of two retrievals: one entry per chunk (best score wins), best first, capped.

    Why a union and not "replace with the new results": a rewrite is meant to *add*
    what the first query missed; dropping the first results could lose the chunk that
    was right all along. The cap (2 x top_k) keeps the draft prompt bounded. Ties keep
    first-seen order (``sorted`` is stable), so results are deterministic.
    """
    best: dict[str, Evidence] = {}
    for ev in [*existing, *new]:
        current = best.get(ev.chunk_id)
        if current is None or ev.score > current.score:
            best[ev.chunk_id] = ev
    return sorted(best.values(), key=lambda e: e.score, reverse=True)[:cap]


def _retrieve(run: _Run, retriever: Retriever, query: str) -> None:
    """Retrieve with k and mode from settings (never from the model), then merge."""
    s = run.settings
    t0 = time.perf_counter()
    found = retriever.retrieve(query, k=s.top_k, mode=s.retrieval_mode)
    latency = ms_since(t0)
    known = {e.chunk_id for e in run.evidence}
    run.queries.append(query)
    # The cap applies to retrieved chunks only; pinned context is re-appended after it.
    searched = [e for e in run.evidence if e.method != "pinned"]
    run.evidence = with_pinned(merge_evidence(searched, found, cap=2 * s.top_k), pinned_evidence(s))
    detail = {
        "query": query,
        "k": s.top_k,
        "mode": s.retrieval_mode,
        "results": [{"chunk_id": e.chunk_id, "score": round(e.score, 4)} for e in found],
        "new_chunk_ids": [e.chunk_id for e in found if e.chunk_id not in known],
        "merged_count": len(run.evidence),
        "pinned": [e.chunk_id for e in run.evidence if e.method == "pinned"],
    }
    run.add(TraceStep(name="retrieve", latency_ms=latency, detail=detail), "retrieval")
    events.evidence(run.evidence)


# --------------------------------------------------------------------------- decisions


def _blocked_actions(run: _Run) -> dict[AgentAction, str]:
    """Actions the model may NOT take right now, each with the reason (for the trace).

    ``draft_report`` is never blocked: it is the safe default every path falls back to.
    The clarifying-question limit spans requests: asking ends this request, so the only
    way to "ask twice" is a resubmission that already carries ``clarification``.
    """
    s = run.settings
    blocked: dict[AgentAction, str] = {}
    if run.rewrites >= s.agent_max_query_rewrites:
        blocked["rewrite_query"] = f"query rewrite limit reached ({s.agent_max_query_rewrites})"
    if run.clarification_given:
        blocked["ask_clarifying_question"] = "a clarification was already given (one round-trip)"
    elif s.agent_max_clarifying_questions < 1:
        blocked["ask_clarifying_question"] = "clarifying questions are disabled"
    return blocked


def _decide(run: _Run, llm: LLMClient, allowed: list[AgentAction]) -> AgentDecision:
    """One decision call. Malformed output falls back to ``draft_report`` (recorded)."""
    events.step_started("decide")
    t0 = time.perf_counter()
    result = llm.generate_json(
        system=DECIDE_SYSTEM,
        user=build_decide_user_prompt(
            run.incident, queries=run.queries, evidence=run.evidence, allowed=allowed
        ),
        schema=AgentDecision,
        temperature=run.settings.llm_temperature,
    )
    run.llm_calls += 1
    detail: dict[str, object] = {
        "prompt_version": AGENT_PROMPT_VERSION,
        "allowed": allowed,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cached": result.cached,
    }
    decision: AgentDecision | None = None
    error = "output was not valid JSON"
    if result.parsed is not None:
        try:
            decision = AgentDecision.model_validate(result.parsed)
        except ValidationError as exc:
            error = "; ".join(
                f"{'.'.join(map(str, e['loc'])) or 'decision'}: {e['msg']}" for e in exc.errors()
            )
    if decision is not None:
        detail |= {
            "decision": decision.action,
            "rationale": _short(decision.rationale),
            "rewritten_query": decision.rewritten_query,
            "clarifying_question": decision.clarifying_question,
        }
    else:
        detail |= {"decision": None, "error": error}
    run.add(TraceStep(name="decide", latency_ms=ms_since(t0), detail=detail), "generation")
    if decision is None:
        return _override(run, requested=None, reason=f"malformed decision output: {error}")
    return decision


def _enforce(run: _Run, decision: AgentDecision, blocked: dict[AgentAction, str]) -> AgentDecision:
    """Apply the rules the model cannot be trusted with; override to draft if broken."""
    reason = blocked.get(decision.action)
    if reason is None and decision.rewritten_query is not None:
        tried = {_normalise_query(q) for q in run.queries}
        if _normalise_query(decision.rewritten_query) in tried:
            reason = "rewritten_query repeats a query already tried"
    if reason is None:
        return decision
    return _override(run, requested=decision.action, reason=reason)


def _override(run: _Run, *, requested: AgentAction | None, reason: str) -> AgentDecision:
    """Record that the application replaced the model's choice with ``draft_report``."""
    detail = {"overridden": True, "requested_action": requested, "action": "draft_report",
              "reason": reason}
    run.add(TraceStep(name="override", detail=detail))
    return AgentDecision(action="draft_report", rationale=f"Overridden by the app: {reason}")


def _normalise_query(query: str) -> str:
    return " ".join(query.lower().split())


def _short(text: str, *, sentences: int = 2) -> str:
    """First ``sentences`` sentences, capped in length: rationales are UI text, not essays.

    Truncating (rather than rejecting a long rationale as malformed) keeps a perfectly
    good decision from being thrown away over its explanation's length.
    """
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    short = " ".join(parts[:sentences])
    if len(short) > RATIONALE_MAX_CHARS:
        short = short[: RATIONALE_MAX_CHARS - 3].rstrip() + "..."
    return short


# --------------------------------------------------------------------------- draft


def _draft(run: _Run, llm: LLMClient) -> tuple[TriageReport | None, list[Violation]]:
    """Draft with the stage-1 prompt over the merged evidence; validate; repair once.

    The allow-list is the merged evidence, i.e. exactly the chunks in the draft prompt.
    The repair counts toward the step budget like any other LLM call.
    """
    allowed_ids = {e.chunk_id for e in run.evidence}
    guards = guards_for(run.settings, run.evidence, TRIAGE_SYSTEM)
    result, step = generate_report(
        llm,
        system=TRIAGE_SYSTEM,
        user=build_rag_user_prompt(run.incident, run.evidence),
        settings=run.settings,
        step_name="draft",
    )
    run.llm_calls += 1
    run.add(step, "generation")
    report, violations, check = validate_output(
        result, allowed_ids, require_citations=True, guards=guards
    )
    run.add(check, "validation")
    if not violations:
        return report, violations
    if run.llm_calls >= run.budget:
        check.detail["repair"] = "skipped: step budget exhausted"
        return report, violations

    result, step = generate_report(
        llm,
        system=TRIAGE_SYSTEM,
        user=build_repair_user_prompt(
            run.incident, run.evidence, previous_output=result.text, violations=violations
        ),
        settings=run.settings,
        step_name="repair",
    )
    step.detail |= {
        "agent_prompt_version": AGENT_PROMPT_VERSION,
        "violations_fed_back": [v.model_dump() for v in violations],
    }
    run.llm_calls += 1
    run.add(step, "generation")
    report, violations, check = validate_output(
        result, allowed_ids, require_citations=True, guards=guards
    )
    run.add(check, "validation")
    return report, violations


def _respond(
    run: _Run,
    llm: LLMClient,
    t_total: float,
    status: TriageStatus,
    *,
    report: TriageReport | None = None,
    violations: list[Violation] | None = None,
    question: str | None = None,
) -> TriageResponse:
    trace = Trace(
        mode="agent",
        model=llm.model_name,
        retrieval_mode=run.settings.retrieval_mode,
        queries=run.queries,
        retrieved=[
            RetrievedRef(chunk_id=e.chunk_id, score=e.score, method=e.method)
            for e in run.evidence
        ],
        steps=run.steps,
        violations=violations or [],
        timings_ms={**run.timings, "total": ms_since(t_total)},
        llm_calls=run.llm_calls,
    )
    return TriageResponse(
        status=status,
        report=report,
        clarifying_question=question,
        evidence=run.evidence,
        trace=trace,
    )
