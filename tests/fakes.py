"""Shared test fakes. Import from here in any test module:

    from tests.fakes import FakeRetriever, ScriptedLLM, make_evidence, DEMO_EVIDENCE,
        valid_report

* ``FakeRetriever``: implements the ``Retriever`` protocol from a fixed list (or a
  function of the query); records every call; can be told to raise.
* ``ScriptedLLM``: re-exported from ``app.llm.fake`` (queued replies or a reply
  function; records calls).
* ``make_evidence``: build an ``Evidence`` from just a chunk id.
* ``DEMO_EVIDENCE``: hand-written chunks from RB-DB-001 / INC-2025-014 / POL-SEV-001
  that match data/demo_incident.txt.
* ``valid_report``: a TriageReport dict that passes validation against DEMO_EVIDENCE.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.config import RetrievalMode
from app.llm.fake import DemoLLM, LLMCall, ScriptedLLM
from app.schemas import Evidence

__all__ = [
    "DEMO_EVIDENCE",
    "DemoLLM",
    "FakeRetriever",
    "LLMCall",
    "RetrieveCall",
    "ScriptedLLM",
    "make_evidence",
    "valid_report",
]


def make_evidence(
    chunk_id: str,
    content: str = "placeholder content",
    *,
    title: str | None = None,
    heading: str = "Section",
    score: float = 0.5,
    method: str = "vector",
) -> Evidence:
    """``make_evidence("RB-DB-001#s2")`` -> Evidence with doc_id "RB-DB-001"."""
    doc_id = chunk_id.split("#", 1)[0]
    return Evidence(
        chunk_id=chunk_id,
        doc_id=doc_id,
        title=title or doc_id,
        heading=heading,
        content=content,
        score=score,
        method=method,  # type: ignore[arg-type]
    )


DEMO_EVIDENCE: list[Evidence] = [
    make_evidence(
        "RB-DB-001#s1",
        'Clients fail with "FATAL: sorry, too many clients already". Application-side '
        "pools report acquire timeouts. Error rate rises within minutes of a scale-out.",
        title="PostgreSQL connection exhaustion",
        heading="Symptoms",
        score=0.82,
    ),
    make_evidence(
        "RB-DB-001#s3",
        "Fastest: scale the deployment back to its previous replica count. Or lower "
        "DB_POOL_SIZE so replicas x pool size stays under 190. Do NOT raise "
        "max_connections on orders-db without DBA approval.",
        title="PostgreSQL connection exhaustion",
        heading="Mitigation",
        score=0.74,
    ),
    make_evidence(
        "INC-2025-014#s2",
        "Each checkout-api pod opens a pool of 15 connections (DB_POOL_SIZE=15). At 16 "
        "pods, demand was 240 connections against max_connections=200 on orders-db.",
        title="Checkout errors after autoscaling event",
        heading="Root cause",
        score=0.71,
    ),
    make_evidence(
        "POL-SEV-001#s1",
        "SEV1: checkout or payments fully unavailable, or >50% error rate on a revenue "
        "path. SEV2: revenue path degraded (5-50% errors). SEV3: revenue path <5% errors. "
        "SEV4: no customer impact.",
        title="Incident severity levels",
        heading="Levels",
        score=0.55,
    ),
]


def valid_report(**overrides: Any) -> dict[str, Any]:
    """A report that passes ``validate_report`` against ``DEMO_EVIDENCE`` ids."""
    report: dict[str, Any] = {
        "summary": "checkout-api 500s from orders-db connection exhaustion after scale-out.",
        "severity": "SEV2",
        "severity_citations": ["POL-SEV-001#s1"],
        "likely_causes": [
            {
                "description": "14 pods x pool size exceeds max_connections=200.",
                "confidence": "high",
                "citations": ["RB-DB-001#s1", "INC-2025-014#s2"],
            }
        ],
        "next_steps": [
            {"action": "Scale checkout-api back to 6 replicas.", "citations": ["RB-DB-001#s3"]}
        ],
        "insufficient_evidence": False,
        "missing_information": [],
    }
    report.update(overrides)
    return report


@dataclass
class RetrieveCall:
    query: str
    k: int | None
    mode: RetrievalMode | None


@dataclass
class FakeRetriever:
    """``Retriever`` double.

    ``results`` is either a fixed list (returned for every query, truncated to k) or a
    function ``query -> list[Evidence]``. Set ``error`` to make ``retrieve`` raise it.
    """

    results: list[Evidence] | Callable[[str], list[Evidence]] = field(
        default_factory=lambda: list(DEMO_EVIDENCE)
    )
    error: Exception | None = None
    calls: list[RetrieveCall] = field(default_factory=list)

    def retrieve(
        self, query: str, k: int | None = None, mode: RetrievalMode | None = None
    ) -> list[Evidence]:
        self.calls.append(RetrieveCall(query, k, mode))
        if self.error is not None:
            raise self.error
        found = self.results(query) if callable(self.results) else list(self.results)
        return found[:k] if k is not None else found
