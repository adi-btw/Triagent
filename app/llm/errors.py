"""Errors raised by the LLM layer.

Kept separate from ``base.py`` so callers (pipeline, API) can catch them without
importing a concrete client (and therefore without importing the Gemini SDK).
"""


class LLMConfigError(RuntimeError):
    """The LLM cannot be built from the current settings (e.g. no API key).

    The API maps this to HTTP 503: the server is up, but a dependency it needs is not.
    """


class LLMCallError(RuntimeError):
    """A model call failed for good (non-retryable error, or retries exhausted).

    Note what is *not* an error: a reply that is not valid JSON or does not match the
    schema. That comes back as a normal ``LLMResult`` with ``parsed=None`` so the
    validator can report it as a ``schema_error`` and the eval can count it.
    """
