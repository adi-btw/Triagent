"""Gemini implementation of ``LLMClient`` using the ``google-genai`` SDK.

Design notes (the "why"):

* **JSON mode + schema.** ``response_mime_type="application/json"`` plus
  ``response_json_schema`` asks Gemini for constrained JSON. We pass plain JSON Schema
  (see ``app.llm.schema``) rather than the Pydantic class, because the SDK's
  Pydantic -> OpenAPI conversion is the part that has historically mishandled
  ``Optional``/``Enum``/defaults, and the SDK itself recommends ``response_json_schema``
  as the fallback. Constrained decoding makes output *shaped* right; it does not make
  it *true*, which is why ``app.triage.validate`` exists.
* **Never raise on bad JSON.** If the text does not parse we return ``parsed=None``.
  A malformed answer is a model-quality fact the validator records as
  ``schema_error`` (and the eval counts), not an infrastructure failure.
* **Our own retry loop.** The SDK only retries when ``HttpRetryOptions`` is given; we
  keep retries explicit here so the policy is visible and unit-testable: retry
  429 / 408 / 5xx / network timeouts with exponential backoff, at most 2 retries;
  never retry other 4xx (a bad request will be just as bad the second time).
* **Measure.** Latency (``time.perf_counter``, monotonic) and token counts from
  ``usage_metadata`` go into ``LLMResult`` so the trace and eval can report cost.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from app.llm.base import LLMResult
from app.llm.errors import LLMCallError
from app.llm.schema import to_gemini_json_schema

RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


def is_retryable(exc: BaseException) -> bool:
    """True for transient failures worth another attempt (rate limit, server, network)."""
    if isinstance(exc, genai_errors.APIError):
        return exc.code in RETRYABLE_STATUS
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError, TimeoutError))


def parse_json(text: str) -> dict[str, Any] | None:
    """``json.loads`` that returns None instead of raising, and only accepts objects."""
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


class GeminiClient:
    """``LLMClient`` backed by Gemini. ``client`` and ``sleep`` are injectable for tests."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_s: float = 60.0,
        max_retries: int = 2,
        backoff_base_s: float = 1.0,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model_name = model
        self._max_retries = max_retries
        self._backoff_base_s = backoff_base_s
        self._sleep = sleep
        # HttpOptions.timeout is in milliseconds.
        self._client = client or genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
        )

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        temperature: float = 0.0,
    ) -> LLMResult:
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=to_gemini_json_schema(schema),
            temperature=temperature,
        )
        start = time.perf_counter()
        response = self._call_with_retries(user, config)
        latency_ms = (time.perf_counter() - start) * 1000

        text = response.text or ""
        usage = getattr(response, "usage_metadata", None)
        return LLMResult(
            text=text,
            parsed=parse_json(text),
            model=self.model_name,
            latency_ms=latency_ms,
            input_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
        )

    def _call_with_retries(self, user: str, config: types.GenerateContentConfig) -> Any:
        attempt = 0
        while True:
            try:
                return self._client.models.generate_content(
                    model=self.model_name, contents=user, config=config
                )
            except Exception as exc:
                if not is_retryable(exc):
                    raise LLMCallError(f"Gemini call failed: {exc}") from exc
                if attempt >= self._max_retries:
                    raise LLMCallError(
                        f"Gemini call failed after {attempt + 1} attempts: {exc}"
                    ) from exc
                # 1s, 2s, ... : exponential backoff gives a rate limiter time to refill.
                self._sleep(self._backoff_base_s * (2**attempt))
                attempt += 1
