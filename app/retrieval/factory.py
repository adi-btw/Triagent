"""Stub owned by the retrieval workstream; replaced with the real implementation."""

from app.config import Settings
from app.retrieval.base import Retriever


def build_retriever(settings: Settings) -> Retriever:
    raise NotImplementedError("retrieval workstream implements this")
