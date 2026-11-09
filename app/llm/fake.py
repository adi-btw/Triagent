"""Offline LLM clients: ``ScriptedLLM`` for tests, ``DemoLLM`` for LLM_PROVIDER=fake.

Both implement the same one-method ``LLMClient`` protocol as ``GeminiClient``, which is
the point of having a protocol: the pipeline, API and eval never know which one they got.
"""

from __future__ import annotations

import json
import re
import time
import types as pytypes
import typing
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel

from app.llm.base import LLMResult
from app.schemas import TriageReport

ScriptedReply = dict[str, Any] | str | BaseModel | Exception
ReplyFn = Callable[[str, str, type[BaseModel]], dict[str, Any] | str | BaseModel]


@dataclass
class LLMCall:
    """One recorded call, so tests can assert on what the pipeline sent."""

    system: str
    user: str
    schema: type[BaseModel]
    temperature: float


def _to_result(reply: dict[str, Any] | str | BaseModel, model: str) -> LLMResult:
    """Normalise a scripted reply into an ``LLMResult`` exactly like a real client would.

    A ``str`` is treated as raw model text (so tests can feed garbage and get
    ``parsed=None``); a dict/model is serialised to JSON first.
    """
    if isinstance(reply, BaseModel):
        reply = reply.model_dump(mode="json")
    text = reply if isinstance(reply, str) else json.dumps(reply)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    return LLMResult(
        text=text,
        parsed=parsed if isinstance(parsed, dict) else None,
        model=model,
        latency_ms=0.0,
        input_tokens=len(text) // 4,  # rough, but non-None so trace code paths run
        output_tokens=len(text) // 4,
    )


class ScriptedLLM:
    """Test double: replays queued replies, or computes them with a function.

    >>> llm = ScriptedLLM([{"summary": "..."}, "not json", RuntimeError("boom")])
    >>> llm = ScriptedLLM(lambda system, user, schema: {...})

    Queued ``Exception`` instances are raised (to test error paths). Running out of
    queued replies raises ``AssertionError``: a test that makes more LLM calls than it
    scripted is almost always a bug worth failing loudly on.
    """

    def __init__(
        self, replies: Iterable[ScriptedReply] | ReplyFn, *, model_name: str = "scripted"
    ) -> None:
        self.model_name = model_name
        self.calls: list[LLMCall] = []
        self._fn: ReplyFn | None = replies if callable(replies) else None
        self._queue: deque[ScriptedReply] = deque() if callable(replies) else deque(replies)

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        temperature: float = 0.0,
    ) -> LLMResult:
        self.calls.append(LLMCall(system, user, schema, temperature))
        if self._fn is not None:
            return _to_result(self._fn(system, user, schema), self.model_name)
        if not self._queue:
            raise AssertionError(f"ScriptedLLM ran out of replies after {len(self.calls)} calls")
        reply = self._queue.popleft()
        if isinstance(reply, Exception):
            raise reply
        return _to_result(reply, self.model_name)


# --------------------------------------------------------------------------- DemoLLM

_EVIDENCE_TAG = re.compile(r'<evidence id="([^"]+)" title="([^"]*)" heading="([^"]*)">')


class DemoLLM:
    """Deterministic stand-in so the UI and CLI work with no API key.

    For ``TriageReport`` it reads the ``<evidence id=... title=... heading=...>`` tags in
    the user prompt and builds a report that is *valid by construction*: it cites only
    ids it saw, cites the severity policy chunk if one was retrieved, and abstains when
    there is no evidence. It does not understand the incident; the summary is labelled
    "[fake LLM]" so nobody mistakes it for analysis.

    Limitation: for any other schema (e.g. the agent's decision schema later) it returns
    a minimal instance built from field defaults / first enum or Literal option. That
    is enough to exercise plumbing, not to test behaviour; use ``ScriptedLLM`` for that.
    """

    model_name = "fake-demo"

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        temperature: float = 0.0,
    ) -> LLMResult:
        start = time.perf_counter()
        if schema is TriageReport:
            reply: dict[str, Any] = self._triage_report(user)
        else:
            reply = schema.model_validate(minimal_instance(schema)).model_dump(mode="json")
        result = _to_result(reply, self.model_name)
        result.latency_ms = (time.perf_counter() - start) * 1000
        return result

    @staticmethod
    def _triage_report(user: str) -> dict[str, Any]:
        tags = _EVIDENCE_TAG.findall(user)
        if not tags:
            # Either no-retrieval mode or retrieval found nothing: no ids to cite.
            return {
                "summary": "[fake LLM] No evidence was provided, so no grounded diagnosis.",
                "severity": None,
                "severity_citations": [],
                "likely_causes": [],
                "next_steps": [],
                "insufficient_evidence": True,
                "missing_information": ["Relevant runbook or past-incident evidence"],
            }
        policy_ids = [cid for cid, _, _ in tags if cid.startswith("POL-SEV")]
        other = [(cid, title, heading) for cid, title, heading in tags if cid not in policy_ids]
        causes = [
            {
                "description": f"Matches '{title}' ({heading})",
                "confidence": "medium" if i == 0 else "low",
                "citations": [cid],
            }
            for i, (cid, title, heading) in enumerate(other[:2])
        ]
        steps = [
            {"action": f"Follow '{heading}' in {title}", "citations": [cid]}
            for cid, title, heading in other[:2]
        ]
        insufficient = not causes
        return {
            "summary": f"[fake LLM] Incident resembles: {', '.join(c for c, _, _ in other[:2])}"
            if other
            else "[fake LLM] Only the severity policy was retrieved.",
            "severity": "SEV2" if policy_ids else None,
            "severity_citations": policy_ids[:1],
            "likely_causes": causes,
            "next_steps": steps,
            "insufficient_evidence": insufficient or not policy_ids,
            "missing_information": ["Matching runbook evidence"] if insufficient else [],
        }


def minimal_instance(schema: type[BaseModel]) -> dict[str, Any]:
    """Smallest dict that validates as ``schema``: required fields get a trivial value."""
    out: dict[str, Any] = {}
    hints = typing.get_type_hints(schema)
    for name, field in schema.model_fields.items():
        if not field.is_required():
            continue
        out[name] = _trivial_value(hints.get(name, field.annotation))
    return out


def _trivial_value(tp: Any) -> Any:
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin is typing.Literal:
        return args[0]
    if origin in (typing.Union, pytypes.UnionType):
        return None if type(None) in args else _trivial_value(args[0])
    if origin in (list, set, tuple, frozenset):
        return []
    if origin is dict:
        return {}
    if isinstance(tp, type):
        if issubclass(tp, Enum):
            return next(iter(tp)).value
        if issubclass(tp, BaseModel):
            return minimal_instance(tp)
        if issubclass(tp, bool):
            return False
        if issubclass(tp, (int, float)):
            return 0
        if issubclass(tp, str):
            return ""
    return None
