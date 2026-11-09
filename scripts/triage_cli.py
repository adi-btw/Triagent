"""Triage an incident file from the terminal.

    python -m scripts.triage_cli data/demo_incident.txt --mode rag
    python -m scripts.triage_cli data/demo_incident.txt --mode no_retrieval --json
    LLM_PROVIDER=fake python -m scripts.triage_cli data/demo_incident.txt   # offline

Uses the same ``run_triage`` as the API, so what you see here is what the UI gets.
Exit code: 0 ok, 1 invalid_output, 2 setup error (no index / no key).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.llm.factory import build_llm
from app.retrieval.base import Retriever
from app.retrieval.factory import build_retriever
from app.schemas import TriageRequest, TriageResponse
from app.triage.service import run_triage


def render(resp: TriageResponse) -> str:
    """Human-readable view: report, citations, violations, timings."""
    lines = [f"status: {resp.status}   model: {resp.trace.model}   mode: {resp.trace.mode}"]
    report = resp.report
    if report is not None:
        sev_cites = ", ".join(report.severity_citations) or "-"
        lines += [
            "",
            f"Summary:  {report.summary}",
            f"Severity: {report.severity.value if report.severity else 'unknown'}"
            f"   [{sev_cites}]",
            f"Insufficient evidence: {report.insufficient_evidence}",
            "",
            "Likely causes:",
        ]
        lines += [
            f"  - ({c.confidence}) {c.description}  [{', '.join(c.citations) or '-'}]"
            for c in report.likely_causes
        ] or ["  (none)"]
        lines += ["", "Next steps:"]
        lines += [
            f"  {i}. {s.action}  [{', '.join(s.citations) or '-'}]"
            for i, s in enumerate(report.next_steps, 1)
        ] or ["  (none)"]
        if report.missing_information:
            lines += ["", "Missing information:"]
            lines += [f"  - {m}" for m in report.missing_information]
    if resp.evidence:
        lines += ["", "Retrieved evidence:"]
        lines += [f"  {e.score:.3f}  {e.chunk_id}  {e.title} / {e.heading}" for e in resp.evidence]
    if resp.trace.violations:
        lines += ["", "VIOLATIONS:"]
        lines += [f"  ! {v.type}: {v.detail}" for v in resp.trace.violations]
    timings = "  ".join(f"{k}={v:.1f}ms" for k, v in resp.trace.timings_ms.items())
    lines += ["", f"Timings: {timings}"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("incident_file", type=Path)
    parser.add_argument("--mode", choices=["rag", "no_retrieval", "agent"], default="rag")
    parser.add_argument("--clarification", default=None)
    parser.add_argument("--json", action="store_true", help="print the full TriageResponse")
    args = parser.parse_args(argv)

    settings = get_settings()
    request = TriageRequest(
        incident=args.incident_file.read_text(encoding="utf-8"),
        mode=args.mode,
        clarification=args.clarification,
    )
    try:
        llm = build_llm(settings)
        retriever: Retriever | None = (
            None if args.mode == "no_retrieval" else build_retriever(settings)
        )
        resp = run_triage(request, retriever=retriever, llm=llm, settings=settings)
    except Exception as exc:  # setup problems: show one line, not a traceback
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(resp.model_dump_json(indent=2) if args.json else render(resp))
    return 0 if resp.status != "invalid_output" else 1


if __name__ == "__main__":
    sys.exit(main())
