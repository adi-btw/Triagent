"""Render ``summary.json`` as a Markdown report.

The report is a pure function of the summary, so it can be re-rendered (e.g. after a
wording fix) without re-running any LLM calls:

    python -c "import json,sys; from eval.report import render_report; \
print(render_report(json.load(open(sys.argv[1]))))" eval/results/runs/<run_id>/summary.json

Wording rule: state what was measured, with counts and intervals, and nothing
stronger. "rag scored 72% (23/32) [56-86]" is a fact; "rag is better" is a claim the
data may not support at this n.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

SMOKE_BANNER = (
    "> **SMOKE TEST: THESE NUMBERS ARE MEANINGLESS.** This run used a fake LLM "
    "(`LLM_PROVIDER=fake`, which pattern-fills reports without reading the incident) "
    "and/or a fake keyword-overlap retriever. It only proves the harness runs end to "
    "end. Do not quote any number below."
)

Metrics = dict[str, Any]


# --------------------------------------------------------------------------- formatting


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def _num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.1f}"


def fmt_rate(r: dict | None, *, ci: bool = False) -> str:
    if r is None:
        return "n/a"
    if r["value"] is None:
        return "n/a (n=0)"
    out = f"{_pct(r['value'])} ({_num(r['k'])}/{_num(r['n'])})"
    if ci and r.get("ci"):
        lo, hi = r["ci"]
        out += f" [{lo * 100:.0f}-{hi * 100:.0f}]"
    return out


def fmt_mean_pct(m: dict | None) -> str:
    if m is None:
        return "n/a"
    if m["mean"] is None:
        return "n/a (n=0)"
    return f"{_pct(m['mean'])} (n={m['n']})"


def fmt_ms(x: float | None) -> str:
    return "n/a" if x is None else f"{x:,.0f} ms"


def fmt_float(x: float | None, digits: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{digits}f}"


def _get(m: Metrics, *path: str) -> Any:
    for key in path:
        if m is None:
            return None
        m = m.get(key)
    return m


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


# --------------------------------------------------------------------------- rows

Row = tuple[str, Callable[[Metrics], str]]

COMPARISON_ROWS: list[Row] = [
    ("Results (cases x repeats)", lambda m: str(m["n_results"])),
    ("Status ok", lambda m: fmt_rate(m["validity"]["status"]["ok"])),
    ("Status invalid_output", lambda m: fmt_rate(m["validity"]["status"]["invalid_output"])),
    ("Status needs_clarification",
     lambda m: fmt_rate(m["validity"]["status"]["needs_clarification"])),
    ("Status error (crashed)", lambda m: fmt_rate(m["validity"]["status"]["error"])),
    ("Citation validity (no unknown ids)", lambda m: fmt_rate(m["citation_validity"])),
    ("Severity exact [95% CI]", lambda m: fmt_rate(m["severity"]["exact"], ci=True)),
    ("Severity within one level", lambda m: fmt_rate(m["severity"]["within_one"])),
    ("Correct abstention (insufficient_evidence cases)",
     lambda m: fmt_rate(m["abstention"]["correct_abstention"])),
    ("False abstention (answerable cases, lower is better)",
     lambda m: fmt_rate(m["abstention"]["false_abstention"])),
    ("Abstention accuracy [95% CI]", lambda m: fmt_rate(m["abstention"]["accuracy"], ci=True)),
    ("Retrieval doc recall@k", lambda m: fmt_mean_pct(_get(m, "retrieval_recall", "doc"))),
    ("Retrieval chunk recall@k", lambda m: fmt_mean_pct(_get(m, "retrieval_recall", "chunk"))),
    ("Cited-doc precision (PROXY vs labels)",
     lambda m: fmt_mean_pct(m["citation_precision_proxy"])),
    ("Claims supported (judge) [95% CI]",
     lambda m: fmt_rate(_get(m, "claim_support", "supported"), ci=True)),
    ("Claims partially supported", lambda m: fmt_rate(_get(m, "claim_support",
                                                           "partially_supported"))),
    ("Claims not supported", lambda m: fmt_rate(_get(m, "claim_support", "not_supported"))),
    ("Claims unjudged (judge gave no verdict)",
     lambda m: "n/a" if m["claim_support"] is None else str(m["claim_support"]["unjudged"])),
    ("Clarification rate (ambiguous, agent only)",
     lambda m: fmt_rate(_get(m, "clarification", "clarification_rate"))),
    ("Over-asking (unambiguous, agent only)",
     lambda m: fmt_rate(_get(m, "clarification", "over_asking"))),
    ("Latency p50", lambda m: fmt_ms(m["latency"]["p50_ms"])),
    ("Latency p95", lambda m: fmt_ms(m["latency"]["p95_ms"])),
    ("Latency mean", lambda m: fmt_ms(m["latency"]["mean_ms"])),
    ("Mean LLM calls per case (excl. judge)",
     lambda m: fmt_float(m["latency"]["mean_llm_calls"])),
    ("Mean tokens per case (in+out, if reported)",
     lambda m: fmt_float(m["latency"]["mean_tokens"], 0)),
]

CATEGORY_ROWS: list[Row] = [
    ("Results", lambda m: str(m["n_results"])),
    ("Status ok", lambda m: fmt_rate(m["validity"]["status"]["ok"])),
    ("Status error", lambda m: fmt_rate(m["validity"]["status"]["error"])),
    ("Severity exact", lambda m: fmt_rate(m["severity"]["exact"])),
    ("Correct abstention", lambda m: fmt_rate(m["abstention"]["correct_abstention"])),
    ("False abstention", lambda m: fmt_rate(m["abstention"]["false_abstention"])),
    ("Doc recall@k", lambda m: fmt_mean_pct(_get(m, "retrieval_recall", "doc"))),
    ("Claims supported", lambda m: fmt_rate(_get(m, "claim_support", "supported"))),
    ("Clarification rate", lambda m: fmt_rate(_get(m, "clarification", "clarification_rate"))),
]


# --------------------------------------------------------------------------- sections


def _metadata(meta: dict) -> list[str]:
    keys = [
        ("run_id", "Run id"),
        ("timestamp_utc", "Timestamp (UTC)"),
        ("git_sha", "Git sha"),
        ("git_dirty", "Uncommitted changes"),
        ("llm_provider", "LLM provider"),
        ("llm_model", "LLM model"),
        ("temperature", "Temperature"),
        ("prompt_versions", "Prompt versions (from traces)"),
        ("judge_enabled", "Judge enabled"),
        ("judge_model", "Judge model"),
        ("judge_prompt_version", "Judge prompt version"),
        ("retriever", "Retriever"),
        ("embedder", "Embedder"),
        ("retrieval_mode", "Retrieval mode"),
        ("top_k", "top_k"),
        ("cases_sha256", "cases.jsonl sha256"),
        ("corpus_sha256", "Corpus sha256"),
        ("n_cases", "Cases"),
        ("repeats", "Repeats"),
        ("modes", "Modes"),
        ("bootstrap", "Bootstrap"),
        ("llm_calls_total", "LLM calls made (generation)"),
        ("judge_calls_total", "LLM calls made (judge)"),
        ("retriever_build_error", "Retriever build error"),
    ]
    lines = []
    for key, label in keys:
        if key not in meta or meta[key] is None:
            continue
        value = meta[key]
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value) or "(none recorded)"
        lines.append(f"- **{label}:** `{value}`")
    return lines


def _confusion(m: Metrics) -> list[str]:
    cm = m["confusion"]
    if not any(any(row) for row in cm["matrix"]):
        return ["_No labelled cases with a parsed report._"]
    header = ["expected \\ predicted", *cm["cols"]]
    rows = [[name, *map(str, row)] for name, row in zip(cm["rows"], cm["matrix"], strict=True)]
    return _table(header, rows)


def _failure_detail(f: dict) -> str:
    if f["status"] == "error":
        msg = (f.get("error_message") or "").replace("|", "\\|").replace("\n", " ")
        return f"`{f['error_type']}`: {msg[:160]}"
    parts = []
    if f["violations"]:
        parts.append("violations: " + ", ".join(f["violations"]))
    if f["status"] == "needs_clarification":
        parts.append("ended asking a question (no report to score)")
    if f.get("judge_error"):
        parts.append("judge: " + f["judge_error"][:120].replace("|", "\\|"))
    return "; ".join(parts) or "-"


def render_report(summary: dict) -> str:
    meta = summary["metadata"]
    modes: list[str] = meta["modes"]
    by_mode = summary["metrics"]["by_mode"]
    n_cases = meta["n_cases"]
    pp_per_case = 100 / n_cases if n_cases else 0

    out: list[str] = [f"# Evaluation report: {meta['run_id']}", ""]
    if meta.get("smoke"):
        out += [SMOKE_BANNER, ""]
    out += ["## Run metadata", "", *_metadata(meta), ""]

    out += [
        "## Comparison",
        "",
        f"Same LLM in every mode; only the evidence and control flow differ. n = {n_cases} "
        f"cases (one case is about {pp_per_case:.0f} percentage points). Brackets are 95% "
        "bootstrap CIs (2000 resamples over cases). **With this n, differences under "
        "~10 pp are not meaningful, and overlapping intervals mean the data do not "
        "separate the modes.**",
        "",
    ]
    out += _table(
        ["Metric", *modes],
        [[label, *(fn(by_mode[m]) for m in modes)] for label, fn in COMPARISON_ROWS],
    )
    out.append("")

    out += ["## By category", ""]
    for cat, per_mode in summary["metrics"]["by_category"].items():
        out += [f"### {cat}", ""]
        out += _table(
            ["Metric", *modes],
            [[label, *(fn(per_mode[m]) for m in modes)] for label, fn in CATEGORY_ROWS],
        )
        out.append("")
    out += [
        "Ambiguous cases are asymmetric by design: `agent` may ask a clarifying question "
        "and is then re-run with the scripted answer; `no_retrieval` and `rag` cannot ask "
        "and are scored on the vague incident alone, against labels that describe the "
        "incident *after* clarification. Their low scores there are expected.",
        "",
    ]

    out += ["## Severity confusion matrices", ""]
    for m in modes:
        out += [f"### {m}", "", *_confusion(by_mode[m]), ""]

    out += ["## Failed and erroring cases", ""]
    failures = summary["metrics"]["failures"]
    if not failures:
        out += ["_None: every result was `ok` and every judge call succeeded._", ""]
    for m in modes:
        rows = [f for f in failures if f["mode"] == m]
        if not rows:
            continue
        out += [f"### {m} ({len(rows)})", ""]
        out += _table(
            ["case", "repeat", "status", "detail"],
            [[f["case_id"], str(f["repeat"]), f["status"], _failure_detail(f)] for f in rows],
        )
        out.append("")

    out += [
        "## How to read this",
        "",
        "- **Every rate shows k/n.** Quality rows (severity, abstention, citations, claims) "
        "only count results with a parsed report; check the status rows to see how many "
        "were dropped from them. Errors are never silently removed.",
        "- **Severity exact** compares to a single labeller's reading of POL-SEV-001; "
        "*within one level* shows whether misses are near-misses.",
        "- **Citation validity** only proves cited ids were retrieved. **Claims "
        "supported** is an LLM judge's opinion that the cited passage backs the claim; "
        "it has its own error rate and should be calibrated against a human spot-check. "
        "In `no_retrieval` every claim is not supported by construction (no passages).",
        "- **Cited-doc precision** is a cheap label-based proxy: it penalises citing a "
        "sensible doc the labeller did not list.",
        "- **Recall@k** measures retrieval, not the answer: a mode can retrieve the right "
        "doc and still misread it.",
        "- **Latency** excludes judge calls; p95 over ~30 samples is about the "
        "second-slowest case.",
        "- The corpus and the eval cases were written by the same author, so retrieval "
        "numbers are likely optimistic compared with real tickets.",
        f"- n = {n_cases}: treat differences under ~10 pp as noise and read the CIs.",
        "",
    ]
    return "\n".join(out)
