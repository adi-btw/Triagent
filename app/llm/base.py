from typing import Any, Protocol

from pydantic import BaseModel


class LLMResult(BaseModel):
    text: str  # raw model output
    parsed: dict[str, Any] | None  # json.loads(text) if it parsed, else None
    model: str
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMClient(Protocol):
    """One method on purpose: every call (report, agent decision, judge) is
    "system + user prompt in, JSON matching a Pydantic schema out"."""

    model_name: str

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        temperature: float = 0.0,
    ) -> LLMResult: ...
