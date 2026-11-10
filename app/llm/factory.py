"""Pick the LLM implementation from settings (the only place that knows about providers)."""

from app.config import Settings
from app.llm.base import LLMClient
from app.llm.errors import LLMConfigError


def with_cache(client: LLMClient, settings: Settings) -> LLMClient:
    """Wrap ``client`` in the disk cache when ``settings.llm_cache`` is on.

    Demo mode always caches, in ``demo_cache_dir`` (pre-seeded with the UI's samples),
    and puts the daily budget *between* cache and provider so cache hits are free.
    """
    if not (settings.llm_cache or settings.demo_mode):
        return client
    from app.llm.cache import CachingLLM

    cache_dir = settings.llm_cache_dir
    if settings.demo_mode:
        from app.demo import BudgetedLLM, DailyBudget

        client = BudgetedLLM(client, DailyBudget(settings.demo_llm_calls_per_day))
        cache_dir = settings.demo_cache_dir
    extra = (f"gemini_thinking_level={settings.gemini_thinking_level}"
             if settings.llm_provider == "gemini"
             else f"openai_compat={settings.openai_base_url} json_mode={settings.openai_json_mode}")
    return CachingLLM(client, cache_dir, extra_key=extra)


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
        if not settings.gemini_api_key and settings.demo_mode:
            # Key-free public demo: serve pre-seeded answers only, never call a provider.
            from app.demo import OfflineLLM

            return with_cache(OfflineLLM(settings.gemini_model), settings)
        if not settings.gemini_api_key:
            raise LLMConfigError(
                "LLM_PROVIDER=gemini but GEMINI_API_KEY is not set. "
                "Add it to .env, or set LLM_PROVIDER=fake to run offline."
            )
        from app.llm.gemini import GeminiClient

        client = GeminiClient(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            timeout_s=settings.llm_timeout_s,
            thinking_level=settings.gemini_thinking_level,
        )
        return with_cache(client, settings)
    if settings.llm_provider == "openai_compat":
        from app.llm.openai_compat import OpenAICompatClient

        client = OpenAICompatClient(
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            json_mode=settings.openai_json_mode,
            timeout_s=settings.llm_timeout_s,
        )
        return with_cache(client, settings)
    raise LLMConfigError(f"Unknown llm_provider: {settings.llm_provider!r}")
