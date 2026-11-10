"""Shared data contracts. Every module imports these; change them deliberately.

Chunk ID rule (used by the chunker, the corpus, and the eval set):
    f"{doc_id}#s{n}" where n is the 1-based index of the document's `## ` heading.
    Text between the front-matter and the first `## ` heading is not a chunk.
"""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- corpus

DocType = Literal["runbook", "incident", "policy"]


class Document(BaseModel):
    doc_id: str
    doc_type: DocType
    title: str
    metadata: dict[str, Any] = Field(default_factory=dict)  # services, severity, ...


class Chunk(BaseModel):
    chunk_id: str  # "RB-DB-001#s2"
    doc_id: str
    ordinal: int  # 1-based
    heading: str
    content: str  # embedded text: "<doc_id> · <title> · <heading>\n<body>"
    content_hash: str


class Evidence(BaseModel):
    """A retrieved chunk as handed to the LLM and recorded in the trace."""

    chunk_id: str
    doc_id: str
    title: str
    heading: str
    content: str
    score: float
    # "pinned" = always-included context (app.retrieval.pinned), not a search result.
    method: Literal["vector", "keyword", "hybrid", "pinned"]


# --------------------------------------------------------------------------- report


class Severity(StrEnum):
    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"
    SEV4 = "SEV4"


# The schema describes *shape*. Grounding policy ("every cause cites >= 1 retrieved chunk")
# is enforced in app/triage/validate.py, because the no_retrieval baseline has nothing to
# cite and must still produce a parseable report.


class Cause(BaseModel):
    description: str
    confidence: Literal["high", "medium", "low"]
    citations: list[str] = Field(default_factory=list)


class NextStep(BaseModel):
    action: str
    citations: list[str] = Field(default_factory=list)


class TriageReport(BaseModel):
    summary: str
    # Severity can be known even when causes are not (e.g. "checkout 30% errors" with no
    # matching runbook). Rules (validator): severity None => insufficient_evidence;
    # insufficient_evidence False => at least one likely cause.
    severity: Severity | None = Field(
        description="Null only when the incident lacks the facts the severity policy needs"
    )
    severity_citations: list[str] = Field(default_factory=list)
    likely_causes: list[Cause] = Field(default_factory=list)
    next_steps: list[NextStep] = Field(default_factory=list)
    insufficient_evidence: bool
    missing_information: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- validation

ViolationType = Literal[
    "schema_error",  # output did not parse into TriageReport
    "unknown_citation",  # cited id not in the retrieved evidence
    "missing_citation",  # cause/step/severity without a citation
    "inconsistent_abstention",  # severity set while insufficient_evidence, or vice versa
]


class Violation(BaseModel):
    type: ViolationType
    detail: str


# --------------------------------------------------------------------------- API + trace

TriageMode = Literal["no_retrieval", "rag", "agent"]
TriageStatus = Literal["ok", "invalid_output", "needs_clarification"]


class TriageRequest(BaseModel):
    incident: str = Field(min_length=10, max_length=8000)
    mode: TriageMode = "rag"
    # Stage 2: answer to a previous clarifying question, appended to the incident.
    clarification: str | None = Field(default=None, max_length=2000)


class TraceStep(BaseModel):
    """One visible step of the pipeline / agent loop. Rendered in the demo UI."""

    name: str  # "retrieve", "generate", "validate", "decide", "rewrite_query", ...
    detail: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0.0


class RetrievedRef(BaseModel):
    chunk_id: str
    score: float
    method: str


class Trace(BaseModel):
    mode: TriageMode
    model: str
    retrieval_mode: str | None = None
    queries: list[str] = Field(default_factory=list)
    retrieved: list[RetrievedRef] = Field(default_factory=list)
    steps: list[TraceStep] = Field(default_factory=list)
    violations: list[Violation] = Field(default_factory=list)
    timings_ms: dict[str, float] = Field(default_factory=dict)  # retrieval, generation, total
    llm_calls: int = 0


class TriageResponse(BaseModel):
    status: TriageStatus
    report: TriageReport | None = None
    clarifying_question: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    trace: Trace
