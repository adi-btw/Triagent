from typing import Protocol

from app.config import RetrievalMode
from app.schemas import Evidence


class Retriever(Protocol):
    def retrieve(
        self, query: str, k: int | None = None, mode: RetrievalMode | None = None
    ) -> list[Evidence]:
        """Return up to k chunks, best first. k/mode default to Settings.top_k/retrieval_mode."""
        ...
