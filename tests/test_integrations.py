"""Alert webhook, Slack formatting, slash-command signatures. Fakes only, no network."""

from __future__ import annotations

import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.deps import get_llm, get_retriever_provider, get_settings
from app.integrations import alerts, routes, slack
from app.main import app
from app.schemas import TriageResponse
from tests.fakes import DemoLLM, FakeRetriever, ScriptedLLM, valid_report

TOKEN = "t0ken"
SECRET = "s1gning"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

ALERTMANAGER = {
    "version": "4", "status": "firing", "groupKey": "{}:{alertname=\"PgConnExhausted\"}",
    "commonLabels": {"alertname": "PgConnExhausted", "service": "checkout-api"},
    "commonAnnotations": {"summary": "orders-db connections at 100%"},
    "alerts": [
        {"status": "firing", "fingerprint": "abc",
         "labels": {"alertname": "PgConnExhausted", "service": "checkout-api", "pod": "p1"},
         "annotations": {"description": "FATAL: sorry, too many clients already"},
         "startsAt": "2026-11-10T04:00:00Z"},
        {"status": "resolved", "fingerprint": "old",
         "labels": {"alertname": "DiskFull"}, "startsAt": "2026-11-09T01:00:00Z"},
    ],
}


class RecordingNotifier(slack.SlackNotifier):
    def __init__(self, fail: bool = False) -> None:
        super().__init__("https://hooks.slack.com/services/T/B/X")
        self.sent: list[tuple[dict, str | None]] = []
        self.fail = fail

    def post(self, message, url=None):
        if self.fail:
            raise RuntimeError("slack is down")
        self.sent.append((message, url))
        return True


@pytest.fixture
def notifier():
    return RecordingNotifier()


@pytest.fixture
def client(notifier):
    settings = Settings(_env_file=None, llm_provider="fake", webhook_token=TOKEN,
                        slack_signing_secret=SECRET)
    routes.reset_state()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_retriever_provider] = lambda: lambda: FakeRetriever()
    app.dependency_overrides[get_llm] = DemoLLM
    app.dependency_overrides[routes.get_notifier] = lambda: notifier
    yield TestClient(app)
    app.dependency_overrides.clear()
    routes.reset_state()


def configure(**kw):
    s = Settings(_env_file=None, llm_provider="fake", **kw)
    app.dependency_overrides[get_settings] = lambda: s


# --------------------------------------------------------------------------- parsing


def test_alertmanager_payload_becomes_one_incident_of_firing_alerts():
    [inc] = alerts.parse(ALERTMANAGER)
    assert inc.title == "PgConnExhausted on checkout-api"
    assert "too many clients" in inc.text and "pod=p1" in inc.text
    assert "DiskFull" not in inc.text  # resolved alerts are not triaged
    assert alerts.parse(ALERTMANAGER)[0].key == inc.key  # stable identity


def test_resolved_only_payload_needs_no_triage():
    assert alerts.parse({"alerts": [{"status": "resolved", "labels": {}}]}) == []


def test_generic_payload_and_unknown_shape():
    [inc] = alerts.parse({"title": "Checkout down", "description": "500s", "service": "c"})
    assert inc.title == "Checkout down" and "Service: c" in inc.text
    with pytest.raises(ValueError):
        alerts.parse({"hello": "world"})


def test_deduper_expires():
    now = [0.0]
    d = alerts.Deduper(10, clock=lambda: now[0])
    assert d.first_time("k") and not d.first_time("k")
    now[0] = 11
    assert d.first_time("k")


# --------------------------------------------------------------------------- formatting


def response_for(report: dict | None, status: str = "ok", **extra) -> TriageResponse:
    from app.schemas import Trace
    return TriageResponse(status=status, report=report, trace=Trace(mode="rag", model="m"),
                          **extra)


def all_text(msg: dict) -> str:
    return json.dumps(msg)


def test_model_output_cannot_ping_or_hide_links():
    r = response_for(valid_report(summary="<!channel> see <https://evil.example|runbook> & go"))
    text = all_text(slack.format_report(r, title="<@U123> title"))
    assert "<!channel>" not in text and "<https://evil" not in text and "<@U123>" not in text
    assert "&lt;!channel&gt;" in text and "&amp; go" in text


def test_ok_report_shows_severity_causes_steps_and_citations():
    msg = slack.format_report(response_for(valid_report()), title="PgConnExhausted")
    text = all_text(msg)
    assert msg["text"] == "SEV2: PgConnExhausted"
    assert "Likely causes" in text and "Next steps" in text and "`RB-DB-001#s3`" in text


def test_rejected_report_is_not_shown():
    from app.schemas import Trace, Violation
    trace = Trace(mode="rag", model="m",
                  violations=[Violation(type="unknown_citation", detail="AI-455")])
    r = TriageResponse(status="invalid_output", report=valid_report(summary="SECRET-CONTENT"),
                       trace=trace)
    text = all_text(slack.format_report(r, title="x"))
    assert "rejected" in text and "unknown_citation" in text
    assert "SECRET-CONTENT" not in text


def test_insufficient_evidence_and_clarification():
    r = response_for(valid_report(insufficient_evidence=True, severity=None,
                                  missing_information=["which region"]))
    assert "Not enough evidence" in all_text(slack.format_report(r, title="x"))
    q = response_for(None, status="needs_clarification", clarifying_question="Which service?")
    assert "Which service?" in all_text(slack.format_report(q, title="x"))


def test_long_text_is_clipped_to_slack_limits():
    r = response_for(valid_report(summary="x" * 5000))
    for block in slack.format_report(r, title="t")["blocks"]:
        if block["type"] == "section":
            assert len(block["text"]["text"]) <= 3000


# --------------------------------------------------------------------------- webhook API


def test_webhook_is_off_without_a_token(client):
    configure()
    assert client.post("/webhooks/alert", json=ALERTMANAGER).status_code == 503


def test_webhook_rejects_a_wrong_token(client):
    r = client.post("/webhooks/alert", json=ALERTMANAGER, headers={"Authorization": "Bearer no"})
    assert r.status_code == 401


def test_webhook_triages_in_background_and_posts_to_slack(client, notifier):
    r = client.post("/webhooks/alert", json=ALERTMANAGER, headers=AUTH)
    assert r.status_code == 202
    assert r.json()["accepted"][0]["title"] == "PgConnExhausted on checkout-api"
    [(msg, url)] = notifier.sent  # TestClient runs background tasks before returning
    assert url is None and "PgConnExhausted" in msg["text"]


def test_resends_are_deduplicated(client, notifier):
    client.post("/webhooks/alert", json=ALERTMANAGER, headers=AUTH)
    r = client.post("/webhooks/alert", json=ALERTMANAGER, headers=AUTH)
    assert r.json() == {"accepted": [], "duplicates": 1}
    assert len(notifier.sent) == 1


def test_wait_returns_the_triage_response(client):
    r = client.post("/webhooks/alert?wait=true", json={"title": "Checkout 500s",
                                                       "description": "too many clients"},
                    headers=AUTH)
    assert r.status_code == 200
    [res] = r.json()["results"]
    assert res["posted_to_slack"] is True and res["response"]["status"] == "ok"


def test_bad_payload_is_400(client):
    assert client.post("/webhooks/alert", content=b"not json", headers=AUTH).status_code == 400
    assert client.post("/webhooks/alert", json={"x": 1}, headers=AUTH).status_code == 400


def test_alert_storm_is_rate_limited(client):
    configure(webhook_token=TOKEN, integration_triages_per_hour=1)
    ok = client.post("/webhooks/alert", json={"title": "one", "description": "a"}, headers=AUTH)
    assert ok.status_code == 202
    r = client.post("/webhooks/alert", json={"title": "two", "description": "b"}, headers=AUTH)
    assert r.status_code == 429 and r.headers["Retry-After"]


def test_provider_failure_is_reported_to_the_channel(client, notifier):
    app.dependency_overrides[get_llm] = lambda: ScriptedLLM([])  # raises: script exhausted
    client.post("/webhooks/alert", json=ALERTMANAGER, headers=AUTH)
    [(msg, _)] = notifier.sent
    assert msg["text"].startswith("Triage failed")


def test_slack_outage_does_not_break_the_webhook(client):
    app.dependency_overrides[routes.get_notifier] = lambda: RecordingNotifier(fail=True)
    assert client.post("/webhooks/alert", json=ALERTMANAGER, headers=AUTH).status_code == 202


def test_health_reports_integrations_without_secrets(client):
    body = client.get("/health").json()
    assert body["integrations"] == {"alert_webhook": True, "slack_delivery": False,
                                    "slack_commands": True}
    assert TOKEN not in json.dumps(body) and SECRET not in json.dumps(body)


# --------------------------------------------------------------------------- slash command


def signed(body: bytes, ts: int | None = None, secret: str = SECRET) -> dict:
    ts_s = str(ts if ts is not None else int(time.time()))
    return {"X-Slack-Request-Timestamp": ts_s, "X-Slack-Signature": slack.sign(secret, ts_s, body),
            "Content-Type": "application/x-www-form-urlencoded"}


def slash_body(text: str, url: str = "https://hooks.slack.com/commands/T/1/abc") -> bytes:
    return urlencode({"command": "/triage", "text": text, "response_url": url}).encode()


def test_signature_check():
    body, now = b"a=1", 1_700_000_000
    sig = slack.sign(SECRET, str(now), body)
    assert slack.verify_signature(SECRET, str(now), body, sig, now=now)
    assert not slack.verify_signature(SECRET, str(now), b"a=2", sig, now=now)  # tampered
    assert not slack.verify_signature("other", str(now), body, sig, now=now)
    assert not slack.verify_signature(SECRET, str(now), body, sig, now=now + 301)  # replay
    assert not slack.verify_signature(SECRET, None, body, sig)


def test_slash_command_acks_then_replies_in_channel(client, notifier):
    body = slash_body("checkout-api 500s: FATAL: sorry, too many clients already")
    r = client.post("/slack/commands", content=body, headers=signed(body))
    assert r.status_code == 200 and r.json()["response_type"] == "ephemeral"
    [(msg, url)] = notifier.sent
    assert url == "https://hooks.slack.com/commands/T/1/abc"
    assert msg["response_type"] == "in_channel" and msg["replace_original"] is True


def test_slash_command_rejects_unsigned_and_stale(client, notifier):
    body = slash_body("checkout-api 500s everywhere")
    assert client.post("/slack/commands", content=body,
                       headers=signed(body, secret="wrong")).status_code == 401
    assert client.post("/slack/commands", content=body,
                       headers=signed(body, ts=int(time.time()) - 600)).status_code == 401
    assert notifier.sent == []


def test_slash_command_never_posts_outside_slack(client, notifier):
    body = slash_body("checkout-api 500s everywhere", url="http://169.254.169.254/latest")
    assert client.post("/slack/commands", content=body, headers=signed(body)).status_code == 400
    assert notifier.sent == []


def test_slash_command_usage_on_short_text(client, notifier):
    body = slash_body("help")
    r = client.post("/slack/commands", content=body, headers=signed(body))
    assert "Usage" in r.json()["text"] and notifier.sent == []
