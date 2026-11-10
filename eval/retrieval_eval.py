"""Retrieval-only evaluation: no LLM, so it is free, fast and deterministic.

    python -m scripts.ingest                       # build the index first
    python -m eval.retrieval_eval                  # vector, keyword, hybrid at k=5
    python -m eval.retrieval_eval --modes vector hybrid --k 8
    python -m eval.retrieval_eval --modes hybrid hybrid+rerank

Every first-stage mode also has a ``<mode>+rerank`` variant: the same search widened to
``rerank_candidates`` chunks, then reordered by the cross-encoder (app.retrieval.rerank).

Why separate from ``run_eval``: when the end-to-end score is bad you need to know
whether the right passage was never retrieved (a retrieval problem) or was retrieved
and misread (a generation problem). This tool answers the first question in seconds,
across every retrieval mode, without spending a single LLM call.

Metrics per mode (each a mean over cases):

* **doc recall@k**: share of ``expected_doc_ids`` with at least one chunk in the top k.
* **chunk recall@k**: share of ``expected_chunk_ids`` in the top k.
* **primary hit@k**: is the *primary* doc (first non-policy expected doc, usually the
  runbook that explains the cause) in the top k? POL-SEV-001 is excluded because it is
  expected for nearly every case and easy to retrieve, so it inflates doc recall.
* **MRR** (chunk level): 1 / rank of the first retrieved chunk that is in
  ``expected_chunk_ids`` (0 if none in the top k). Rewards putting key evidence first.

Which cases: every case with a non-policy expected doc. ``insufficient_evidence`` cases
whose expected docs are ``[]`` or only POL-SEV-001 have nothing to recall; they are
listed separately with what each mode returned for them (a retriever always returns k
chunks, which is why the *generator* must be able to abstain). Ambiguous cases are
scored twice: on the vague incident alone and on incident + clarification (the same
text the triage service builds), as separate rows.

Outputs ``eval/results/retrieval-latest.md`` and ``eval/results/runs/<run_id>-retrieval/
summary.json``. Not measured: whether the retrieved text is *useful* to the model, and
anything about generation. The labels were written by the corpus author, so absolute
numbers are optimistic; the comparison between modes on the same cases is the point.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import RetrievalMode, Settings, get_settings
from app.retrieval.base import Retriever
from app.retrieval.factory import build_retriever
from app.retrieval.rerank import FastEmbedReranker, Reranker, RerankingRetriever
from app.schemas import TriageRequest
from app.triage.service import incident_text
from eval.cases import DEFAULT_CASES_PATH, EvalCase, load_cases, sha256_dir, sha256_file
from eval.metrics import BOOTSTRAP_SEED, bootstrap_ci, doc_id
from eval.run_eval import git_info, make_run_id

BASE_MODES: tuple[RetrievalMode, ...] = ("vector", "keyword", "hybrid")
RERANK_SUFFIX = "+rerank"
ALL_RETRIEVAL_MODES: tuple[str, ...] = BASE_MODES + tuple(m + RERANK_SUFFIX for m in BASE_MODES)
METRICS = ("doc_recall", "chunk_recall", "primary_hit", "mrr")
METRIC_LABELS = {
    "doc_recall": "Doc recall@k",
    "chunk_recall": "Chunk recall@k",
    "primary_hit": "Primary-doc hit@k",
    "mrr": "MRR (chunk level)",
}
SLICES = ("answerable", "insufficient_evidence", "ambiguous (vague)", "ambiguous (+clarification)")


# --------------------------------------------------------------------------- pure parts


class VariantRetriever:
    """Routes ``mode="hybrid+rerank"`` to the reranking retriever with ``mode="hybrid"``,
    and plain modes to the first-stage retriever, so ``evaluate`` treats every variant as
    just another mode name."""

    def __init__(self, base: Retriever, reranking: Retriever | None) -> None:
        self.base = base
        self.reranking = reranking
        self.label = getattr(reranking or base, "label", type(base).__name__)

    def retrieve(self, query: str, k: int | None = None, mode: str | None = None):
        if mode and mode.endswith(RERANK_SUFFIX):
            if self.reranking is None:
                raise ValueError(f"{mode!r} requested but no reranker was built")
            return self.reranking.retrieve(query, k=k, mode=mode.removesuffix(RERANK_SUFFIX))
        return self.base.retrieve(query, k=k, mode=mode)


def primary_doc(case: EvalCase) -> str | None:
    """First expected doc that is not a policy, or None (nothing case-specific to find)."""
    return next((d for d in case.expected_doc_ids if not d.startswith("POL-")), None)


def is_scored(case: EvalCase) -> bool:
    return primary_doc(case) is not None


def score_ranking(
    retrieved: Sequence[str], expected_docs: Sequence[str], expected_chunks: Sequence[str],
    primary: str | None,
) -> dict[str, Any]:
    """All four metrics for one ranked list of chunk ids (best first, already top-k)."""
    docs = [doc_id(c) for c in retrieved]
    exp_docs, exp_chunks = set(expected_docs), set(expected_chunks)
    rr = next((1 / i for i, c in enumerate(retrieved, 1) if c in exp_chunks), 0.0)
    primary_rank = next((i for i, d in enumerate(docs, 1) if d == primary), None)
    return {
        "doc_recall": len(exp_docs & set(docs)) / len(exp_docs) if exp_docs else None,
        "chunk_recall": len(exp_chunks & set(retrieved)) / len(exp_chunks)
        if exp_chunks else None,
        "primary_hit": None if primary is None else float(primary_rank is not None),
        "primary_rank": primary_rank,
        "mrr": rr if exp_chunks else None,
    }


def queries_for(case: EvalCase) -> list[tuple[str, str]]:
    """(slice, query text) pairs: ambiguous cases yield both the vague and clarified text."""
    if case.category == "ambiguous":
        clarified = incident_text(
            TriageRequest(incident=case.incident, clarification=case.clarification)
        )
        return [("ambiguous (vague)", case.incident), ("ambiguous (+clarification)", clarified)]
    return [(case.category, case.incident)]


def aggregate(rows: list[dict], *, seed: int = BOOTSTRAP_SEED) -> dict[str, Any]:
    """Mean of each metric over rows where it is defined, with n and a bootstrap CI."""
    out: dict[str, Any] = {"n": len(rows), "errors": sum(1 for r in rows if r.get("error"))}
    for metric in METRICS:
        values = [r[metric] for r in rows if r.get(metric) is not None]
        ci = bootstrap_ci([(v, 1.0) for v in values], seed=seed) if values else None
        out[metric] = {
            "mean": sum(values) / len(values) if values else None,
            "n": len(values),
            "ci": list(ci) if ci else None,
        }
    return out


def evaluate(
    cases: Sequence[EvalCase], retriever: Retriever, modes: Sequence[str], k: int
) -> dict[str, Any]:
    """Run every (case query, mode) and return per-row results plus aggregates."""
    rows: list[dict] = []
    skipped: list[dict] = []
    for case in cases:
        if not is_scored(case):
            entry: dict[str, Any] = {"case_id": case.id, "expected_doc_ids": case.expected_doc_ids,
                                     "top": {}}
            for mode in modes:
                try:
                    hits = retriever.retrieve(case.incident, k=k, mode=mode)
                    entry["top"][mode] = [h.chunk_id for h in hits]
                except Exception as exc:
                    entry["top"][mode] = f"error: {type(exc).__name__}: {exc}"
            skipped.append(entry)
            continue
        for slice_name, query in queries_for(case):
            for mode in modes:
                row: dict[str, Any] = {"case_id": case.id, "slice": slice_name, "mode": mode}
                try:
                    hits = retriever.retrieve(query, k=k, mode=mode)
                    retrieved = [h.chunk_id for h in hits][:k]
                    row["retrieved"] = retrieved
                    row.update(score_ranking(retrieved, case.expected_doc_ids,
                                             case.expected_chunk_ids, primary_doc(case)))
                except Exception as exc:  # recorded, counted, never dropped
                    row["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
                    row.update({m: 0.0 for m in METRICS})  # a crash retrieves nothing
                    row["primary_rank"] = None
                rows.append(row)

    def pick(mode: str, slices: Sequence[str]) -> list[dict]:
        return [r for r in rows if r["mode"] == mode and r["slice"] in slices]

    overall_slices = ("answerable", "insufficient_evidence", "ambiguous (+clarification)")
    return {
        "rows": rows,
        "skipped": skipped,
        "overall": {m: aggregate(pick(m, overall_slices)) for m in modes},
        "by_slice": {s: {m: aggregate(pick(m, (s,))) for m in modes} for s in SLICES},
    }


# --------------------------------------------------------------------------- report


def _fmt(cell: dict, *, ci: bool = False) -> str:
    if cell["mean"] is None:
        return "n/a (n=0)"
    out = f"{cell['mean'] * 100:.0f}% (n={cell['n']})"
    if ci and cell.get("ci"):
        out += f" [{cell['ci'][0] * 100:.0f}-{cell['ci'][1] * 100:.0f}]"
    return out


def render(summary: dict) -> str:
    meta, res = summary["metadata"], summary["results"]
    modes = meta["modes"]
    head = "| Metric | " + " | ".join(modes) + " |\n|" + "---|" * (len(modes) + 1)
    lines = [f"# Retrieval evaluation: {meta['run_id']}", ""]
    if meta.get("injected_retriever"):
        lines += ["> **TEST RUN: a retriever object was injected (not built from settings); "
                  "numbers are meaningless.**", ""]
    lines += [f"- **{k}:** `{v}`" for k, v in meta.items() if k not in ("primary_docs",)]
    lines += [
        "",
        "## Overall",
        "",
        "Answerable + insufficient_evidence cases with a non-policy expected doc + ambiguous "
        "cases *with* clarification. Brackets: 95% bootstrap CI over cases. "
        f"k = {meta['k']}. Same cases and labels for every mode, so differences are paired; "
        "still, with ~25 cases a gap under ~10 pp is not meaningful.",
        "",
        head,
    ]
    for metric in METRICS:
        cells = [_fmt(res["overall"][m][metric], ci=True) for m in modes]
        lines.append(f"| {METRIC_LABELS[metric]} | " + " | ".join(cells) + " |")
    errors = [res["overall"][m]["errors"] for m in modes]
    lines.append("| Retriever errors (scored as 0) | " + " | ".join(map(str, errors)) + " |")

    for metric in METRICS:
        lines += ["", f"## {METRIC_LABELS[metric]} by slice", "",
                  "| Slice | " + " | ".join(modes) + " |", "|" + "---|" * (len(modes) + 1)]
        for s in SLICES:
            cells = [_fmt(res["by_slice"][s][m][metric]) for m in modes]
            lines.append(f"| {s} | " + " | ".join(cells) + " |")

    lines += ["", "## Primary doc rank per case", "",
              "Rank of the first chunk from the primary doc (blank = not in top k).", "",
              "| Case | Slice | Primary doc | " + " | ".join(modes) + " |",
              "|" + "---|" * (len(modes) + 3)]
    keyed: dict[tuple[str, str], dict[str, dict]] = {}
    for row in res["rows"]:
        keyed.setdefault((row["case_id"], row["slice"]), {})[row["mode"]] = row
    primaries = meta.get("primary_docs", {})
    for (case_id, slice_name), per_mode in keyed.items():
        cells = []
        for m in modes:
            row = per_mode.get(m, {})
            cells.append("error" if row.get("error") else str(row.get("primary_rank") or ""))
        lines.append(f"| {case_id} | {slice_name} | {primaries.get(case_id, '')} | "
                     + " | ".join(cells) + " |")

    lines += ["", "## Not scored (nothing case-specific to retrieve)", "",
              "insufficient_evidence cases whose expected docs are [] or only POL-SEV-001. "
              "Shown so you can see that the retriever still returns k chunks for them: "
              "recognising that those chunks do not explain the incident is the "
              "generator's job (abstention).", ""]
    for entry in res["skipped"]:
        lines.append(f"- **{entry['case_id']}** (expected {entry['expected_doc_ids']}):")
        for m in modes:
            top = entry["top"][m]
            top = ", ".join(top) if isinstance(top, list) else top
            lines.append(f"  - {m}: {top or '(nothing)'}")
    lines += ["", "## Caveats", "",
              "- Recall says the passage was *retrieved*, not that the model used it well.",
              "- Labels and corpus share an author; absolute numbers are optimistic.",
              "- Expected docs are a floor: a sensible extra doc lowers nothing here, but a "
              "near-miss distractor ranked above the right doc pushes it out of the top k.",
              ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- CLI


def main(
    argv: list[str] | None = None,
    *,
    settings: Settings | None = None,
    retriever: Retriever | None = None,
    reranker: Reranker | None = None,
    now: datetime | None = None,
) -> int:
    p = argparse.ArgumentParser(prog="python -m eval.retrieval_eval",
                                description=__doc__.split("\n")[0])
    p.add_argument("--modes", nargs="+", choices=ALL_RETRIEVAL_MODES,
                   default=list(ALL_RETRIEVAL_MODES))
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--rerank-model", default=None,
                   help="cross-encoder for +rerank modes (default: settings.rerank_model)")
    p.add_argument("--out", type=Path, default=Path("eval/results"))
    p.add_argument("--cases-file", type=Path, default=DEFAULT_CASES_PATH)
    args = p.parse_args(argv)
    settings = settings or get_settings()
    if args.rerank_model:
        settings = settings.model_copy(update={"rerank_model": args.rerank_model})
    modes: list[str] = list(dict.fromkeys(args.modes))

    injected = retriever is not None
    try:
        cases = load_cases(args.cases_file)
        # First stage without reranking: the +rerank variants add it explicitly.
        retriever = retriever or build_retriever(settings.model_copy(update={"rerank": False}))
        if any(m.endswith(RERANK_SUFFIX) for m in modes):
            retriever = VariantRetriever(
                retriever,
                RerankingRetriever(retriever, reranker or FastEmbedReranker(
                    settings.rerank_model), candidates=settings.rerank_candidates),
            )
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}. Run `python -m scripts.ingest` first?",
              file=sys.stderr)
        return 2

    results = evaluate(cases, retriever, modes, args.k)
    sha, dirty = git_info()
    run_id = make_run_id(sha, now) + "-retrieval"
    metadata = {
        "run_id": run_id,
        "timestamp_utc": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "git_sha": sha,
        "git_dirty": dirty,
        "retriever": getattr(retriever, "label", type(retriever).__name__),
        "injected_retriever": injected,
        "store_backend": settings.store_backend,
        "embedder": f"{settings.embedder} ({settings.embedding_model})",
        "k": args.k,
        "modes": modes,
        "reranker": settings.rerank_model if any(m.endswith(RERANK_SUFFIX) for m in modes)
        else None,
        "rerank_candidates": settings.rerank_candidates
        if any(m.endswith(RERANK_SUFFIX) for m in modes) else None,
        "cases_sha256": sha256_file(args.cases_file),
        "corpus_sha256": sha256_dir(settings.corpus_dir) if settings.corpus_dir.exists() else None,
        "n_cases_scored": len({r["case_id"] for r in results["rows"]}),
        "n_cases_skipped": len(results["skipped"]),
        "primary_docs": {c.id: primary_doc(c) for c in cases if is_scored(c)},
    }
    summary = {"metadata": metadata, "results": results}
    run_dir = args.out / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str),
                                          encoding="utf-8", newline="\n")
    (args.out / "retrieval-latest.md").write_text(render(summary), encoding="utf-8",
                                                  newline="\n")
    print(f"wrote {run_dir / 'summary.json'} and {args.out / 'retrieval-latest.md'}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
