"""Retrieval regression gate for CI: fail the build if search quality drops.

    python -m scripts.ingest           # build the index
    python -m eval.retrieval_gate      # exit 0 if every threshold holds, 1 otherwise

Runs the same scoring as ``eval.retrieval_eval`` on the labeled cases, for the default
retrieval mode only, and compares the overall means with ``THRESHOLDS``. It needs no LLM,
so it is free and deterministic and can run on every push. A corpus edit, chunker
change, embedder upgrade or ranking tweak that loses the primary document for a case
fails CI instead of quietly lowering end-to-end quality.

Thresholds sit a little below the measured values (hybrid, k=5: primary hit 100%, doc
recall 59%, MRR 78%) so that a one-case wobble from an intentional change is visible
but does not block. Primary hit allows exactly one miss in 25. If a change *should*
move a number, update the threshold in the same commit, so the change is reviewable.
"""

from __future__ import annotations

import argparse
import sys

from app.config import get_settings
from app.retrieval.factory import build_retriever
from eval.cases import DEFAULT_CASES_PATH, load_cases
from eval.retrieval_eval import evaluate

K = 5
THRESHOLDS: dict[str, float] = {
    "primary_hit": 0.96,
    "doc_recall": 0.55,
    "chunk_recall": 0.55,
    "mrr": 0.70,
}


def check(overall: dict, thresholds: dict[str, float]) -> list[str]:
    """Human-readable failures; empty means the gate passes."""
    failures = []
    for metric, minimum in thresholds.items():
        mean = overall[metric]["mean"]
        if mean is None or mean < minimum:
            shown = "n/a" if mean is None else f"{mean:.3f}"
            failures.append(f"{metric}: {shown} < {minimum:.2f}")
    return failures


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m eval.retrieval_gate",
                                description=__doc__.split("\n")[0])
    p.add_argument("--mode", default=None, help="retrieval mode (default: settings)")
    args = p.parse_args(argv)
    settings = get_settings()
    mode = args.mode or settings.retrieval_mode
    retriever = build_retriever(settings.model_copy(update={"rerank": False}))
    overall = evaluate(load_cases(DEFAULT_CASES_PATH), retriever, [mode], K)["overall"][mode]

    for metric, minimum in THRESHOLDS.items():
        mean = overall[metric]["mean"]
        print(f"{mode:>8} {metric:<13} {mean:.3f}  (min {minimum:.2f}, n={overall[metric]['n']})")
    failures = check(overall, THRESHOLDS)
    if failures:
        print("RETRIEVAL REGRESSION: " + "; ".join(failures), file=sys.stderr)
        return 1
    print("retrieval gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
