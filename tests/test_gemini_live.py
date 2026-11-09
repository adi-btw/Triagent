"""GeminiClient tests.

The first group runs offline against a fake SDK client (retry policy, parsing, token
counts). The last test is a real API call: marked ``slow`` (deselected by default) and
skipped unless GEMINI_API_KEY is set. Run it with ``pytest -m slow tests/test_gemini_live.py``.
"""

import os
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors as genai_errors

from app.config import Settings
from app.llm.errors import LLMCallError
from app.llm.gemini import GeminiClient
from app.schemas import TriageReport
from app.triage.pipeline import run_rag
from tests.fakes import DEMO_EVIDENCE, FakeRetriever


class FakeModels:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append(SimpleNamespace(model=model, contents=contents, config=config))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def response(text, prompt_tokens=120, output_tokens=40):
    usage = SimpleNamespace(prompt_token_count=prompt_tokens,
                            candidates_token_count=output_tokens)
    return SimpleNamespace(text=text, usage_metadata=usage)


def make_client(outcomes):
    models = FakeModels(outcomes)
    sleeps = []
    client = GeminiClient(api_key="unused", model="gemini-test",
                          client=SimpleNamespace(models=models), sleep=sleeps.append)
    return client, models, sleeps


def call(client):
    return client.generate_json(system="sys", user="usr", schema=TriageReport)


def test_parses_json_and_records_tokens_and_config():
    client, models, _ = make_client([response('{"summary": "x"}')])
    result = call(client)
    assert result.parsed == {"summary": "x"}
    assert (result.input_tokens, result.output_tokens) == (120, 40)
    config = models.calls[0].config
    assert config.response_mime_type == "application/json"
    assert config.system_instruction == "sys" and config.temperature == 0.0
    assert config.response_json_schema["title"] == "TriageReport"


def test_bad_json_returns_parsed_none_instead_of_raising():
    client, _, _ = make_client([response("not json at all")])
    result = call(client)
    assert result.parsed is None and result.text == "not json at all"


def test_retries_transient_errors_with_backoff():
    client, models, sleeps = make_client([
        genai_errors.ClientError(429, {"error": {"message": "slow down"}}),
        httpx.ReadTimeout("timeout"),
        response("{}"),
    ])
    assert call(client).parsed == {}
    assert len(models.calls) == 3 and sleeps == [1.0, 2.0]


def test_gives_up_after_two_retries():
    err = genai_errors.ServerError(503, {"error": {"message": "unavailable"}})
    client, models, _ = make_client([err, err, err])
    with pytest.raises(LLMCallError, match="3 attempts"):
        call(client)
    assert len(models.calls) == 3


def test_does_not_retry_client_errors():
    client, models, sleeps = make_client(
        [genai_errors.ClientError(400, {"error": {"message": "bad schema"}})]
    )
    with pytest.raises(LLMCallError):
        call(client)
    assert len(models.calls) == 1 and sleeps == []


@pytest.mark.slow
@pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="needs GEMINI_API_KEY")
def test_live_gemini_on_demo_incident():
    settings = Settings(llm_provider="gemini", gemini_api_key=os.environ["GEMINI_API_KEY"])
    llm = GeminiClient(api_key=settings.gemini_api_key or "", model=settings.gemini_model)
    with open("data/demo_incident.txt", encoding="utf-8") as fh:
        incident = fh.read()
    resp = run_rag(incident, retriever=FakeRetriever(DEMO_EVIDENCE), llm=llm, settings=settings)
    print(resp.model_dump_json(indent=2))
    assert resp.report is not None, resp.trace.violations
    assert resp.status == "ok", resp.trace.violations
    assert resp.report.severity is not None
    assert resp.trace.steps[1].detail["input_tokens"]
