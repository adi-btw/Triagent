"""The per-(case, mode, repeat) record the harness writes to ``raw.jsonl``.

One flat, self-contained record per run unit, on purpose:

* The labels are copied in (``expected_*``), so metrics can be recomputed from
  ``raw.jsonl`` alone, without re-reading a ``cases.jsonl`` that may have changed since.
* ``status`` has a fourth value, ``"error"``, that the API does not have: the harness
  must count a crashed case (rate limit, ``AgentNotAvailable``, timeout) instead of
  dropping it. A mode that errors on 30% of cases is not "accurate on the other 70%".
* The full final ``TriageResponse`` is kept so any number in the report can be traced
  back to what the model actually wrote.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas import Severity, TriageMode, TriageResponse

ResultStatus = Literal["ok", "invalid_output", "needs_clarification", "error"]
Verdict = Literal["supported", "partially_supported", "not_supported"]
VerdictSource = Literal["judge", "no_citations", "no_passages"]


class ClaimJudgement(BaseModel):
    """One claim (a likely cause or a next step) and the judge's verdict on it.

    ``verdict`` is None when the judge was asked but returned nothing usable for this
    claim ("unjudged"); such claims are counted separately, never silently scored.
    ``source`` says where the verdict came from: the LLM judge, or a rule applied
    without calling it (no citations / none of the cited ids had a passage).
    """

    claim_id: int
    kind: Literal["cause", "step"]
    text: str
    citations: list[str] = Field(default_factory=list)
    verdict: Verdict | None
    reason: str = ""
    source: VerdictSource


class CaseResult(BaseModel):
    run_id: str
    case_id: str
    category: str
    mode: TriageMode
    repeat: int = 0

    # labels, copied from the case
    expected_severity: Severity | None
    expected_doc_ids: list[str]
    expected_chunk_ids: list[str]
    should_abstain: bool

    status: ResultStatus
    error_type: str | None = None
    error_message: str | None = None

    # ambiguous-case protocol (see run_eval.run_case)
    asked_clarification: bool = False
    clarifying_question: str | None = None
    resubmitted_with_clarification: bool = False

    response: TriageResponse | None = None  # the final response that is scored

    # costs, summed over every run_triage call made for this unit
    latency_ms: float = 0.0  # trace.timings_ms.total, or wall time if absent
    latency_source: Literal["trace", "wall"] = "trace"
    llm_calls: int = 0
    tokens: int | None = None  # input + output, when the client reported them
    prompt_versions: list[str] = Field(default_factory=list)

    # judge
    judged: bool = False
    judge_calls: int = 0
    judge_error: str | None = None
    claims: list[ClaimJudgement] = Field(default_factory=list)
