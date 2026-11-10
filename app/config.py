"""Application settings. Every limit the application (not the model) enforces lives here."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

RetrievalMode = Literal["vector", "keyword", "hybrid"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Storage
    store_backend: Literal["memory", "postgres"] = "memory"
    database_url: str = "postgresql://triage:triage@localhost:5432/triage"
    corpus_dir: Path = Path("data/corpus")
    index_path: Path = Path(".cache/index.json")

    # Embeddings
    embedder: Literal["fastembed", "hashing"] = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # Generation
    llm_provider: Literal["gemini", "fake"] = "gemini"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"
    # Reasoning depth for Gemini 3.x models; None leaves the model's default (slower).
    gemini_thinking_level: Literal["minimal", "low", "medium", "high"] | None = "low"
    llm_temperature: float = 0.0
    llm_timeout_s: float = 120.0
    # Disk cache of LLM answers (app/llm/cache.py). Off for the app; the eval turns it on.
    llm_cache: bool = False
    llm_cache_dir: Path = Path(".cache/llm")

    # Retrieval
    top_k: int = 5
    retrieval_mode: RetrievalMode = "hybrid"  # see eval/results/retrieval-latest.md
    # Docs added to every request's evidence regardless of ranking (see app/retrieval/pinned.py).
    # The severity rubric applies to every incident, so it must not depend on search ranking.
    pinned_doc_ids: list[str] = ["POL-SEV-001"]
    # Second-stage cross-encoder reranking (app/retrieval/rerank.py).
    rerank: bool = False
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    rerank_candidates: int = 20  # first-stage depth handed to the reranker

    # Observability (app/observability.py)
    log_format: Literal["text", "json"] = "text"
    log_level: str = "info"
    otel_enabled: bool = False  # needs opentelemetry-sdk; exporter via standard OTEL_* vars
    # USD per million tokens, for the cost metric. No defaults: a wrong price is worse.
    llm_price_input_per_mtok: float | None = None
    llm_price_output_per_mtok: float | None = None

    # Public demo guardrails (app/demo.py). Off locally; the deployment turns them on.
    demo_mode: bool = False
    demo_requests_per_ip_per_hour: int = 20
    demo_llm_calls_per_day: int = 300
    demo_proxy_hops: int = 1  # trusted proxies in front of the app (X-Forwarded-For)
    demo_cache_dir: Path = Path("data/demo_cache")

    # Agent limits (enforced by code, never by the model)
    agent_max_steps: int = 4
    agent_max_query_rewrites: int = 1
    agent_max_clarifying_questions: int = 1


@lru_cache
def get_settings() -> Settings:
    return Settings()
