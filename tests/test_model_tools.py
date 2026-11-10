"""OpenAI-compatible client, model comparison report, judge calibration scoring."""

from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.llm.cache import CachingLLM
from app.llm.errors import LLMCallError
from app.llm.factory import build_llm
from app.llm.openai_compat import OpenAICompatClient
from app.schemas import TriageReport
from eval import compare_models, judge_calibration
from eval.judge import EvalSettings, build_judge_llm, judge_model_name


def client_with(handler, **kw) -> OpenAICompatClient:
    return OpenAICompatClient(base_url="http://llm.test/v1", model="qwen2.5:7b",
                              client=httpx.Client(transport=httpx.MockTransport(handler)),
                              sleep=lambda s: None, **kw)


def ok_body(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30}}


def test_sends_json_schema_and_parses_reply():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(json.loads(req.content))
        seen["url"] = str(req.url)
        return httpx.Response(200, json=ok_body('{"summary": "x"}'))

    r = client_with(handler).generate_json(system="S", user="U", schema=TriageReport)
    assert seen["url"] == "http://llm.test/v1/chat/completions"
    assert seen["model"] == "qwen2.5:7b" and seen["temperature"] == 0.0
    assert seen["messages"] == [{"role": "system", "content": "S"},
                                {"role": "user", "content": "U"}]
    rf = seen["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["name"] == "TriageReport"
    assert "summary" in rf["json_schema"]["schema"]["properties"]
    assert r.parsed == {"summary": "x"} and (r.input_tokens, r.output_tokens) == (120, 30)


def test_json_object_mode_puts_schema_in_system_prompt():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json=ok_body("{}"))

    client_with(handler, json_mode="json_object").generate_json(
        system="S", user="U", schema=TriageReport)
    assert seen["response_format"] == {"type": "json_object"}
    assert "JSON schema" in seen["messages"][0]["content"]


def test_unparseable_reply_is_returned_not_raised():
    r = client_with(lambda req: httpx.Response(200, json=ok_body("a poem"))).generate_json(
        system="S", user="U", schema=TriageReport)
    assert r.parsed is None and r.text == "a poem"


def test_retries_rate_limits_then_succeeds():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429 if len(calls) < 3 else 200, json=ok_body("{}"))

    r = client_with(handler).generate_json(system="S", user="U", schema=TriageReport)
    assert r.parsed == {}
    assert len(calls) == 3


def test_client_errors_are_not_retried():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(400, text="bad model")

    with pytest.raises(LLMCallError, match="400"):
        client_with(handler).generate_json(system="S", user="U", schema=TriageReport)
    assert len(calls) == 1


def test_api_key_is_sent_as_bearer_only_when_set():
    assert "Authorization" not in OpenAICompatClient(base_url="http://x", model="m")._client.headers
    c = OpenAICompatClient(base_url="http://x", model="m", api_key="k")
    assert c._client.headers["Authorization"] == "Bearer k"


def test_factory_and_judge_use_openai_settings(tmp_path):
    s = Settings(_env_file=None, llm_provider="openai_compat", openai_model="llama3.2:3b",
                 llm_cache=True, llm_cache_dir=tmp_path)
    llm = build_llm(s)
    assert isinstance(llm, CachingLLM) and llm.model_name == "llama3.2:3b"
    ev = EvalSettings(_env_file=None, judge_model="qwen2.5:7b")
    assert judge_model_name(s, ev) == "qwen2.5:7b"
    assert build_judge_llm(s, ev).model_name == "qwen2.5:7b"
    assert judge_model_name(s, EvalSettings(_env_file=None)) == "llama3.2:3b"


# --------------------------------------------------------------------------- comparison


def summary(model: str, exact_k: int, judge: str | None = "j", hits: str = "0/10") -> dict:
    def rate(k, n):
        return ({"k": k, "n": n, "value": k / n, "ci": [0.1, 0.9]})
    by_mode = {"rag": {
        "severity": {"exact": rate(exact_k, 29), "within_one": rate(exact_k, 29)},
        "abstention": {"correct_abstention": rate(5, 7), "false_abstention": rate(0, 20)},
        "validity": {"status": {"ok": rate(32, 32), "invalid_output": rate(0, 32),
                                "error": rate(0, 32)}},
        "clarification": None,
        "claim_support": {"supported": rate(40, 60), "claims": 60},
        "latency": {"p50_ms": 1500, "p95_ms": 3000, "mean_llm_calls": 1, "mean_tokens": 1800},
    }}
    return {"metadata": {"run_id": f"run-{model}", "llm_model": model, "llm_provider": "x",
                         "judge_enabled": judge is not None, "judge_model": judge,
                         "cases_sha256": "c", "corpus_sha256": "k", "llm_cache_hits": hits},
            "metrics": {"by_mode": by_mode}}


def test_comparison_table_and_warnings():
    md = compare_models.render([summary("a", 23), summary("b", 20, judge="other")], "rag")
    assert "| | a | b |" in md
    assert "79% (23/29)" in md and "69% (20/29)" in md
    assert "different judges" in md
    assert "| Clarifying question on vague cases (agent) | n/a | n/a |" in md
    assert "replayed" not in md
    assert "replayed" in compare_models.render([summary("a", 23, hits="5/10")], "rag")


def test_comparison_flags_mismatched_cases():
    b = summary("b", 20)
    b["metadata"]["cases_sha256"] = "other"
    assert "not comparable" in compare_models.render([summary("a", 23), b], "rag")


# --------------------------------------------------------------------------- calibration


def test_cohens_kappa_known_values():
    k = judge_calibration.cohens_kappa
    assert k(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    assert k(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == 0.0
    # Classic example: 20 items, po=0.7, pe=0.5 -> kappa 0.4
    a = ["y"] * 10 + ["n"] * 10
    b = ["y"] * 7 + ["n"] * 3 + ["y"] * 3 + ["n"] * 7
    assert k(a, b) == pytest.approx(0.4)


def test_stratified_sample_is_deterministic_and_respects_quota():
    claims = [{"item_id": f"i{i}", "judge_verdict": v}
              for i, v in enumerate(["supported"] * 30 + ["not_supported"] * 3)]
    s1 = judge_calibration.stratified_sample(claims, {"supported": 5, "not_supported": 5}, 7)
    s2 = judge_calibration.stratified_sample(claims, {"supported": 5, "not_supported": 5}, 7)
    assert s1 == s2
    assert sum(c["judge_verdict"] == "not_supported" for c in s1) == 3  # capped by pool
    assert len(s1) == 8


def test_score_weights_by_population():
    sample = [
        {"item_id": "a", "judge_verdict": "supported", "claim": "c", "judge_reason": ""},
        {"item_id": "b", "judge_verdict": "supported", "claim": "c", "judge_reason": ""},
        {"item_id": "c", "judge_verdict": "not_supported", "claim": "c", "judge_reason": ""},
        {"item_id": "d", "judge_verdict": "not_supported", "claim": "c", "judge_reason": ""},
    ]
    labels = {"a": "supported", "b": "supported", "c": "supported", "d": "supported"}
    meta = {"population_verdicts": {"supported": 90, "not_supported": 10}}
    res = judge_calibration.score(sample, labels, meta)
    assert res["agreement"] == 0.5
    assert res["agreement_weighted"] == pytest.approx(0.9)  # 90% of claims are "supported"
    assert res["supported_precision"] == 1.0
    assert len(res["disagreements"]) == 2


def test_published_sample_is_blind_ready():
    text = judge_calibration.SAMPLE.read_text(encoding="utf-8")
    rows = [json.loads(x) for x in text.splitlines()]
    assert len(rows) == 40 and len({r["item_id"] for r in rows}) == 40
    assert all(r["passages"] and r["claim"] for r in rows)
