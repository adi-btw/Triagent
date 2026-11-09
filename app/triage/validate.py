"""Deterministic checks on a model-written triage report.

Why this is code and not "ask the model to double-check": the model is the thing being
checked. A JSON schema guarantees the report has the right *shape*; it cannot know
which chunk ids were actually retrieved for this request. This function does, because
the pipeline passes it the allow-list. It is pure (no I/O, no randomness), so the same
report always gets the same verdict, and the eval can count violations by type.

What it proves: every cited id was really shown to the model, and the report is
internally consistent. What it does NOT prove: that the cited passage supports the
claim. That is a semantic judgement, measured by the eval harness (stage 3).
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.schemas import TriageReport, Violation


def validate_report(
    raw: dict[str, Any] | str | None,
    evidence_ids: set[str],
    *,
    require_citations: bool,
) -> tuple[TriageReport | None, list[Violation]]:
    """Parse ``raw`` into a ``TriageReport`` and list every rule it breaks.

    Args:
        raw: the model output (parsed dict, raw JSON text, or None if it did not parse).
        evidence_ids: chunk ids that were in the prompt; the citation allow-list.
        require_citations: True in RAG mode. False for the no-retrieval baseline, which
            has nothing to cite, but is still penalised for citing ids that don't exist.

    Returns:
        ``(report, violations)``. ``report`` is None only on ``schema_error``.
        An empty violation list means the report is acceptable.
    """
    report, error = _parse(raw)
    if report is None:
        return None, [Violation(type="schema_error", detail=error)]

    violations: list[Violation] = []
    violations += _unknown_citations(report, evidence_ids)
    if require_citations:
        violations += _missing_citations(report)
    violations += _inconsistent_abstention(report)
    return report, violations


def _parse(raw: dict[str, Any] | str | None) -> tuple[TriageReport | None, str]:
    if raw is None:
        return None, "model output was empty or not valid JSON"
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            return None, f"not valid JSON: {exc}"
    if not isinstance(raw, dict):
        return None, f"expected a JSON object, got {type(raw).__name__}"
    try:
        return TriageReport.model_validate(raw), ""
    except ValidationError as exc:
        return None, str(exc)


def _cited(report: TriageReport) -> list[tuple[str, str]]:
    """Every (location, chunk_id) pair in the report, e.g. ("likely_causes[0]", "RB-..")."""
    pairs = [("severity_citations", cid) for cid in report.severity_citations]
    for i, cause in enumerate(report.likely_causes):
        pairs += [(f"likely_causes[{i}]", cid) for cid in cause.citations]
    for i, step in enumerate(report.next_steps):
        pairs += [(f"next_steps[{i}]", cid) for cid in step.citations]
    return pairs


def _unknown_citations(report: TriageReport, evidence_ids: set[str]) -> list[Violation]:
    return [
        Violation(type="unknown_citation", detail=f"{where} cites {cid!r}, not in evidence")
        for where, cid in _cited(report)
        if cid not in evidence_ids
    ]


def _missing_citations(report: TriageReport) -> list[Violation]:
    out = [
        Violation(type="missing_citation", detail=f"likely_causes[{i}] has no citations")
        for i, cause in enumerate(report.likely_causes)
        if not cause.citations
    ]
    out += [
        Violation(type="missing_citation", detail=f"next_steps[{i}] has no citations")
        for i, step in enumerate(report.next_steps)
        if not step.citations
    ]
    if report.severity is not None and not report.severity_citations:
        out.append(
            Violation(type="missing_citation", detail="severity is set but not cited")
        )
    return out


def _inconsistent_abstention(report: TriageReport) -> list[Violation]:
    out: list[Violation] = []
    if report.insufficient_evidence:
        return out
    if report.severity is None:
        out.append(
            Violation(
                type="inconsistent_abstention",
                detail="severity is null but insufficient_evidence is false",
            )
        )
    if not report.likely_causes:
        out.append(
            Violation(
                type="inconsistent_abstention",
                detail="insufficient_evidence is false but likely_causes is empty",
            )
        )
    return out
