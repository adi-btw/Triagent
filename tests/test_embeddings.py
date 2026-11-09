import numpy as np

from app.config import Settings
from app.embeddings.factory import build_embedder
from app.embeddings.fastembed_embedder import l2_normalise
from app.embeddings.hashing import HashingEmbedder
from app.retrieval.tokenizer import tokenize


def test_hashing_is_deterministic_and_normalised() -> None:
    a, b = HashingEmbedder(), HashingEmbedder()
    vec = a.embed_query("getaddrinfo EAI_AGAIN after CoreDNS restart")
    assert vec == b.embed_passages(["getaddrinfo EAI_AGAIN after CoreDNS restart"])[0]
    assert len(vec) == 384
    assert np.isclose(np.linalg.norm(vec), 1.0)


def test_hashing_prefers_token_overlap() -> None:
    emb = HashingEmbedder()
    q = np.array(emb.embed_query("too many clients max_connections"))
    near, far = (
        np.array(v)
        for v in emb.embed_passages(
            ["sorry, too many clients already; check max_connections", "restart CoreDNS pods"]
        )
    )
    assert q @ near > q @ far


def test_hashing_empty_text_is_zero_vector() -> None:
    assert not any(HashingEmbedder(dim=8).embed_query("the of and"))


def test_factory_builds_hashing() -> None:
    emb = build_embedder(Settings(embedder="hashing", embedding_dim=64))
    assert emb.dim == 64 and emb.name == "hashing-64"


def test_l2_normalise_handles_zero_rows() -> None:
    out = l2_normalise(np.array([[3.0, 4.0], [0.0, 0.0]]))
    assert np.allclose(out, [[0.6, 0.8], [0.0, 0.0]])


def test_tokenizer_keeps_identifiers() -> None:
    tokens = tokenize("ERROR pool.acquire EAI_AGAIN 53300 max_connections=200 v2.31.0.")
    for t in [
        "pool.acquire",
        "pool",
        "acquire",
        "eai_again",
        "53300",
        "max_connections",
        "200",
        "v2.31.0",
    ]:
        assert t in tokens
    assert "eai" not in tokens  # underscore is not a split point
