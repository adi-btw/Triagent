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
    gemini_model: str = "gemini-2.5-flash"
    llm_temperature: float = 0.0
    llm_timeout_s: float = 60.0

    # Retrieval
    top_k: int = 5
    retrieval_mode: RetrievalMode = "vector"

    # Agent limits (enforced by code, never by the model)
    agent_max_steps: int = 4
    agent_max_query_rewrites: int = 1
    agent_max_clarifying_questions: int = 1


@lru_cache
def get_settings() -> Settings:
    return Settings()
