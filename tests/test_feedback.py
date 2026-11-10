"""Feedback store, POST /feedback, and the eval loop (report + candidate cases)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.deps import get_llm, get_retriever_provider, get_settings
from app.feedback import FeedbackIn, FeedbackStore, UnknownTriage
from app.main import app
from app.schemas import Trace, TriageReport, TriageRequest, TriageResponse
from eval import feedback as fb_eval
from eval.cases import EvalCase
from tests.fakes import DemoLLM, FakeRetriever, valid_report

INCIDENT = "checkout-api returning 500s: FATAL: sorry, too many clients already"


def response(report: dict | None = None, status: str = "ok") -> TriageResponse:
    return TriageResponse(status=status, report=TriageReport.model_validate(report)
                          if report else None,
                          trace=Trace(mode="rag", model="m"))


@pytest.fixture
def store(tmp_path):
    return FeedbackStore(tmp_path / "fb.sqlite3", max_triages=3)


def record(store, incident=INCIDENT, report=None, **req):
    resp = response(report or valid_report())
    return store.record_triage(TriageRequest(incident=incident, **req), resp), resp


# --------------------------------------------------------------------------- store


def test_record_sets_id_and_feedback_upserts(store):
    tid, resp = record(store)
    assert resp.triage_id == tid
    store.add_feedback(FeedbackIn(triage_id=tid, rating="up"))
    store.add_feedback(FeedbackIn(triage_id=tid, rating="down", correct_severity="SEV1",
                                  wrong_citations=["RB-DB-001#s1", "RB-DB-001#s1"]))
    [row] = store.rows()
    assert row["rating"] == "down" and row["correct_severity"] == "SEV1"
    assert row["wrong_citations"] == ["RB-DB-001#s1"]
    assert row["severity"] == "SEV2" and "RB-DB-001#s3" in row["cited_ids"]
    assert store.counts() == {"triages": 1, "feedback": 1}


def test_unknown_triage_is_refused(store):
    with pytest.raises(UnknownTriage):
        store.add_feedback(FeedbackIn(triage_id="deadbeef00", rating="up"))


def test_eviction_drops_oldest_unreviewed_first(store):
    reviewed, _ = record(store, incident=INCIDENT + " first")
    store.add_feedback(FeedbackIn(triage_id=reviewed, rating="up"))
    for i in range(4):
        record(store, incident=f"{INCIDENT} {i}")
    assert store.counts()["triages"] == 3
    assert [r["triage_id"] for r in store.rows()] == [reviewed]  # labelled data survives


# --------------------------------------------------------------------------- API


@pytest.fixture
def client():
    settings = Settings(_env_file=None, llm_provider="fake")
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_retriever_provider] = lambda: lambda: FakeRetriever()
    app.dependency_overrides[get_llm] = DemoLLM
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_triage_then_feedback_round_trip(client):
    body = client.post("/triage", json={"incident": INCIDENT}).json()
    tid = body["triage_id"]
    assert tid
    r = client.post("/feedback", json={"triage_id": tid, "rating": "down",
                                       "correct_severity": "SEV1", "comment": "full outage"})
    assert r.status_code == 201 and r.json() == {"triage_id": tid, "rating": "down"}


def test_streamed_result_carries_a_triage_id(client):
    with client.stream("POST", "/triage/stream", json={"incident": INCIDENT}) as r:
        last = [ln for ln in r.iter_lines() if ln.startswith("data:")][-1]
    assert json.loads(last[5:])["response"]["triage_id"]


def test_feedback_for_unknown_triage_is_404(client):
    r = client.post("/feedback", json={"triage_id": "0123456789ab", "rating": "up"})
    assert r.status_code == 404


def test_feedback_validation(client):
    tid = client.post("/triage", json={"incident": INCIDENT}).json()["triage_id"]
    assert client.post("/feedback", json={"triage_id": tid, "rating": "meh"}).status_code == 422
    assert client.post("/feedback", json={"triage_id": tid, "rating": "down",
                                          "comment": "x" * 1001}).status_code == 422


def test_feedback_can_be_disabled(client):
    s = Settings(_env_file=None, llm_provider="fake", feedback_enabled=False)
    app.dependency_overrides[get_settings] = lambda: s
    body = client.post("/triage", json={"incident": INCIDENT}).json()
    assert body["triage_id"] is None
    assert client.post("/feedback", json={"triage_id": "0123456789ab",
                                          "rating": "up"}).status_code == 503


# --------------------------------------------------------------------------- eval loop


def reviewed(store, incident, report, **feedback):
    tid, _ = record(store, incident=incident, report=report)
    store.add_feedback(FeedbackIn(triage_id=tid, **feedback))


def test_report_counts_corrections(tmp_path):
    store = FeedbackStore(tmp_path / "f.sqlite3")
    reviewed(store, INCIDENT + " a", valid_report(), rating="up")
    reviewed(store, INCIDENT + " b", valid_report(), rating="down", correct_severity="SEV1",
             wrong_citations=["RB-DB-001#s1"])
    reviewed(store, INCIDENT + " c", valid_report(), rating="down", should_abstain=True)
    reviewed(store, INCIDENT + " d", valid_report(), rating="down")
    s = fb_eval.summarize(store.rows())
    assert (s["n"], s["up"], s["under_rated"], s["over_rated"]) == (4, 1, 1, 0)
    assert len(s["missed_abstain"]) == 1 and s["needs_labelling"] == 1
    md = fb_eval.render(s, store.counts())
    assert "| SEV2 | SEV1 | 1 |" in md and "`RB-DB-001#s1`" in md and "25% (1/4)" in md


def test_export_turns_feedback_into_valid_cases(tmp_path):
    store = FeedbackStore(tmp_path / "f.sqlite3")
    reviewed(store, INCIDENT + " up", valid_report(), rating="up")
    reviewed(store, INCIDENT + " sev", valid_report(), rating="down", correct_severity="SEV1",
             wrong_citations=["INC-2025-014#s2"])
    reviewed(store, INCIDENT + " abstain", valid_report(), rating="down", should_abstain=True)
    reviewed(store, INCIDENT + " vague", valid_report(), rating="down")  # no label
    reviewed(store, "an incident already in the eval set", valid_report(), rating="up")
    existing = [{"id": "case-032", "incident": "An incident  already in the EVAL set"}]
    cases, stats = fb_eval.export_cases(store.rows(), existing)
    assert stats == {"exported": 3, "no_label": 1, "already_in_eval_set": 1}
    assert [c["id"] for c in cases] == ["case-033", "case-034", "case-035"]
    for c in cases:
        EvalCase.model_validate(c)
    up, sev, abstain = cases
    assert up["expected_severity"] == "SEV2" and up["category"] == "answerable"
    assert sev["expected_severity"] == "SEV1" and "INC-2025-014#s2" not in sev[
        "expected_chunk_ids"]
    assert abstain["should_abstain"] and abstain["category"] == "insufficient_evidence"
    assert abstain["expected_chunk_ids"] == ["POL-SEV-001#s1"]


def test_last_verdict_wins_for_the_same_incident(tmp_path):
    store = FeedbackStore(tmp_path / "f.sqlite3")
    reviewed(store, INCIDENT, valid_report(), rating="up")
    reviewed(store, INCIDENT, valid_report(), rating="down", correct_severity="SEV3")
    cases, _ = fb_eval.export_cases(store.rows(), [])
    assert [c["expected_severity"] for c in cases] == ["SEV3"]


def test_cli_end_to_end(tmp_path):
    db = tmp_path / "f.sqlite3"
    reviewed(FeedbackStore(db), INCIDENT, valid_report(), rating="up")
    cases_file = tmp_path / "cases.jsonl"
    cases_file.write_text("", encoding="utf-8")
    out = tmp_path / "cand.jsonl"
    assert fb_eval.main(["--db", str(db), "export-cases", "--out", str(out),
                         "--cases", str(cases_file)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["id"] == "case-001"
    rep = tmp_path / "r.md"
    assert fb_eval.main(["--db", str(db), "report", "--out", str(rep)]) == 0
    assert "100% (1/1)" in rep.read_text(encoding="utf-8")
