from eval.metrics import compute_all, rate
from eval.report import SMOKE_BANNER, fmt_mean_pct, fmt_rate, render_report


def test_fmt_rate_shows_counts_ci_and_empty():
    assert fmt_rate(rate(3, 4, (0.25, 1.0)), ci=True) == "75% (3/4) [25-100]"
    assert fmt_rate(rate(0, 0)) == "n/a (n=0)"
    assert fmt_rate(None) == "n/a"
    assert fmt_mean_pct({"mean": 0.5, "n": 2}) == "50% (n=2)"


def test_render_report_with_no_results():
    summary = {
        "metadata": {"run_id": "r1", "modes": ["rag"], "n_cases": 0, "smoke": False},
        "metrics": compute_all([], ["rag"]),
    }
    md = render_report(summary)
    assert md.startswith("# Evaluation report: r1")
    assert SMOKE_BANNER not in md
    assert "| Metric | rag |" in md and "How to read this" in md
    assert "not meaningful" in md
