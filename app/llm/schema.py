"""Turn a Pydantic model into the JSON schema we send to Gemini.

Why not pass the Pydantic class straight to ``response_schema``? The SDK can do that,
but it first converts the class into its own OpenAPI-3.0-subset ``Schema`` type, and
that conversion has historically been the fragile part (``X | None`` unions, ``$ref``
to enums, defaults). The SDK's own docstring says: "If `response_schema` doesn't
process your schema correctly, try using `response_json_schema` instead."

So we send standard JSON Schema via ``response_json_schema`` and make it explicit and
inspectable (``python -c "from app.llm.schema import ...; print(...)"``). Three edits:

1. Drop ``default``: not in Gemini's supported keyword list.
2. Rewrite ``const`` (Pydantic's output for a one-value ``Literal``) as a one-item
   ``enum``; ``const`` is also not supported.
3. Mark *every* property required and record ``propertyOrdering``. The Python model
   still accepts omitted lists (they default to ``[]``), but asking the model to always
   emit ``citations`` makes it decide about them instead of silently skipping them,
   and ordering puts ``summary`` before the details, as a human would write it.

The schema only constrains *shape*. Whether citations point at real evidence is
checked afterwards by ``app.triage.validate``.
"""

from typing import Any

from pydantic import BaseModel


def to_gemini_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return a Gemini-compatible JSON schema for ``model`` (pure; no SDK import)."""
    return _clean(model.model_json_schema())


def _clean(node: Any) -> Any:
    if isinstance(node, list):
        return [_clean(item) for item in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in ("properties", "$defs"):
            # Keys here are field/definition *names*, not keywords: keep them all.
            out[key] = {name: _clean(sub) for name, sub in value.items()}
            continue
        if key == "default":
            continue
        if key == "const":
            out["enum"] = [value]
            continue
        out[key] = _clean(value)
    properties = out.get("properties")
    if out.get("type") == "object" and isinstance(properties, dict):
        out["required"] = list(properties)
        out["propertyOrdering"] = list(properties)
    return out
