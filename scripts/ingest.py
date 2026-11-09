"""Build or update the retrieval index.

    python -m scripts.ingest [--backend memory|postgres] [--embedder fastembed|hashing]
                             [--corpus data/corpus] [--rebuild]

Defaults come from Settings (.env). Safe to re-run: only changed chunks are re-embedded.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from app.config import Settings, get_settings
from app.embeddings.factory import build_embedder
from app.ingest.pipeline import IngestStats, ingest
from app.store.base import IndexMismatchError
from app.store.factory import build_store


def run(settings: Settings, *, rebuild: bool = False) -> IngestStats:
    """Programmatic entry point (used by tests and the eval harness)."""
    embedder = build_embedder(settings)
    if rebuild and settings.store_backend == "memory" and settings.index_path.exists():
        settings.index_path.unlink()  # may belong to another embedder: don't load it
    store = build_store(settings, embedder, create=True)
    if rebuild:
        store.clear()
    return ingest(settings.corpus_dir, store, embedder)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--backend", choices=["memory", "postgres"])
    parser.add_argument("--embedder", choices=["fastembed", "hashing"])
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--rebuild", action="store_true", help="drop the index and re-embed all")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    overrides = {
        key: value
        for key, value in {
            "store_backend": args.backend,
            "embedder": args.embedder,
            "corpus_dir": args.corpus,
        }.items()
        if value is not None
    }
    settings = get_settings().model_copy(update=overrides)

    start = time.perf_counter()
    try:
        stats = run(settings, rebuild=args.rebuild)
    except IndexMismatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    elapsed = time.perf_counter() - start
    where = settings.index_path if settings.store_backend == "memory" else "postgres"
    print(f"{stats}  ({elapsed:.1f}s, {settings.embedder}, -> {where})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
