"""Run the eval set through each triage mode with the same LLM and write a report.

    python -m eval.run_eval --modes no_retrieval rag agent
    python -m eval.run_eval --modes rag --cases case-001,case-005 --no-judge
    python -m eval.run_eval --modes rag agent --limit 5 --delay 6 --repeats 1

Outputs, for run id ``<UTC timestamp>-<short sha>``:

    eval/results/runs/<run_id>/raw.jsonl      one CaseResult per line (gitignored)
    eval/results/runs/<run_id>/summary.json   metadata + every metric
    eval/results/<run_id>.md                  Markdown report (commit this)
    eval/results/latest.md                    copy of the newest report

Why the harness calls ``app.triage.service.run_triage`` and nothing lower: that is the
function the API and CLI call, so the eval measures the product, and real retrieval /
the agent loop are picked up automatically once they are merged.

Ordering: case-major (for each case, every mode), so slow drift in provider latency or
rate limiting hits all modes alike instead of biasing whichever mode ran last.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.llm.base import LLMClient
from app.llm.factory import build_llm
from app.retrieval.base import Retriever
from app.retrieval.factory import build_retriever
from app.schemas import TriageMode, TriageRequest, TriageResponse
from app.triage import service
from eval.cases import DEFAULT_CASES_PATH, EvalCase, load_cases, sha256_dir, sha256_file
from eval.judge import (
    JUDGE_PROMPT_VERSION,
    EvalSettings,
    build_judge_llm,
    judge_model_name,
    judge_response,
)
from eval.metrics import BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED, compute_all
from eval.records import CaseResult
from eval.report import render_report

ALL_MODES: tuple[TriageMode, ...] = ("no_retrieval", "rag", "agent")
RunFn = Callable[..., TriageResponse]


# --------------------------------------------------------------------------- one case


def _tokens(resp: TriageResponse) -> int | None:
    total, seen = 0, False
    for step in resp.trace.steps:
        for key in ("input_tokens", "output_tokens"):
            value = step.detail.get(key)
            if isinstance(value, int):
                total, seen = total + value, True
    return total if seen else None


def _prompt_versions(resp: TriageResponse) -> list[str]:
    found = {
        str(step.detail["prompt_version"])
        for step in resp.trace.steps
        if step.detail.get("prompt_version")
    }
    return sorted(found)


def run_case(
    case: EvalCase,
    mode: TriageMode,
    *,
    retriever: Retriever | None,
    llm: LLMClient,
    settings: Settings,
    run_id: str = "",
    repeat: int = 0,
    run_fn: RunFn | None = None,
) -> CaseResult:
    """Run one (case, mode) unit. Never raises: exceptions become ``status="error"``.

    Ambiguous-case protocol (the asymmetry is deliberate and reported):
      * ``agent``: if the first response is ``needs_clarification``, record that a
        question was asked, resubmit with the case's scripted ``clarification`` and
        score the *final* response. Costs (latency, LLM calls) add up over both calls.
      * ``no_retrieval`` / ``rag``: they cannot ask, so they run on the vague incident
        alone and are scored as-is against labels written for the clarified incident.
    An agent that asks on a non-ambiguous case has no scripted answer; that response
    is scored as-is (status needs_clarification, no report) and counted as over-asking.
    """
    run = run_fn or service.run_triage  # looked up at call time so tests can monkeypatch
    result = CaseResult(
        run_id=run_id,
        case_id=case.id,
        category=case.category,
        mode=mode,
        repeat=repeat,
        expected_severity=case.expected_severity,
        expected_doc_ids=case.expected_doc_ids,
        expected_chunk_ids=case.expected_chunk_ids,
        should_abstain=case.should_abstain,
        status="error",
    )
    responses: list[TriageResponse] = []
    wall: list[float] = []

    def call(clarification: str | None) -> TriageResponse:
        t0 = time.perf_counter()
        try:
            return run(
                TriageRequest(incident=case.incident, mode=mode, clarification=clarification),
                retriever=retriever,
                llm=llm,
                settings=settings,
            )
        finally:
            wall.append((time.perf_counter() - t0) * 1000)

    try:
        resp = call(None)
        responses.append(resp)
        if mode == "agent" and resp.status == "needs_clarification":
            result.asked_clarification = True
            result.clarifying_question = resp.clarifying_question
            if case.clarification:
                result.resubmitted_with_clarification = True
                resp = call(case.clarification)
                responses.append(resp)
        result.response = resp
        result.status = resp.status
    except Exception as exc:  # AgentNotAvailable, rate limits, timeouts, bugs: all counted
        result.status = "error"
        result.error_type = type(exc).__name__
        result.error_message = str(exc)[:500]

    if len(responses) == len(wall) and all("total" in r.trace.timings_ms for r in responses):
        result.latency_ms = sum(r.trace.timings_ms["total"] for r in responses)
        result.latency_source = "trace"
    else:
        result.latency_ms = sum(wall)
        result.latency_source = "wall"
    result.llm_calls = sum(r.trace.llm_calls for r in responses)
    token_counts = [t for t in (_tokens(r) for r in responses) if t is not None]
    result.tokens = sum(token_counts) if token_counts else None
    result.prompt_versions = sorted({v for r in responses for v in _prompt_versions(r)})
    return result


def judge_case(result: CaseResult, judge_llm: LLMClient) -> None:
    """Attach claim verdicts to ``result`` in place (only when there is a report)."""
    if result.response is None or result.response.report is None:
        return
    outcome = judge_response(result.response, judge_llm)
    result.judged = True
    result.claims = outcome.claims
    result.judge_calls = outcome.calls
    result.judge_error = outcome.error


# --------------------------------------------------------------------------- metadata


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True, timeout=10
        )
        return out.stdout.strip()
    except Exception:
        return None


def git_info() -> tuple[str, bool | None]:
    sha = _git("rev-parse", "--short", "HEAD") or "nogit"
    # Untracked files are ignored: the reports this tool writes would otherwise make
    # every second run look dirty.
    status = _git("status", "--porcelain", "--untracked-files=no")
    return sha, (bool(status) if status is not None else None)


def make_run_id(sha: str, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}-{sha}"


# --------------------------------------------------------------------------- CLI


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m eval.run_eval", description=__doc__.split("\n")[0])
    p.add_argument("--modes", nargs="+", choices=ALL_MODES, default=list(ALL_MODES))
    p.add_argument("--cases", default=None, help="comma-separated case ids, e.g. case-001,case-005")
    p.add_argument("--limit", type=int, default=None, help="first N cases after --cases")
    p.add_argument("--judge", action=argparse.BooleanOptionalAction, default=True,
                   help="score claim support with the LLM judge (default on)")
    p.add_argument("--delay", type=float, default=0.0,
                   help="seconds to sleep after each LLM-using unit (rate limits)")
    p.add_argument("--repeats", type=int, default=1, help="run every case x mode N times")
    p.add_argument("--out", type=Path, default=Path("eval/results"))
    p.add_argument("--cases-file", type=Path, default=DEFAULT_CASES_PATH)
    # Hidden: offline smoke tests only. Serves real corpus chunks by keyword overlap.
    p.add_argument("--fake-retriever", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    if args.repeats < 1:
        p.error("--repeats must be >= 1")
    return args


def main(
    argv: list[str] | None = None,
    *,
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    retriever: Retriever | None = None,
    judge_llm: LLMClient | None = None,
    now: datetime | None = None,
) -> int:
    """CLI entry point. Keyword arguments are injection seams for tests.

    Exit codes: 0 run completed (even if some cases errored: they are in the report),
    2 setup error (bad case filter, no LLM). Per-case failures never abort the run.
    """
    args = parse_args(argv)
    settings = settings or get_settings()
    eval_settings = EvalSettings()
    modes: list[TriageMode] = list(dict.fromkeys(args.modes))

    try:
        ids = [c.strip() for c in args.cases.split(",") if c.strip()] if args.cases else None
        cases = load_cases(args.cases_file, ids=ids, limit=args.limit)
        llm = llm or build_llm(settings)
        if args.judge:
            judge_llm = judge_llm or build_judge_llm(settings, eval_settings)
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    retriever_label = "app.retrieval.factory.build_retriever"
    retriever_error: str | None = None
    if any(m != "no_retrieval" for m in modes) and retriever is None:
        if args.fake_retriever:
            from eval.fake_retriever import KeywordOverlapRetriever

            retriever = KeywordOverlapRetriever(settings.corpus_dir, default_k=settings.top_k)
            retriever_label = KeywordOverlapRetriever.label
        else:
            try:
                retriever = build_retriever(settings)
            except Exception as exc:
                # Keep going: rag/agent units will each be recorded as errors, so the
                # report shows the failure instead of an empty table.
                retriever_error = f"{type(exc).__name__}: {exc}"
                print(f"warning: retriever unavailable ({retriever_error})", file=sys.stderr)
    elif retriever is not None:
        retriever_label = getattr(retriever, "label", type(retriever).__name__)

    sha, dirty = git_info()
    run_id = make_run_id(sha, now)
    run_dir = args.out / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    raw_path = run_dir / "raw.jsonl"

    results: list[CaseResult] = []
    total = len(cases) * len(modes) * args.repeats
    done = 0
    with raw_path.open("w", encoding="utf-8", newline="\n") as raw:
        for repeat in range(args.repeats):
            for case in cases:
                for mode in modes:
                    res = run_case(case, mode, retriever=retriever, llm=llm,
                                   settings=settings, run_id=run_id, repeat=repeat)
                    if args.judge and judge_llm is not None:
                        judge_case(res, judge_llm)
                    results.append(res)
                    # Written as we go, so a crash or Ctrl+C keeps what already ran.
                    raw.write(res.model_dump_json() + "\n")
                    raw.flush()
                    done += 1
                    print(f"[{done}/{total}] {case.id} {mode}: {res.status}"
                          + (f" ({res.error_type})" if res.error_type else ""), file=sys.stderr)
                    if args.delay and (res.llm_calls or res.judge_calls):
                        time.sleep(args.delay)

    metadata: dict[str, Any] = {
        "run_id": run_id,
        "timestamp_utc": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "git_sha": sha,
        "git_dirty": dirty,
        "llm_provider": settings.llm_provider,
        "llm_model": llm.model_name,
        "temperature": settings.llm_temperature,
        "prompt_versions": sorted({v for r in results for v in r.prompt_versions}),
        "judge_enabled": bool(args.judge),
        "judge_model": judge_model_name(settings, eval_settings) if args.judge else None,
        "judge_prompt_version": JUDGE_PROMPT_VERSION if args.judge else None,
        "retriever": retriever_label if any(m != "no_retrieval" for m in modes) else None,
        "retriever_build_error": retriever_error,
        "fake_retriever": bool(args.fake_retriever),
        "embedder": f"{settings.embedder} ({settings.embedding_model})",
        "retrieval_mode": settings.retrieval_mode,
        "top_k": settings.top_k,
        "cases_file": args.cases_file.as_posix(),
        "cases_sha256": sha256_file(args.cases_file),
        "corpus_sha256": sha256_dir(settings.corpus_dir) if settings.corpus_dir.exists() else None,
        "n_cases": len(cases),
        "case_ids": [c.id for c in cases],
        "repeats": args.repeats,
        "modes": modes,
        "bootstrap": f"percentile, {BOOTSTRAP_RESAMPLES} resamples over cases, "
        f"seed {BOOTSTRAP_SEED}",
        "llm_calls_total": sum(r.llm_calls for r in results),
        "judge_calls_total": sum(r.judge_calls for r in results),
        "smoke": settings.llm_provider == "fake" or bool(args.fake_retriever),
    }
    summary = {"metadata": metadata, "metrics": compute_all(results, modes)}
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8", newline="\n"
    )
    report_path = args.out / f"{run_id}.md"
    report_path.write_text(render_report(summary), encoding="utf-8", newline="\n")
    shutil.copyfile(report_path, args.out / "latest.md")
    print(f"wrote {raw_path}, {run_dir / 'summary.json'}, {report_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
