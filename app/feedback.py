"""Reviewer feedback on triage reports, stored for the eval loop.

    POST /triage            -> response carries ``triage_id``; the triage is recorded
    POST /feedback          -> {triage_id, rating, correct_severity?, should_abstain?, ...}
    python -m eval.feedback report | export-cases

Feedback is only useful if it points at exactly what was shown, so the **server** records
each triage when it answers: the incident, mode, model, prompt versions, the report and
the ids it cited. ``POST /feedback`` names the triage by id and adds the reviewer's
verdict. A client can't attach feedback to a report it invents, and the feedback can't
claim the model said something it didn't.

**Storage: SQLite** (stdlib, one file, transactional, queryable with any SQL tool). Each
operation opens its own connection, so it is safe from FastAPI's thread pool. WAL mode
lets readers and the writer work side by side. Volume here is one row per human request,
so a server database would add nothing. With several replicas, this moves to Postgres
behind the same three methods.

**Bounded.** At most ``FEEDBACK_MAX_TRIAGES`` triages are kept. Past that, the oldest
triages that received no feedback are dropped first, so a public demo can't fill the
disk and nothing a reviewer labelled is lost.

**Privacy.** The incident text is stored. That's what lets a correction become an eval
case. Set ``FEEDBACK_ENABLED=false`` where incidents must not be retained.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas import Severity, TriageRequest, TriageResponse

SCHEMA = """
CREATE TABLE IF NOT EXISTS triages (
    triage_id     TEXT PRIMARY KEY,
    created_at    REAL NOT NULL,
    mode          TEXT NOT NULL,
    model         TEXT NOT NULL,
    status        TEXT NOT NULL,
    severity      TEXT,
    abstained     INTEGER NOT NULL,
    incident      TEXT NOT NULL,
    clarification TEXT,
    cited_ids     TEXT NOT NULL,   -- JSON list
    prompt_versions TEXT NOT NULL, -- JSON list
    report        TEXT             -- JSON TriageReport, null when there is none
);
CREATE TABLE IF NOT EXISTS feedback (
    triage_id        TEXT PRIMARY KEY REFERENCES triages(triage_id) ON DELETE CASCADE,
    created_at       REAL NOT NULL,
    updated_at       REAL NOT NULL,
    rating           TEXT NOT NULL,
    correct_severity TEXT,
    should_abstain   INTEGER,
    wrong_citations  TEXT NOT NULL, -- JSON list of chunk ids the reviewer flagged
    comment          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS triages_created ON triages(created_at);
"""


class FeedbackIn(BaseModel):
    triage_id: str = Field(min_length=8, max_length=64)
    rating: Literal["up", "down"]
    # Corrections, all optional: what the right answer was, in eval-label terms.
    correct_severity: Severity | None = None
    should_abstain: bool | None = None
    wrong_citations: list[str] = Field(default_factory=list, max_length=20)
    comment: str = Field(default="", max_length=1000)


class UnknownTriage(LookupError):
    """``triage_id`` was never recorded here, or was evicted."""


def cited_ids(response: TriageResponse) -> list[str]:
    r = response.report
    if r is None:
        return []
    ids = list(r.severity_citations)
    for c in r.likely_causes:
        ids += c.citations
    for s in r.next_steps:
        ids += s.citations
    return sorted(set(ids))


def prompt_versions(response: TriageResponse) -> list[str]:
    out = set()
    for step in response.trace.steps:
        for key in ("prompt_version", "agent_prompt_version"):
            if step.detail.get(key):
                out.add(str(step.detail[key]))
    return sorted(out)


class FeedbackStore:
    def __init__(self, path: Path, *, max_triages: int = 20_000) -> None:
        self.path = Path(path)
        self.max_triages = max_triages
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:  # commit on success, roll back on error
                yield db
        finally:
            db.close()

    # ------------------------------------------------------------------ writes

    def record_triage(self, request: TriageRequest, response: TriageResponse) -> str:
        """Store what was shown and return its id (also set on ``response``)."""
        triage_id = uuid.uuid4().hex
        r = response.report
        row = (
            triage_id, time.time(), request.mode, response.trace.model, response.status,
            r.severity.value if r and r.severity else None,
            int(bool(r and r.insufficient_evidence)), request.incident, request.clarification,
            json.dumps(cited_ids(response)), json.dumps(prompt_versions(response)),
            r.model_dump_json() if r else None,
        )
        with self._connect() as db:
            db.execute("INSERT INTO triages VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", row)
            self._evict(db)
        response.triage_id = triage_id
        return triage_id

    def _evict(self, db: sqlite3.Connection) -> None:
        (n,) = db.execute("SELECT COUNT(*) FROM triages").fetchone()
        excess = n - self.max_triages
        if excess > 0:
            db.execute(
                "DELETE FROM triages WHERE triage_id IN (SELECT t.triage_id FROM triages t "
                "LEFT JOIN feedback f USING (triage_id) WHERE f.triage_id IS NULL "
                "ORDER BY t.created_at LIMIT ?)", (excess,))

    def add_feedback(self, fb: FeedbackIn) -> dict[str, Any]:
        """Insert, or replace the reviewer's earlier verdict on the same triage."""
        now = time.time()
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM triages WHERE triage_id=?",
                              (fb.triage_id,)).fetchone():
                raise UnknownTriage(fb.triage_id)
            db.execute(
                "INSERT INTO feedback VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(triage_id) DO UPDATE "
                "SET updated_at=excluded.updated_at, rating=excluded.rating, "
                "correct_severity=excluded.correct_severity, "
                "should_abstain=excluded.should_abstain, "
                "wrong_citations=excluded.wrong_citations, comment=excluded.comment",
                (fb.triage_id, now, now, fb.rating,
                 fb.correct_severity.value if fb.correct_severity else None,
                 None if fb.should_abstain is None else int(fb.should_abstain),
                 json.dumps(sorted(set(fb.wrong_citations))), fb.comment.strip()))
        return {"triage_id": fb.triage_id, "rating": fb.rating}

    # ------------------------------------------------------------------ reads

    def rows(self) -> list[dict[str, Any]]:
        """Every triage that received feedback, joined with it (for the eval tools)."""
        with self._connect() as db:
            cur = db.execute(
                "SELECT t.*, f.rating, f.correct_severity, f.should_abstain, f.wrong_citations, "
                "f.comment, f.updated_at AS feedback_at FROM triages t "
                "JOIN feedback f USING (triage_id) ORDER BY f.updated_at")
            out = []
            for row in cur.fetchall():
                d = dict(row)
                for key in ("cited_ids", "prompt_versions", "wrong_citations"):
                    d[key] = json.loads(d[key])
                d["report"] = json.loads(d["report"]) if d["report"] else None
                d["abstained"] = bool(d["abstained"])
                if d["should_abstain"] is not None:
                    d["should_abstain"] = bool(d["should_abstain"])
                out.append(d)
            return out

    def counts(self) -> dict[str, int]:
        with self._connect() as db:
            (t,) = db.execute("SELECT COUNT(*) FROM triages").fetchone()
            (f,) = db.execute("SELECT COUNT(*) FROM feedback").fetchone()
        return {"triages": t, "feedback": f}
