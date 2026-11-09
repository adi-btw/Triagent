from typing import Protocol


class Embedder(Protocol):
    """Asymmetric embedder: queries and passages may be encoded differently (BGE uses a
    query instruction prefix). Returned vectors are L2-normalised so dot == cosine."""

    dim: int
    name: str

    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...
