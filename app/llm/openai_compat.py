"""``LLMClient`` for any OpenAI-compatible chat-completions API.

One client covers local and hosted open-weight models:

    Ollama (local, free)   OPENAI_BASE_URL=http://localhost:11434/v1   OPENAI_MODEL=qwen2.5:7b
    Groq                   OPENAI_BASE_URL=https://api.groq.com/openai/v1   + OPENAI_API_KEY
    OpenRouter             OPENAI_BASE_URL=https://openrouter.ai/api/v1     + OPENAI_API_KEY

Plain ``httpx`` instead of the ``openai`` SDK: the request is one POST, and every
provider above accepts it, so another dependency would add nothing.

Structured output: ``response_format`` with a JSON schema (the same cleaned schema Gemini
gets, ``app.llm.schema``), which Ollama and Groq enforce with constrained decoding.
``OPENAI_JSON_MODE=json_object`` falls back to "any JSON object" for providers or models
without schema support; the schema is then described in the system prompt and the
validator does the rest. As with Gemini, unparseable output is returned with
``parsed=None`` and becomes a ``schema_error``, never an exception.

Retries: 429 / 408 / 5xx and network errors, exponential backoff, at most 2 retries.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any, Literal

import httpx
from pydantic import BaseModel

from app.llm.base import LLMResult
from app.llm.errors import LLMCallError
from app.llm.gemini import parse_json
from app.llm.schema import to_gemini_json_schema

RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
JsonMode = Literal["json_schema", "json_object"]


class OpenAICompatClient:
    """``client`` (an ``httpx.Client``) and ``sleep`` are injectable for tests."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        json_mode: JsonMode = "json_schema",
        timeout_s: float = 120.0,
        max_retries: int = 2,
        backoff_base_s: float = 1.0,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model_name = model
        self.base_url = base_url.rstrip("/")
        self._json_mode = json_mode
        self._max_retries = max_retries
        self._backoff_base_s = backoff_base_s
        self._sleep = sleep
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.Client(timeout=timeout_s, headers=headers)

    def _body(self, system: str, user: str, schema: type[BaseModel],
              temperature: float) -> dict[str, Any]:
        json_schema = to_gemini_json_schema(schema)
        if self._json_mode == "json_schema":
            response_format: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": json_schema, "strict": False},
            }
        else:
            response_format = {"type": "json_object"}
            system = (f"{system}\n\nRespond with one JSON object matching this JSON schema:\n"
                      f"{json.dumps(json_schema)}")
        return {
            "model": self.model_name,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": temperature,
            "response_format": response_format,
            "stream": False,
        }

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        temperature: float = 0.0,
    ) -> LLMResult:
        body = self._body(system, user, schema, temperature)
        start = time.perf_counter()
        data = self._post_with_retries(body)
        latency_ms = (time.perf_counter() - start) * 1000
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMCallError(f"unexpected response shape: {str(data)[:300]}") from exc
        usage = data.get("usage") or {}
        return LLMResult(
            text=text,
            parsed=parse_json(text),
            model=self.model_name,
            latency_ms=latency_ms,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )

    def _post_with_retries(self, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        attempt = 0
        while True:
            try:
                resp = self._client.post(url, json=body)
                if resp.status_code < 400:
                    return resp.json()
                error: Exception = LLMCallError(
                    f"{resp.status_code} from {url}: {resp.text[:300]}")
                retryable = resp.status_code in RETRYABLE_STATUS
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                error, retryable = exc, True
            if not retryable:
                raise error if isinstance(error, LLMCallError) else LLMCallError(str(error))
            if attempt >= self._max_retries:
                raise LLMCallError(f"call failed after {attempt + 1} attempts: {error}") from (
                    error if not isinstance(error, LLMCallError) else None)
            self._sleep(self._backoff_base_s * (2**attempt))
            attempt += 1
