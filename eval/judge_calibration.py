"""Calibrate the LLM judge against a human: how far can "claims supported" be trusted?

    python -m eval.judge_calibration export   # draw the blind sample (no LLM calls)
    python -m eval.judge_calibration score    # agreement + Cohen's kappa vs your labels

The end-to-end eval reports "claims supported by the cited passage" from an LLM judge,
and the judge is the same model as the generator. This tool measures how often a person
reading the same claim and passages agrees with it.

**Sample.** Claims the LLM judge graded in RAG and agent mode (claims without citations
are scored by a rule, not the judge, so they're excluded). Stratified by the judge's
verdict, with a fixed seed: ``supported`` is two thirds of all verdicts, so a simple random
sample would hold too few of the other classes to say anything about them. Agreement on a
stratified sample is not the agreement on all claims. The report gives both the raw sample
numbers and the agreement re-weighted to the real verdict mix.

**Blind.** The labelling page shows the incident, the claim and the cited passages, never
the judge's verdict. Verdicts are kept in ``sample.jsonl`` for scoring only.

**Metrics.** Raw agreement; Cohen's kappa (agreement corrected for chance, 3 classes);
kappa on the binary question the README cares about (``supported`` vs not); the confusion
matrix; and the judge's precision on ``supported`` (when the judge says supported, how
often the human agrees), which is what the "claims supported" number depends on.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from eval.cases import DEFAULT_CASES_PATH, load_cases
from eval.metrics import bootstrap_ci

DIR = Path("data/eval/judge_calibration")
SAMPLE = DIR / "sample.jsonl"
LABELS = DIR / "human_labels.jsonl"
REPORT = Path("eval/results/judge-calibration.md")
DEFAULT_RUN = Path("eval/results/runs/20261110T024152Z-738ce87/raw.jsonl")
CLASSES = ("supported", "partially_supported", "not_supported")
QUOTA = {"supported": 14, "partially_supported": 12, "not_supported": 14}
SEED = 7


# --------------------------------------------------------------------------- export


def judged_claims(raw_path: Path) -> list[dict[str, Any]]:
    """Every claim graded by the LLM judge, with the cited passages' text attached."""
    incidents = {c.id: c.incident for c in load_cases(DEFAULT_CASES_PATH)}
    out = []
    for line in raw_path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["mode"] == "no_retrieval" or not r.get("response"):
            continue
        evidence = {e["chunk_id"]: e for e in r["response"]["evidence"]}
        for cl in r.get("claims") or []:
            if cl.get("source") != "judge" or cl.get("verdict") not in CLASSES:
                continue
            out.append({
                "item_id": f"{r['case_id']}:{r['mode']}:{cl['claim_id']}",
                "case_id": r["case_id"], "mode": r["mode"], "kind": cl["kind"],
                "incident": incidents.get(r["case_id"], ""),
                "claim": cl["text"],
                "passages": [{k: evidence[c][k] for k in ("chunk_id", "title", "heading",
                                                          "content")}
                             for c in cl["citations"] if c in evidence],
                "judge_verdict": cl["verdict"],
                "judge_reason": cl.get("reason", ""),
            })
    return out


def stratified_sample(claims: list[dict], quota: dict[str, int], seed: int) -> list[dict]:
    rng = random.Random(seed)
    picked = []
    for cls, n in quota.items():
        pool = sorted((c for c in claims if c["judge_verdict"] == cls), key=lambda c: c["item_id"])
        picked += rng.sample(pool, min(n, len(pool)))
    rng.shuffle(picked)  # labelling order must not reveal the stratum
    return picked


def export(raw_path: Path) -> int:
    claims = judged_claims(raw_path)
    sample = stratified_sample(claims, QUOTA, SEED)
    DIR.mkdir(parents=True, exist_ok=True)
    with SAMPLE.open("w", encoding="utf-8", newline="\n") as f:
        for item in sample:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    mix = Counter(c["judge_verdict"] for c in claims)
    meta = {"source_run": raw_path.as_posix(), "seed": SEED, "quota": QUOTA,
            "population_verdicts": dict(mix), "n_population": len(claims)}
    (DIR / "sample_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8",
                                          newline="\n")
    print(f"wrote {len(sample)} of {len(claims)} judged claims to {SAMPLE}; population {dict(mix)}")
    return 0


# --------------------------------------------------------------------------- scoring


def cohens_kappa(a: list[str], b: list[str]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    labels = sorted(set(a) | set(b))
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in labels) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def binary(v: str) -> str:
    return "supported" if v == "supported" else "not fully supported"


def score(sample: list[dict], labels: dict[str, str], meta: dict) -> dict[str, Any]:
    rows = [(s, labels[s["item_id"]]) for s in sample if s["item_id"] in labels]
    judge = [s["judge_verdict"] for s, _ in rows]
    human = [h for _, h in rows]
    n = len(rows)
    agree = [float(j == h) for j, h in zip(judge, human, strict=True)]
    confusion = {j: {h: 0 for h in CLASSES} for j in CLASSES}
    for j, h in zip(judge, human, strict=True):
        confusion[j][h] += 1
    # Re-weight per-stratum agreement by the population's verdict mix.
    pop = meta["population_verdicts"]
    total = sum(pop.values())
    weighted = 0.0
    for cls in CLASSES:
        stratum = [a for a, j in zip(agree, judge, strict=True) if j == cls]
        if stratum:
            weighted += pop.get(cls, 0) / total * (sum(stratum) / len(stratum))
    said_supported = [h for j, h in zip(judge, human, strict=True) if j == "supported"]
    ci = bootstrap_ci([(a, 1.0) for a in agree]) if agree else None
    return {
        "n": n, "n_sample": len(sample),
        "agreement": sum(agree) / n if n else None, "agreement_ci": ci,
        "agreement_weighted": weighted if n else None,
        "kappa": cohens_kappa(judge, human),
        "kappa_binary": cohens_kappa([binary(x) for x in judge], [binary(x) for x in human]),
        "supported_precision": (sum(h == "supported" for h in said_supported)
                                / len(said_supported)) if said_supported else None,
        "n_judge_supported": len(said_supported),
        "confusion": confusion,
        "disagreements": [
            {"item_id": s["item_id"], "claim": s["claim"], "judge": s["judge_verdict"],
             "human": h, "judge_reason": s["judge_reason"]}
            for s, h in rows if s["judge_verdict"] != h
        ],
    }


def kappa_words(k: float | None) -> str:
    if k is None:
        return "n/a"
    for bound, word in ((0.8, "almost perfect"), (0.6, "substantial"), (0.4, "moderate"),
                        (0.2, "fair"), (0.0, "slight")):
        if k > bound:
            return word
    return "no better than chance"


def render(res: dict, meta: dict, labeler: str = "human") -> str:
    def pct(x: float | None) -> str:
        return "n/a" if x is None else f"{x * 100:.0f}%"

    lines = [
        f"# LLM judge vs {labeler} labels", "",
        f"Generated by `python -m eval.judge_calibration score`. {res['n']} of "
        f"{res['n_sample']} sampled claims labelled, blind to the judge's verdict. The sample is "
        f"stratified by judge verdict ({meta['quota']}) from {meta['n_population']} judged "
        f"claims (population mix {meta['population_verdicts']}).", "",
        "| Metric | Value |", "|---|---|",
        f"| Raw agreement (3 classes) [95% CI] | {pct(res['agreement'])}"
        + (f" [{pct(res['agreement_ci'][0])}–{pct(res['agreement_ci'][1])}]"
           if res["agreement_ci"] else "") + " |",
        f"| Agreement re-weighted to the population mix | {pct(res['agreement_weighted'])} |",
        f"| Cohen's kappa (3 classes) | {res['kappa']:.2f} ({kappa_words(res['kappa'])}) |"
        if res["kappa"] is not None else "| Cohen's kappa (3 classes) | n/a |",
        f"| Cohen's kappa (supported vs not) | {res['kappa_binary']:.2f} "
        f"({kappa_words(res['kappa_binary'])}) |"
        if res["kappa_binary"] is not None else "| Cohen's kappa (supported vs not) | n/a |",
        f"| Judge precision on \"supported\" ({labeler} agrees) | "
        f"{pct(res['supported_precision'])} (n={res['n_judge_supported']}) |", "",
        f"## Confusion matrix (rows: judge, columns: {labeler})", "",
        "| judge \\ other | " + " | ".join(CLASSES) + " |", "|---" * (len(CLASSES) + 1) + "|",
    ]
    for j in CLASSES:
        lines.append(f"| {j} | " + " | ".join(str(res["confusion"][j][h]) for h in CLASSES)
                     + " |")
    lines += ["", "## Disagreements", ""]
    if not res["disagreements"]:
        lines.append("_None._")
    for d in res["disagreements"]:
        claim = d["claim"].replace("|", "\\|")
        lines.append(f"- `{d['item_id']}`: judge **{d['judge']}**, {labeler} "
                     f"**{d['human']}**: {claim}")
    if labeler == "human":
        lines += ["", "One labeller, who also wrote the corpus: this measures agreement with "
                  "one careful reader, not ground truth.", ""]
    else:
        lines += ["", f"**These labels come from a second model ({labeler}), not a person.** "
                  "Agreement between two models is a consistency check. It can show that the "
                  "judge is erratic, but two models can share blind spots, so it does not "
                  "replace human calibration.", ""]
    return "\n".join(lines)


def load_labels(path: Path) -> dict[str, str]:
    labels = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("label") in CLASSES:
                labels[row["item_id"]] = row["label"]
    return labels


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m eval.judge_calibration")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--run", type=Path, default=DEFAULT_RUN)
    s = sub.add_parser("score")
    s.add_argument("--labels", type=Path, default=LABELS)
    s.add_argument("--labeler", default="human",
                   help='who labelled, shown in the report: "human" or a model name')
    s.add_argument("--report", type=Path, default=REPORT)
    args = p.parse_args(argv)
    if args.cmd == "export":
        return export(args.run)
    sample = [json.loads(x) for x in SAMPLE.read_text(encoding="utf-8").splitlines() if x]
    meta = json.loads((DIR / "sample_meta.json").read_text(encoding="utf-8"))
    res = score(sample, load_labels(args.labels), meta)
    args.report.write_text(render(res, meta, args.labeler), encoding="utf-8", newline="\n")
    print(f"{res['n']}/{res['n_sample']} labelled; agreement {res['agreement']}; "
          f"kappa {res['kappa']}; wrote {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
