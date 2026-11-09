"""Load and validate the labelled eval set (``data/eval/cases.jsonl``).

Why validate at load time: a typo in a label (``"SEV 2"``, a chunk whose doc is not in
``expected_doc_ids``, an ambiguous case with no scripted clarification) would not crash
the harness; it would silently produce a wrong score. Failing loudly here is cheaper
than discovering a bad label after paying for a full LLM run.

The hashes (``sha256_file`` / ``sha256_dir``) go into every run's metadata, so a result
can always be tied to the exact labels and corpus that produced it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas import Severity

DEFAULT_CASES_PATH = Path("data/eval/cases.jsonl")

Category = Literal["answerable", "insufficient_evidence", "ambiguous"]
CATEGORIES: tuple[Category, ...] = ("answerable", "insufficient_evidence", "ambiguous")


class EvalCase(BaseModel):
    """One labelled incident. Field meanings: ``data/eval/README.md``."""

    id: str = Field(pattern=r"^case-\d{3}$")
    category: Category
    incident: str = Field(min_length=10, max_length=8000)  # same limits as TriageRequest
    expected_severity: Severity | None
    expected_doc_ids: list[str]
    expected_chunk_ids: list[str]
    should_abstain: bool
    clarification: str | None = None
    notes: str = ""

    @model_validator(mode="after")
    def _labels_are_consistent(self) -> EvalCase:
        docs = set(self.expected_doc_ids)
        for cid in self.expected_chunk_ids:
            if "#" not in cid:
                raise ValueError(f"{self.id}: chunk id {cid!r} has no '#s<n>' part")
            if cid.split("#", 1)[0] not in docs:
                raise ValueError(
                    f"{self.id}: chunk {cid!r} belongs to a doc not in expected_doc_ids"
                )
        if self.category == "ambiguous" and not self.clarification:
            raise ValueError(f"{self.id}: ambiguous cases need a scripted clarification")
        if self.category != "ambiguous" and self.clarification is not None:
            raise ValueError(f"{self.id}: only ambiguous cases may carry a clarification")
        if (self.category == "insufficient_evidence") != self.should_abstain:
            raise ValueError(
                f"{self.id}: should_abstain must be true exactly for insufficient_evidence cases"
            )
        return self


def load_cases(
    path: Path = DEFAULT_CASES_PATH,
    *,
    ids: list[str] | None = None,
    limit: int | None = None,
) -> list[EvalCase]:
    """Parse every non-blank line of ``path`` into an ``EvalCase``.

    ``ids`` keeps only those case ids (in file order; unknown ids raise, so a typo in
    ``--cases`` is not mistaken for "ran zero cases"). ``limit`` keeps the first N after
    filtering. Duplicate ids raise.
    """
    cases: list[EvalCase] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        if not line.strip():
            continue
        try:
            cases.append(EvalCase.model_validate(json.loads(line)))
        except Exception as exc:
            raise ValueError(f"{path}:{lineno}: invalid case: {exc}") from exc

    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            raise ValueError(f"{path}: duplicate case id {case.id}")
        seen.add(case.id)

    if ids:
        unknown = sorted(set(ids) - seen)
        if unknown:
            raise ValueError(f"unknown case ids: {', '.join(unknown)}")
        wanted = set(ids)
        cases = [c for c in cases if c.id in wanted]
    if limit is not None:
        cases = cases[:limit]
    return cases


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_dir(root: Path, pattern: str = "*.md") -> str:
    """Hash of every matching file's relative path and bytes, in sorted order.

    Including the path means renaming a doc changes the hash; sorting makes the hash
    independent of filesystem listing order (which differs between Windows and Linux).
    Line endings are hashed as stored, which is LF in this repo (.gitattributes).
    """
    digest = hashlib.sha256()
    for path in sorted(root.rglob(pattern), key=lambda p: p.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()
