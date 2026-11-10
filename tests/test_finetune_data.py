"""Stage-4 dataset and metrics. No ML stack needed: torch is only imported to run models."""

from __future__ import annotations

import json
import random
from collections import Counter

import pytest

from finetune import build_dataset as bd
from finetune import evaluate as ev
from finetune.common import label_token_ids


def F(**kw) -> bd.Facts:
    return bd.Facts(**kw)


# --------------------------------------------------------------------------- the rubric


@pytest.mark.parametrize("facts,expected", [
    # SEV1: revenue path fully unavailable or >50% errors; any data loss / exposure
    (F(kind="service", service="payments-api", full_outage=True, error_pct=100), "SEV1"),
    (F(kind="service", service="checkout-api", error_pct=51), "SEV1"),
    (F(kind="data_security", service="search-api", data_loss_or_exposure=True), "SEV1"),
    # SEV2: revenue path 5–50% errors (inclusive) or p95 >3x
    (F(kind="service", service="cart-api", error_pct=50), "SEV2"),
    (F(kind="service", service="cart-api", error_pct=5), "SEV2"),
    (F(kind="service", service="checkout-api", error_pct=1, latency_mult=3.1), "SEV2"),
    (F(kind="internal", service="CI", internal_down=True, workaround=False), "SEV2"),
    # SEV3: revenue path <5% errors and p95 <=3x; any non-revenue degradation
    (F(kind="service", service="checkout-api", error_pct=4.8, latency_mult=3.0), "SEV3"),
    (F(kind="service", service="search-api", error_pct=100, full_outage=True), "SEV3"),
    # SEV4: no customer impact
    (F(kind="internal", service="CI", internal_down=True, workaround=True), "SEV4"),
    (F(kind="no_impact", service="checkout-api"), "SEV4"),
])
def test_label_follows_policy_clauses(facts, expected):
    assert bd.label(facts) == expected


def test_policy_text_is_the_corpus_document():
    text = bd.policy_text()
    assert "SEV1: Checkout or payments fully unavailable" in text and "---" not in text
    assert all(s in text for s in bd.REVENUE + bd.NON_REVENUE)


# --------------------------------------------------------------------------- the dataset


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("ft")
    stats = bd.build(out)
    rows = {s: [json.loads(x) for x in (out / f"{s}.jsonl").read_text(encoding="utf-8")
                .splitlines()] for s in ("train", "val", "test")}
    return stats, rows, out


def test_split_sizes_are_balanced(built):
    stats, rows, _ = built
    for split, n in bd.PER_CLASS.items():
        assert Counter(r["label"] for r in rows[split]) == {lab: n for lab in bd.LABELS}


def test_templates_never_cross_splits(built):
    _, rows, _ = built
    t = {s: {r["template"] for r in rows[s]} for s in rows}
    assert not (t["train"] & t["test"]) and not (t["train"] & t["val"]) and not (
        t["val"] & t["test"])


def test_every_label_matches_its_facts(built):
    _, rows, _ = built
    for split in rows.values():
        for r in split:
            facts = bd.Facts(**r["facts"])
            assert bd.label(facts) == r["label"], r["id"]
            assert r["prompt"].endswith(r["incident"]) and "POL" not in r["incident"]


def test_build_is_deterministic(built, tmp_path):
    _, _, out = built
    bd.build(tmp_path)
    for s in ("train", "val", "test"):
        assert (tmp_path / f"{s}.jsonl").read_bytes() == (out / f"{s}.jsonl").read_bytes()


def test_committed_data_is_current(built):
    """finetune/data must be what the builder produces: rerun it after editing templates."""
    _, _, out = built
    for s in ("train", "val", "test"):
        assert (bd.OUT_DIR / f"{s}.jsonl").read_bytes() == (out / f"{s}.jsonl").read_bytes()


def test_no_stage3_eval_case_leaks(built):
    stats, _, _ = built
    assert stats["leakage_max_jaccard"]["train_vs_eval_cases"] < 0.5
    assert stats["leakage_max_jaccard"]["test_vs_eval_cases"] < 0.5


def test_boundary_cases_exist_in_test(built):
    _, rows, _ = built
    assert sum(ev.is_boundary(r["facts"]) for r in rows["test"]) >= 15


# --------------------------------------------------------------------------- metrics


def fake_rows(acc: float, n: int = 200, seed: int = 0) -> list[dict]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        gold = bd.LABELS[i % 4]
        pred = gold if rng.random() < acc else bd.LABELS[(i + 1) % 4]
        out.append({"id": f"t{i}", "template": f"tpl{i % 3}", "label": gold, "pred": pred,
                    "facts": {"kind": "service", "error_pct": 5 if i % 10 == 0 else 20}})
    return out


def test_metrics_and_paired_comparison():
    base, tuned = fake_rows(0.6), fake_rows(0.9, seed=1)
    mb = ev.metrics(base)
    assert 0.5 < mb["accuracy"] < 0.7 and mb["accuracy_ci"][0] < mb["accuracy"]
    assert mb["boundary"]["n"] == 20 and set(mb["f1"]) == set(bd.LABELS)
    d, lo, hi = ev.paired_diff_ci(base, tuned)
    assert d > 0.2 and lo > 0
    res = lambda rows: {"base": "m", "device": "cuda", "rows": rows,  # noqa: E731
                        "metrics": {**ev.metrics(rows), "ms_per_example": 50.0}}
    md = ev.render(res(base), res(tuned), {"train_minutes": 21.5})
    assert "significant improvement" in md and "| train_minutes | 21.5 |" in md


def test_label_tokens_share_a_prefix():
    class Tok:  # SEV1 -> [5, 6, 1] etc., like a digit-splitting BPE
        def __call__(self, text, add_special_tokens=False):
            return {"input_ids": [5, 6, int(text[-1])]}
    prefix, rest = label_token_ids(Tok())
    assert prefix == [5, 6] and rest == [[1], [2], [3], [4]]
