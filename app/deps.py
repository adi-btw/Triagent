"""FastAPI dependencies: settings, retriever, LLM. Built lazily and cached.

Lazy on purpose: ``import app.main`` must succeed with no API key and no index, so the
server can start, serve /health, and say *what* is missing (HTTP 503) instead of
crashing at import. Each heavy object is built on first use and cached for the process;
``functools.lru_cache`` does not cache exceptions, so a failed build is retried on the
next request (e.g. after you run the ingest script).

Tests swap any of these with ``app.dependency_overrides[get_llm] = lambda: fake``.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.config import Settings
from app.config import get_settings as _get_settings
from app.llm.base import LLMClient
from app.llm.factory import build_llm
from app.retrieval.base import Retriever
from app.retrieval.factory import build_retriever


class ServiceUnavailable(RuntimeError):
    """A dependency (index, LLM) could not be built. The API maps this to HTTP 503."""


def get_settings() -> Settings:
    return _get_settings()


@lru_cache
def _cached_retriever() -> Retriever:
    return build_retriever(_get_settings())


@lru_cache
def _cached_llm() -> LLMClient:
    return build_llm(_get_settings())


def get_retriever() -> Retriever:
    """The process-wide retriever, or ``ServiceUnavailable`` explaining why not."""
    try:
        return _cached_retriever()
    except Exception as exc:  # any build failure: missing index, DB down, stub, ...
        raise ServiceUnavailable(
            f"Retriever unavailable ({type(exc).__name__}: {exc}). "
            "Build the index first (see README), or check STORE_BACKEND/DATABASE_URL."
        ) from exc


def get_retriever_provider() -> Callable[[], Retriever]:
    """A *function* that returns the retriever, rather than the retriever itself.

    Why the indirection: ``no_retrieval`` mode must work without an index, so the
    route only builds the retriever when the request's mode needs it.
    """
    return get_retriever


def get_llm() -> LLMClient:
    try:
        return _cached_llm()
    except Exception as exc:
        raise ServiceUnavailable(f"LLM unavailable: {exc}") from exc


SettingsDep = Annotated[Settings, Depends(get_settings)]
LLMDep = Annotated[LLMClient, Depends(get_llm)]
RetrieverProviderDep = Annotated[Callable[[], Retriever], Depends(get_retriever_provider)]
