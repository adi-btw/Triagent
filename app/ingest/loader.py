"""Load the Markdown corpus into (Document, body) pairs.

Each corpus file is Markdown with a YAML front-matter block::

    ---
    doc_id: RB-DB-001
    type: runbook
    title: PostgreSQL connection exhaustion
    services: [orders-db]
    ---
    ## Symptoms
    ...

Why front-matter instead of a separate metadata file: the metadata travels with the
text, so whoever edits a runbook sees (and updates) both in one place.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.schemas import Document

logger = logging.getLogger(__name__)

_FENCE = "---"


class CorpusError(ValueError):
    """A corpus file is malformed. The message always names the offending file, because
    "invalid front-matter" without a path is useless once the corpus has 50 files."""


def normalise_newlines(text: str) -> str:
    """CRLF/CR -> LF. Files edited on Windows would otherwise produce different content
    hashes (and therefore spurious re-embeds) for text that looks identical."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse_document(text: str, source: str) -> tuple[Document, str]:
    """Split one file's text into a validated Document and its Markdown body.

    `source` is only used in error messages.
    """
    lines = normalise_newlines(text).lstrip("﻿").split("\n")
    if lines[0].strip() != _FENCE:
        raise CorpusError(f"{source}: file must start with a '---' front-matter block")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == _FENCE)
    except StopIteration:
        raise CorpusError(f"{source}: front-matter block is never closed with '---'") from None

    try:
        meta: Any = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError as exc:
        raise CorpusError(f"{source}: invalid YAML front-matter: {exc}") from exc
    if not isinstance(meta, dict):
        raise CorpusError(f"{source}: front-matter must be a mapping, got {type(meta).__name__}")

    missing = [key for key in ("doc_id", "type", "title") if key not in meta]
    if missing:
        raise CorpusError(f"{source}: front-matter is missing required key(s): {missing}")

    fields = dict(meta)
    try:
        doc = Document(
            doc_id=str(fields.pop("doc_id")),
            doc_type=fields.pop("type"),
            title=str(fields.pop("title")),
            metadata=fields,  # everything else (services, severity, ...) is free-form
        )
    except ValidationError as exc:
        raise CorpusError(f"{source}: invalid front-matter: {exc}") from exc

    return doc, "\n".join(lines[end + 1 :])


def load_corpus(corpus_dir: Path | str) -> list[tuple[Document, str]]:
    """Load every `*.md` file under `corpus_dir` (recursively), sorted by path.

    Sorting makes ingestion order, and therefore logs and stats, deterministic.
    Duplicate doc_ids are an error: chunk IDs derive from doc_id, so two files with the
    same doc_id would silently overwrite each other's chunks.
    """
    root = Path(corpus_dir)
    if not root.is_dir():
        raise CorpusError(f"{root}: corpus directory does not exist")

    seen: dict[str, Path] = {}
    out: list[tuple[Document, str]] = []
    # Sort on the POSIX string: Path ordering is case-insensitive on Windows only.
    for path in sorted(root.rglob("*.md"), key=lambda p: p.as_posix()):
        doc, body = parse_document(path.read_text(encoding="utf-8"), source=str(path))
        if doc.doc_id in seen:
            raise CorpusError(
                f"{path}: duplicate doc_id {doc.doc_id!r} (also in {seen[doc.doc_id]})"
            )
        if path.stem != doc.doc_id:
            logger.warning("%s: file name does not match doc_id %r", path, doc.doc_id)
        seen[doc.doc_id] = path
        out.append((doc, body))
    return out
