"""Metrics over ``CaseResult`` records. Pure functions: records in, plain dicts out.

Pure on purpose: every number in the report can be recomputed from ``raw.jsonl`` (and
unit-tested on hand-built records) without an LLM, a retriever, or the network.

Conventions used by every function here:

* A *rate* is ``{"k": hits, "n": denominator, "value": k/n or None, "ci": [lo, hi] or
  None}``. ``value`` is None when ``n == 0``: "no cases to measure" must never be shown
  as 0% or 100%. Always read ``value`` next to ``n``.
* *Quality* metrics (severity, abstention, citations, claim support) are computed over
  results that have a parsed report, and say so in ``n``. *Validity* metrics count every
  result, including errors. Read them together: a mode that errors on half the cases
  but is perfect on the rest has a high accuracy over a small ``n`` and a bad validity row.
* Units are (case, repeat) pairs. With ``--repeats > 1`` the same case appears several
  times; the bootstrap resamples *cases* (all repeats of a case move together), because
  repeats of one case are not independent evidence.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np

from app.schemas import TriageReport
from eval.records import CaseResult

SEVERITY_LEVELS = ["SEV1", "SEV2", "SEV3", "SEV4"]
STATUSES = ["ok", "invalid_output", "needs_clarification", "error"]
VIOLATION_TYPES = [
    "schema_error",
    "unknown_citation",
    "missing_citation",
    "inconsistent_abstention",
]
VERDICTS = ["supported", "partially_supported", "not_supported"]
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261109

Rate = dict[str, Any]
Unit = tuple[str, float, float]  # (case_id, numerator, denominator)


# --------------------------------------------------------------------------- helpers


def rate(k: float, n: float, ci: tuple[float, float] | None = None) -> Rate:
    return {
        "k": k,
        "n": n,
        "value": (k / n) if n else None,
        "ci": list(ci) if ci is not None else None,
    }


def doc_id(chunk_id: str) -> str:
    """``"RB-DB-001#s3"`` -> ``"RB-DB-001"`` (the chunk ID rule in app/schemas.py)."""
    return chunk_id.split("#", 1)[0]


def report_of(result: CaseResult) -> TriageReport | None:
    return result.response.report if result.response is not None else None


def with_report(results: Iterable[CaseResult]) -> list[CaseResult]:
    return [r for r in results if report_of(r) is not None]


def cited_ids(report: TriageReport) -> list[str]:
    ids = list(report.severity_citations)
    for cause in report.likely_causes:
        ids += cause.citations
    for step in report.next_steps:
        ids += step.citations
    return ids


def _sev_value(sev: Any) -> str | None:
    if sev is None:
        return None
    return getattr(sev, "value", sev)


# --------------------------------------------------------------------------- bootstrap


def cluster_units(units: Iterable[Unit]) -> list[tuple[float, float]]:
    """Sum (numerator, denominator) per case id, so a case is one resampling unit."""
    sums: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for case_id, num, den in units:
        sums[case_id][0] += num
        sums[case_id][1] += den
    return [(num, den) for num, den in sums.values()]


def bootstrap_ci(
    clusters: Sequence[tuple[float, float]],
    *,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    level: float = 0.95,
) -> tuple[float, float] | None:
    """Percentile bootstrap CI for a ratio sum(num) / sum(den) over clusters.

    Why a ratio of sums: it covers both "accuracy over cases" (each cluster is (0|1, 1))
    and "fraction of claims supported" (each cluster is one report: (supported, claims)),
    where reports with more claims should weigh more but claims inside one report are
    correlated, so the *report/case* is what gets resampled.

    Why bootstrap: with n around 30 the normal approximation is poor near 0% or 100%;
    resampling the observed cases makes no distributional assumption. It cannot fix a
    small n: the interval is wide because the data are few, and that is the message.

    Deterministic for a given ``seed``. Returns None if there is nothing to resample.
    """
    if not clusters:
        return None
    num = np.array([c[0] for c in clusters], dtype=float)
    den = np.array([c[1] for c in clusters], dtype=float)
    if den.sum() == 0:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(clusters), size=(n_resamples, len(clusters)))
    nums, dens = num[idx].sum(axis=1), den[idx].sum(axis=1)
    ratios = nums[dens > 0] / dens[dens > 0]
    tail = (1 - level) / 2 * 100
    lo, hi = np.percentile(ratios, [tail, 100 - tail])
    return float(lo), float(hi)


def _rate_with_ci(units: list[Unit], seed: int) -> Rate:
    k = sum(u[1] for u in units)
    n = sum(u[2] for u in units)
    return rate(k, n, bootstrap_ci(cluster_units(units), seed=seed) if n else None)


# --------------------------------------------------------------------------- severity


def severity_units(results: Iterable[CaseResult]) -> tuple[list[Unit], list[Unit]]:
    """(exact, within_one) units over results with a label and a parsed report.

    A null predicted severity counts as wrong on both: the case was labelled, so the
    facts were there.
    """
    exact: list[Unit] = []
    within: list[Unit] = []
    for r in with_report(results):
        if r.expected_severity is None:
            continue
        expected = _sev_value(r.expected_severity)
        predicted = _sev_value(report_of(r).severity)  # type: ignore[union-attr]
        hit = predicted == expected
        near = predicted is not None and (
            abs(SEVERITY_LEVELS.index(predicted) - SEVERITY_LEVELS.index(expected)) <= 1
        )
        exact.append((r.case_id, float(hit), 1.0))
        within.append((r.case_id, float(near), 1.0))
    return exact, within


def severity_accuracy(results: Sequence[CaseResult], *, seed: int = BOOTSTRAP_SEED) -> dict:
    exact, within = severity_units(results)
    return {"exact": _rate_with_ci(exact, seed), "within_one": rate(
        sum(u[1] for u in within), len(within))}


def confusion_matrix(results: Iterable[CaseResult]) -> dict:
    """Rows = expected SEV1-4, columns = predicted SEV1-4 or "null"."""
    cols = [*SEVERITY_LEVELS, "null"]
    matrix = [[0] * len(cols) for _ in SEVERITY_LEVELS]
    for r in with_report(results):
        if r.expected_severity is None:
            continue
        predicted = _sev_value(report_of(r).severity) or "null"  # type: ignore[union-attr]
        matrix[SEVERITY_LEVELS.index(_sev_value(r.expected_severity))][cols.index(predicted)] += 1
    return {"rows": SEVERITY_LEVELS, "cols": cols, "matrix": matrix}


# --------------------------------------------------------------------------- validity


def output_validity(results: Sequence[CaseResult]) -> dict:
    """Share of results per final status, plus violation counts by type.

    ``violations`` counts individual violations; ``results_with`` counts results that
    had at least one of that type (one bad report can carry five unknown citations).
    """
    n = len(results)
    statuses = Counter(r.status for r in results)
    violations: Counter[str] = Counter()
    results_with: Counter[str] = Counter()
    for r in results:
        if r.response is None:
            continue
        types = [v.type for v in r.response.trace.violations]
        violations.update(types)
        results_with.update(set(types))
    return {
        "n": n,
        "status": {s: rate(statuses.get(s, 0), n) for s in STATUSES},
        "violations": {t: violations.get(t, 0) for t in VIOLATION_TYPES},
        "results_with": {t: results_with.get(t, 0) for t in VIOLATION_TYPES},
    }


def citation_validity(results: Sequence[CaseResult]) -> Rate:
    """Share of parsed reports with zero ``unknown_citation`` violations.

    Measures: the model cited only ids it was shown. Does NOT measure that the cited
    passage supports the claim (that is claim support) or that it is the right doc.
    """
    reports = with_report(results)
    clean = sum(
        1
        for r in reports
        if not any(v.type == "unknown_citation" for v in r.response.trace.violations)  # type: ignore[union-attr]
    )
    return rate(clean, len(reports))


# --------------------------------------------------------------------------- retrieval


def _mean(values: list[float]) -> dict:
    return {"mean": (sum(values) / len(values)) if values else None, "n": len(values)}


def retrieval_recall(results: Sequence[CaseResult]) -> dict | None:
    """Mean per-case recall of expected docs / chunks in ``trace.retrieved``.

    Doc recall: |expected_doc_ids ∩ docs of retrieved chunks| / |expected_doc_ids|.
    Pinned context (``method == "pinned"``) is excluded: it is always present, so counting
    it would credit the retriever for chunks it never found.
    Chunk recall: same with ``expected_chunk_ids``. Cases with no expected ids (most
    insufficient_evidence cases) are skipped: recall of an empty set is undefined.
    Returns None when no result retrieved anything and none was expected to
    (the no_retrieval baseline), so the report shows "n/a", not 0%.
    """
    doc_recalls: list[float] = []
    chunk_recalls: list[float] = []
    any_retrieval = False
    for r in results:
        if r.response is None:
            continue
        retrieved = [
            ref.chunk_id for ref in r.response.trace.retrieved if ref.method != "pinned"
        ]
        if r.response.trace.mode != "no_retrieval":
            any_retrieval = True
        docs = {doc_id(c) for c in retrieved}
        if r.expected_doc_ids:
            expected = set(r.expected_doc_ids)
            doc_recalls.append(len(expected & docs) / len(expected))
        if r.expected_chunk_ids:
            expected = set(r.expected_chunk_ids)
            chunk_recalls.append(len(expected & set(retrieved)) / len(expected))
    if not any_retrieval:
        return None
    return {"doc": _mean(doc_recalls), "chunk": _mean(chunk_recalls)}


def citation_precision(results: Sequence[CaseResult]) -> dict:
    """PROXY: mean per-report share of cited doc ids that are in expected_doc_ids.

    Cheap and label-based, so it penalises citing a reasonable doc the labeller did not
    list, and rewards citing the expected doc for the wrong claim. It is a sanity check
    on "did it cite the right documents at all", not a measure of grounding.
    Skips reports with no citations (precision undefined) and cases with no expected docs.
    """
    values: list[float] = []
    for r in with_report(results):
        cited = {doc_id(c) for c in cited_ids(report_of(r))}  # type: ignore[arg-type]
        if not cited or not r.expected_doc_ids:
            continue
        values.append(len(cited & set(r.expected_doc_ids)) / len(cited))
    return _mean(values)


# --------------------------------------------------------------------------- judge


def claim_support(results: Sequence[CaseResult], *, seed: int = BOOTSTRAP_SEED) -> dict | None:
    """Verdict shares over all judged claims (each cause and each next step).

    Claims without citations are ``not_supported`` by rule (no LLM call). Claims the
    judge returned nothing for are ``unjudged`` and excluded from the denominator, but
    counted. Returns None when the judge did not run for any result in ``results``.
    The CI is on the ``supported`` share, resampling reports (claims within a report
    are correlated).
    """
    judged = [r for r in results if r.judged]
    if not judged:
        return None
    counts: Counter[str] = Counter()
    unjudged = 0
    units: list[Unit] = []
    for r in judged:
        scored = [c for c in r.claims if c.verdict is not None]
        unjudged += len(r.claims) - len(scored)
        counts.update(c.verdict for c in scored)  # type: ignore[misc]
        if scored:
            supported = sum(1 for c in scored if c.verdict == "supported")
            units.append((r.case_id, float(supported), float(len(scored))))
    total = sum(counts.values())
    out = {v: rate(counts.get(v, 0), total) for v in VERDICTS}
    out["supported"] = _rate_with_ci(units, seed)
    return {
        **out,
        "claims": total,
        "unjudged": unjudged,
        "reports": len(judged),
        "judge_errors": sum(1 for r in judged if r.judge_error),
    }


# --------------------------------------------------------------------------- abstention


def abstention(results: Sequence[CaseResult], *, seed: int = BOOTSTRAP_SEED) -> dict:
    """Does the model say "not enough evidence" exactly when it should?

    * correct_abstention: insufficient_evidence=true on ``should_abstain`` cases.
    * false_abstention: insufficient_evidence=true on *answerable* cases.
    * accuracy: insufficient_evidence == should_abstain over answerable +
      insufficient_evidence cases. Ambiguous cases are left out: in modes that cannot
      ask, abstaining on "the site feels slow" is defensible, so it would be unfair to
      score it either way.
    """
    reports = with_report(results)
    should = [r for r in reports if r.should_abstain]
    answerable = [r for r in reports if r.category == "answerable"]

    def abstained(r: CaseResult) -> bool:
        return report_of(r).insufficient_evidence  # type: ignore[union-attr]

    units = [
        (r.case_id, float(abstained(r) == r.should_abstain), 1.0)
        for r in reports
        if r.category in ("answerable", "insufficient_evidence")
    ]
    return {
        "correct_abstention": rate(sum(abstained(r) for r in should), len(should)),
        "false_abstention": rate(sum(abstained(r) for r in answerable), len(answerable)),
        "accuracy": _rate_with_ci(units, seed),
    }


def clarification(results: Sequence[CaseResult]) -> dict:
    """Clarification rate on ambiguous cases and over-asking on the rest.

    Counts results where the mode got as far as answering (an error before the first
    response says nothing about whether it would have asked).
    """
    eligible = [r for r in results if r.asked_clarification or r.status != "error"]
    ambiguous = [r for r in eligible if r.category == "ambiguous"]
    other = [r for r in eligible if r.category != "ambiguous"]
    return {
        "clarification_rate": rate(sum(r.asked_clarification for r in ambiguous), len(ambiguous)),
        "over_asking": rate(sum(r.asked_clarification for r in other), len(other)),
    }


# --------------------------------------------------------------------------- latency


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile (numpy's default), None for no values."""
    return float(np.percentile(values, q)) if values else None


def latency(results: Sequence[CaseResult]) -> dict:
    """p50 / p95 / mean of per-unit latency, mean LLM calls and tokens; errors excluded.

    Latency is the sum of ``trace.timings_ms.total`` over every call made for the unit
    (two for a resubmitted ambiguous case), or wall time when a trace had no total.
    Judge calls are NOT included: the judge is eval cost, not product latency.
    With ~30 samples, p95 is roughly the second-slowest case: treat it as indicative.
    """
    done = [r for r in results if r.status != "error"]
    values = [r.latency_ms for r in done]
    tokens = [r.tokens for r in done if r.tokens is not None]
    return {
        "n": len(done),
        "p50_ms": percentile(values, 50),
        "p95_ms": percentile(values, 95),
        "mean_ms": (sum(values) / len(values)) if values else None,
        "mean_llm_calls": (sum(r.llm_calls for r in done) / len(done)) if done else None,
        "mean_tokens": (sum(tokens) / len(tokens)) if tokens else None,
        "wall_fallbacks": sum(1 for r in done if r.latency_source == "wall"),
    }


# --------------------------------------------------------------------------- roll-up


def mode_metrics(results: Sequence[CaseResult], *, seed: int = BOOTSTRAP_SEED) -> dict:
    """Every metric for one mode (or one mode x category slice)."""
    is_agent = bool(results) and all(r.mode == "agent" for r in results)
    return {
        "n_results": len(results),
        "n_cases": len({r.case_id for r in results}),
        "validity": output_validity(results),
        "citation_validity": citation_validity(results),
        "severity": severity_accuracy(results, seed=seed),
        "confusion": confusion_matrix(results),
        "retrieval_recall": retrieval_recall(results),
        "citation_precision_proxy": citation_precision(results),
        "claim_support": claim_support(results, seed=seed),
        "abstention": abstention(results, seed=seed),
        # Only the agent can ask; for other modes the rate is 0 by construction.
        "clarification": clarification(results) if is_agent else None,
        "latency": latency(results),
        "llm_calls_total": sum(r.llm_calls for r in results),
        "judge_calls_total": sum(r.judge_calls for r in results),
    }


def failures(results: Iterable[CaseResult]) -> list[dict]:
    """Every result that was not a clean ``ok``, or whose judging failed."""
    out = []
    for r in results:
        if r.status == "ok" and not r.judge_error:
            continue
        out.append(
            {
                "case_id": r.case_id,
                "mode": r.mode,
                "repeat": r.repeat,
                "status": r.status,
                "error_type": r.error_type,
                "error_message": r.error_message,
                "violations": sorted(
                    {v.type for v in r.response.trace.violations} if r.response else set()
                ),
                "judge_error": r.judge_error,
            }
        )
    return out


def compute_all(
    results: Sequence[CaseResult], modes: Sequence[str], *, seed: int = BOOTSTRAP_SEED
) -> dict:
    by_mode = {m: mode_metrics([r for r in results if r.mode == m], seed=seed) for m in modes}
    categories = sorted({r.category for r in results})
    by_category = {
        cat: {
            m: mode_metrics([r for r in results if r.mode == m and r.category == cat], seed=seed)
            for m in modes
        }
        for cat in categories
    }
    return {"by_mode": by_mode, "by_category": by_category, "failures": failures(results)}
