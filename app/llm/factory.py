"""Pick the LLM implementation from settings (the only place that knows about providers)."""

from app.config import Settings
from app.llm.base import LLMClient
from app.llm.errors import LLMConfigError


def build_llm(settings: Settings) -> LLMClient:
    """Return the configured ``LLMClient``.

    Raises ``LLMConfigError`` for ``llm_provider="gemini"`` without ``GEMINI_API_KEY``,
    with the two ways to fix it, instead of failing later inside the SDK.
    The Gemini import is deferred so ``LLM_PROVIDER=fake`` never loads the SDK.
    """
    if settings.llm_provider == "fake":
        from app.llm.fake import DemoLLM

        return DemoLLM()
    if settings.llm_provider == "gemini":
        if not settings.gemini_api_key:
            raise LLMConfigError(
                "LLM_PROVIDER=gemini but GEMINI_API_KEY is not set. "
                "Add it to .env, or set LLM_PROVIDER=fake to run offline."
            )
        from app.llm.gemini import GeminiClient

        return GeminiClient(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            timeout_s=settings.llm_timeout_s,
        )
    raise LLMConfigError(f"Unknown llm_provider: {settings.llm_provider!r}")
