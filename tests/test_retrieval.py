import shutil
from pathlib import Path

import pytest

from app.config import Settings
from app.embeddings.hashing import HashingEmbedder
from app.ingest.pipeline import ingest
from app.retrieval.factory import build_retriever
from app.retrieval.search import SearchRetriever, rrf_fuse
from app.store.base import IndexNotFoundError
from app.store.memory import MemoryStore
from scripts.ingest import main as ingest_main
from scripts.ingest import run as ingest_run

REPO_CORPUS = Path("data/corpus")


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    dst = tmp_path / "corpus"
    shutil.copytree(REPO_CORPUS, dst)
    return dst


@pytest.fixture
def settings(tmp_path: Path, corpus: Path) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        store_backend="memory",
        embedder="hashing",
        corpus_dir=corpus,
        index_path=tmp_path / "index.json",
    )


# ----------------------------------------------------------------------------- ingestion


def test_second_run_embeds_nothing(settings: Settings) -> None:
    first = ingest_run(settings)
    assert first.embedded == first.chunks > 0 and first.unchanged == 0
    second = ingest_run(settings)
    assert (second.embedded, second.unchanged, second.deleted) == (0, first.chunks, 0)


def test_editing_one_section_reembeds_exactly_one(settings: Settings, corpus: Path) -> None:
    ingest_run(settings)
    path = corpus / "runbooks" / "RB-NET-002.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("Restart CoreDNS pods", "Roll CoreDNS pods"),
        encoding="utf-8",
    )
    stats = ingest_run(settings)
    assert stats.embedded == 1 and stats.unchanged == stats.chunks - 1


def test_removed_section_and_document_are_deleted(settings: Settings, corpus: Path) -> None:
    ingest_run(settings)
    (corpus / "policies" / "POL-SEV-001.md").unlink()  # 2 chunks
    path = corpus / "runbooks" / "RB-NET-002.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(text[: text.index("## Mitigation")], encoding="utf-8")  # 1 chunk
    stats = ingest_run(settings)
    assert stats.deleted == 3 and stats.embedded == 0
    store = MemoryStore.load(settings.index_path, "hashing-384", 384)
    assert "POL-SEV-001" not in store.document_ids()
    assert "RB-NET-002#s3" not in store.existing_hashes()


def test_rebuild_reembeds_everything(settings: Settings) -> None:
    first = ingest_run(settings)
    assert ingest_run(settings, rebuild=True).embedded == first.chunks


def test_cli_prints_stats(settings: Settings, capsys: pytest.CaptureFixture[str]) -> None:
    import scripts.ingest as script

    original = script.get_settings
    script.get_settings = lambda: settings  # type: ignore[assignment]
    try:
        assert ingest_main(["--embedder", "hashing"]) == 0
    finally:
        script.get_settings = original
    assert "embedded=" in capsys.readouterr().out


# ----------------------------------------------------------------------------- retrieval


def test_missing_index_error_says_run_ingest(settings: Settings) -> None:
    with pytest.raises(IndexNotFoundError, match="python -m scripts.ingest"):
        build_retriever(settings)


def test_keyword_finds_exact_error_token(settings: Settings) -> None:
    ingest_run(settings)
    hits = build_retriever(settings).retrieve("getaddrinfo EAI_AGAIN", k=3, mode="keyword")
    assert hits[0].doc_id == "RB-NET-002"
    assert hits[0].chunk_id == "RB-NET-002#s1" and hits[0].method == "keyword"


def test_modes_return_k_results_with_method(settings: Settings) -> None:
    ingest_run(settings)
    retriever = build_retriever(settings)
    query = "FATAL: sorry, too many clients already max_connections"
    for mode in ("vector", "keyword", "hybrid"):
        hits = retriever.retrieve(query, k=3, mode=mode)  # type: ignore[arg-type]
        assert 0 < len(hits) <= 3
        assert {h.method for h in hits} == {mode}
    assert len(retriever.retrieve(query)) == settings.top_k  # defaults from settings
    assert retriever.retrieve("   ") == []


def test_rrf_fusion_hand_made_rankings() -> None:
    # vector: a b c ; keyword: c a d
    fused = rrf_fuse([["a", "b", "c"], ["c", "a", "d"]], k=60)
    scores = dict(fused)
    assert scores["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert scores["c"] == pytest.approx(1 / 63 + 1 / 61)
    assert scores["b"] == pytest.approx(1 / 62)
    # a (in both, ranks 1+2) > c (ranks 3+1) > b (only vector #2) > d (only keyword #3)
    assert [i for i, _ in fused] == ["a", "c", "b", "d"]


def test_rrf_ties_broken_by_id() -> None:
    assert [i for i, _ in rrf_fuse([["z", "y"], ["y", "z"]])] == ["y", "z"]


def test_hybrid_scores_are_rrf(tmp_path: Path, corpus: Path) -> None:
    emb = HashingEmbedder()
    store = MemoryStore(emb.name, emb.dim)
    ingest(corpus, store, emb)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    hits = SearchRetriever(store, emb, settings).retrieve("EAI_AGAIN", k=2, mode="hybrid")
    assert hits[0].chunk_id == "RB-NET-002#s1"
    assert hits[0].score == pytest.approx(2 / 61)  # #1 in both lists
