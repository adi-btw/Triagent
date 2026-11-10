"""Shared test setup."""

import pytest


@pytest.fixture(autouse=True)
def _isolated_feedback_db(tmp_path, monkeypatch):
    """Every test gets its own feedback database; nothing writes to .cache/."""
    monkeypatch.setenv("FEEDBACK_DB_PATH", str(tmp_path / "feedback.sqlite3"))
