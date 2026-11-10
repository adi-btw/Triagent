"""Base vs fine-tuned severity classifier on the held-out test split.

    python -m finetune.evaluate --out finetune/results/base.json                 # zero-shot
    python -m finetune.evaluate --adapter finetune/outputs/adapter \\
        --out finetune/results/qlora.json                                        # with adapters
    python -m finetune.evaluate compare finetune/results/base.json finetune/results/qlora.json

Both runs use the same base model, the same prompt and the same test rows. Only the
adapters differ. That's the control the experiment needs (finetune/README.md).

**Constrained scoring.** Neither model generates free text. Each of SEV1–SEV4 is scored by
log-probability as the answer, and the highest wins, so an invalid label is impossible
and formatting failures can't count against the base model.

Metrics: accuracy with a bootstrap 95% CI, macro-F1 (classes are balanced, but F1 shows
which ones suffer), within-one-level accuracy, the confusion matrix, accuracy per
template and on boundary cases, and latency per example. ``compare`` adds a paired
bootstrap CI on the accuracy difference, because both models see the same rows.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from finetune.common import DEFAULT_BASE, LABELS, load_split, score_labels

RESULTS = Path("finetune/results")
ORDER = {lab: i for i, lab in enumerate(LABELS)}


def is_boundary(facts: dict[str, Any]) -> bool:
    """Rows whose numbers sit on a rubric edge: 4–6% or 48–55% errors, or 2.6–3.4x p95."""
    if facts.get("kind") != "service" or facts.get("full_outage"):
        return False
    e, m = facts.get("error_pct", 0), facts.get("latency_mult", 1)
    return 4 <= e <= 6 or 48 <= e <= 55 or 2.6 <= m <= 3.4


def metrics(rows: list[dict[str, Any]], seed: int = 0) -> dict[str, Any]:
    gold = [r["label"] for r in rows]
    pred = [r["pred"] for r in rows]
    n = len(rows)
    correct = [g == p for g, p in zip(gold, pred, strict=True)]
    rng = random.Random(seed)
    boots = sorted(sum(correct[rng.randrange(n)] for _ in range(n)) / n for _ in range(2000))
    f1s = {}
    for lab in LABELS:
        tp = sum(g == p == lab for g, p in zip(gold, pred, strict=True))
        fp = sum(p == lab != g for g, p in zip(gold, pred, strict=True))
        fn = sum(g == lab != p for g, p in zip(gold, pred, strict=True))
        f1s[lab] = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
    confusion = {g: {p: 0 for p in LABELS} for g in LABELS}
    for g, p in zip(gold, pred, strict=True):
        confusion[g][p] += 1
    by_t: dict[str, list[bool]] = defaultdict(list)
    for r, c in zip(rows, correct, strict=True):
        by_t[r["template"]].append(c)
    boundary = [c for r, c in zip(rows, correct, strict=True) if is_boundary(r["facts"])]
    return {
        "n": n, "accuracy": sum(correct) / n,
        "accuracy_ci": [boots[int(0.025 * len(boots))], boots[int(0.975 * len(boots)) - 1]],
        "macro_f1": sum(f1s.values()) / len(LABELS), "f1": f1s,
        "within_one": sum(abs(ORDER[g] - ORDER[p]) <= 1
                          for g, p in zip(gold, pred, strict=True)) / n,
        "under_rated": sum(ORDER[p] > ORDER[g] for g, p in zip(gold, pred, strict=True)),
        "over_rated": sum(ORDER[p] < ORDER[g] for g, p in zip(gold, pred, strict=True)),
        "confusion": confusion,
        "by_template": {t: sum(v) / len(v) for t, v in sorted(by_t.items())},
        "boundary": {"n": len(boundary),
                     "accuracy": sum(boundary) / len(boundary) if boundary else None},
        "predicted_mix": dict(Counter(pred)),
    }


def run(args: argparse.Namespace) -> int:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    cuda = torch.cuda.is_available()
    tok = AutoTokenizer.from_pretrained(args.base)
    dtype = torch.float16 if cuda else (torch.bfloat16 if args.bf16 else torch.float32)
    model = AutoModelForCausalLM.from_pretrained(args.base, torch_dtype=dtype)
    if args.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, str(args.adapter))
        model = model.merge_and_unload()  # same speed as the base at inference
    model.to("cuda" if cuda else "cpu").eval()
    rows = load_split(args.split, args.limit)
    out, t0 = [], time.perf_counter()
    for i, r in enumerate(rows, 1):
        t = time.perf_counter()
        scores = score_labels(model, tok, r["prompt"])
        out.append({"id": r["id"], "template": r["template"], "facts": r["facts"],
                    "label": r["label"], "pred": max(scores, key=scores.get),
                    "scores": scores, "ms": (time.perf_counter() - t) * 1000})
        if i % 25 == 0 or i == len(rows):
            acc = sum(o["pred"] == o["label"] for o in out) / len(out)
            print(f"[{i}/{len(rows)}] accuracy so far {acc:.3f}", flush=True)
    m = metrics(out)
    m["ms_per_example"] = (time.perf_counter() - t0) * 1000 / len(out)
    result = {"base": args.base, "adapter": str(args.adapter) if args.adapter else None,
              "split": str(args.split), "device": "cuda" if cuda else "cpu",
              "dtype": str(dtype).replace("torch.", ""), "metrics": m, "rows": out}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1), encoding="utf-8", newline="\n")
    print(f"accuracy {m['accuracy']:.3f}  macro-F1 {m['macro_f1']:.3f}  wrote {args.out}")
    return 0


# --------------------------------------------------------------------------- compare


def paired_diff_ci(a: list[dict], b: list[dict], seed: int = 0) -> tuple[float, float, float]:
    by_id = {r["id"]: r for r in a}
    pairs = [(by_id[r["id"]]["pred"] == r["label"], r["pred"] == r["label"]) for r in b
             if r["id"] in by_id]
    n = len(pairs)
    diff = sum(y - x for x, y in pairs) / n
    rng = random.Random(seed)
    boots = sorted(sum(pairs[k][1] - pairs[k][0] for k in (rng.randrange(n) for _ in range(n))) / n
                   for _ in range(2000))
    return diff, boots[50], boots[1949]


def render(base: dict, tuned: dict, training: dict | None) -> str:
    mb, mt = base["metrics"], tuned["metrics"]

    def pct(x: float | None) -> str:
        return "n/a" if x is None else f"{x * 100:.1f}%"

    def f1_row(m: dict) -> str:  # no nested f-string quotes: Colab runs Python 3.10/3.11
        return " / ".join(format(m["f1"][x], ".2f") for x in LABELS)

    def ci(m: dict) -> str:
        return f"{pct(m['accuracy'])} [{pct(m['accuracy_ci'][0])}–{pct(m['accuracy_ci'][1])}]"

    d, lo, hi = paired_diff_ci(base["rows"], tuned["rows"])
    verdict = ("**significant improvement**" if lo > 0 else "**significantly worse**" if hi < 0
               else "**no significant difference**")
    lines = [
        "# QLoRA severity classifier: results", "",
        f"Base model `{base['base']}`, the same prompt, {mb['n']} held-out test incidents "
        "from scenario templates never seen in training. Labels are computed from POL-SEV-001; "
        "both models are scored by constrained log-probability over SEV1–SEV4.", "",
        f"Accuracy change: **{d * 100:+.1f} points** (paired bootstrap 95% CI "
        f"{lo * 100:+.1f} to {hi * 100:+.1f}): {verdict}.", "",
        "| | Base (zero-shot) | QLoRA |", "|---|---|---|",
        f"| Accuracy [95% CI] | {ci(mb)} | {ci(mt)} |",
        f"| Macro-F1 | {mb['macro_f1']:.3f} | {mt['macro_f1']:.3f} |",
        f"| Within one level | {pct(mb['within_one'])} | {pct(mt['within_one'])} |",
        f"| Boundary cases (n={mb['boundary']['n']}) | {pct(mb['boundary']['accuracy'])} | "
        f"{pct(mt['boundary']['accuracy'])} |",
        f"| Under-rated (said less severe) | {mb['under_rated']} | {mt['under_rated']} |",
        f"| Over-rated (said more severe) | {mb['over_rated']} | {mt['over_rated']} |",
        f"| F1 SEV1 / SEV2 / SEV3 / SEV4 | {f1_row(mb)} | {f1_row(mt)} |",
        f"| Latency per example ({base['device']} / {tuned['device']}) | "
        f"{mb['ms_per_example']:.0f} ms | {mt['ms_per_example']:.0f} ms |", "",
        "## Accuracy by test template", "", "| Template | Base | QLoRA |", "|---|---|---|",
    ]
    for t in mb["by_template"]:
        lines.append(f"| {t} | {pct(mb['by_template'][t])} | {pct(mt['by_template'].get(t))} |")
    for name, m in (("Base", mb), ("QLoRA", mt)):
        lines += ["", f"## Confusion matrix: {name} (rows: gold, columns: predicted)", "",
                  "| | " + " | ".join(LABELS) + " |", "|---" * 5 + "|"]
        lines += [f"| {g} | " + " | ".join(str(m["confusion"][g][p]) for p in LABELS) + " |"
                  for g in LABELS]
    if training:
        lines += ["", "## Training", "", "| | |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in training.items()]
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "compare":
        p = argparse.ArgumentParser(prog="python -m finetune.evaluate compare")
        p.add_argument("base", type=Path)
        p.add_argument("tuned", type=Path)
        p.add_argument("--training", type=Path, default=None)
        p.add_argument("--out", type=Path, default=RESULTS / "README.md")
        a = p.parse_args(argv[1:])
        load = lambda q: json.loads(q.read_text(encoding="utf-8"))  # noqa: E731
        training = load(a.training) if a.training and a.training.exists() else None
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(render(load(a.base), load(a.tuned), training), encoding="utf-8",
                         newline="\n")
        print(f"wrote {a.out}")
        return 0
    p = argparse.ArgumentParser(prog="python -m finetune.evaluate")
    p.add_argument("--base", default=DEFAULT_BASE)
    p.add_argument("--adapter", type=Path, default=None)
    p.add_argument("--split", type=Path, default=Path("finetune/data/test.jsonl"))
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--bf16", action="store_true", help="CPU: bfloat16 weights (half the RAM)")
    p.add_argument("--out", type=Path, required=True)
    return run(p.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
