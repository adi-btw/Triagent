"""Threshold logic of the CI retrieval gate (eval/retrieval_gate.py)."""

from eval.retrieval_gate import THRESHOLDS, check


def overall(**means):
    return {m: {"mean": means.get(m, 1.0), "n": 25} for m in THRESHOLDS}


def test_passes_at_or_above_every_threshold():
    assert check(overall(**THRESHOLDS), THRESHOLDS) == []
    assert check(overall(), THRESHOLDS) == []


def test_one_primary_miss_in_25_is_tolerated_two_are_not():
    assert check(overall(primary_hit=24 / 25), THRESHOLDS) == []
    failures = check(overall(primary_hit=23 / 25), THRESHOLDS)
    assert len(failures) == 1 and failures[0].startswith("primary_hit")


def test_missing_metric_fails():
    data = overall()
    data["mrr"]["mean"] = None
    assert check(data, THRESHOLDS) == ["mrr: n/a < 0.70"]
