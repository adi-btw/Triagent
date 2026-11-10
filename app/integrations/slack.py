"""Slack: render a ``TriageResponse`` as Block Kit, post it, verify inbound requests.

**Model output is escaped.** Slack's mrkdwn treats ``<...>`` as control syntax:
``<!channel>`` pings everyone in the channel and ``<https://x|click>`` hides a link behind
text. A report is model output built from incident text that an attacker may control,
so every model-written string goes through ``escape`` (``& < >`` to entities, as Slack
documents). Mentions and links cannot come from the model. Formatting is ours alone.

**Every status is rendered honestly.** A rejected report (``invalid_output``) is posted
as rejected, with the validator's reasons, and its contents are not shown. This keeps
an unchecked answer out of the channel, where it would look like a real one.

**Signatures.** Slash commands are verified with Slack's v0 scheme: HMAC-SHA256 of
``v0:{timestamp}:{raw body}`` with the app's signing secret, compared in constant time.
Requests older than five minutes are refused to stop replays.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.schemas import TriageResponse

MAX_SECTION = 2900  # Slack's limit is 3000 characters per section text
SIGNATURE_MAX_AGE_S = 300
SEVERITY_EMOJI = {"SEV1": ":red_circle:", "SEV2": ":large_orange_circle:",
                  "SEV3": ":large_yellow_circle:", "SEV4": ":white_circle:"}


def escape(text: str) -> str:
    """Neutralise Slack control sequences in untrusted text."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _clip(text: str, limit: int = MAX_SECTION) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _cites(ids: list[str]) -> str:
    return " ".join(f"`{escape(c)}`" for c in ids)


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": _clip(text)}}


def _context(text: str) -> dict[str, Any]:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": _clip(text)}]}


def format_report(response: TriageResponse, *, title: str) -> dict[str, Any]:
    """A Slack message (``text`` fallback + ``blocks``) for one triage result."""
    title = escape(_clip(title, 150))
    trace = response.trace
    footer = (f"{trace.mode} mode · {escape(trace.model)} · {trace.llm_calls} LLM call(s) · "
              f"{trace.timings_ms.get('total', 0) / 1000:.1f}s")
    report = response.report

    if response.status == "invalid_output":
        reasons = "\n".join(f"• `{v.type}`: {escape(v.detail)}" for v in trace.violations[:8])
        blocks = [
            _section(f":no_entry: *Triage report rejected by the validator*\n*{title}*"),
            _section("The model's report failed citation or safety checks, so it is not "
                     f"shown. Reasons:\n{reasons or '• (none recorded)'}"),
        ]
        return {"text": f"Triage rejected: {title}", "blocks": blocks + [_context(footer)]}

    if response.status == "needs_clarification":
        question = escape(response.clarifying_question or "")
        return {"text": f"Triage needs more information: {title}", "blocks": [
            _section(f":grey_question: *More information needed*\n*{title}*\n{question}"),
            _context(footer)]}

    assert report is not None  # status "ok" always carries a report
    if report.insufficient_evidence:
        missing = "\n".join(f"• {escape(m)}" for m in report.missing_information[:8])
        blocks = [
            _section(f":mag: *Not enough evidence in the runbooks*\n*{title}*\n"
                     f"{escape(report.summary)}"),
        ]
        if missing:
            blocks.append(_section(f"*What would help*\n{missing}"))
        return {"text": f"Triage: insufficient evidence for {title}",
                "blocks": blocks + [_context(footer)]}

    sev = report.severity.value if report.severity else "unrated"
    head = f"{SEVERITY_EMOJI.get(sev, ':white_circle:')} *{sev}* · *{title}*"
    blocks = [_section(f"{head}\n{escape(report.summary)}"
                       + (f"\n_Severity per_ {_cites(report.severity_citations)}"
                          if report.severity_citations else ""))]
    if report.likely_causes:
        blocks.append(_section("*Likely causes*\n" + "\n".join(
            f"• {escape(c.description)} _({c.confidence})_ {_cites(c.citations)}"
            for c in report.likely_causes[:5])))
    if report.next_steps:
        blocks.append(_section("*Next steps*\n" + "\n".join(
            f"{i}. {escape(s.action)} {_cites(s.citations)}"
            for i, s in enumerate(report.next_steps[:6], 1))))
    cited = {c for c in report.severity_citations}
    cited |= {c for x in report.likely_causes for c in x.citations}
    cited |= {c for x in report.next_steps for c in x.citations}
    sources = [f"`{escape(e.chunk_id)}` {escape(e.title)}"
               for e in response.evidence if e.chunk_id in cited]
    if sources:
        blocks.append(_context("Sources: " + " · ".join(sources[:6])))
    blocks.append(_context(footer))
    return {"text": f"{sev}: {title}", "blocks": blocks}


def slash_ack(text: str) -> dict[str, Any]:
    """Immediate reply to a slash command (Slack waits at most 3 seconds)."""
    return {"response_type": "ephemeral", "text": f"Triaging: {escape(_clip(text, 200))}…"}


# --------------------------------------------------------------------------- delivery


def is_slack_response_url(url: str) -> bool:
    """Slash-command ``response_url`` must be Slack's own host.

    The URL arrives in the request body. Even though the request is signed, we refuse to
    POST anywhere else, so a leaked signing secret can't turn the server into a
    proxy for internal addresses (SSRF).
    """
    u = urlparse(url)
    return u.scheme == "https" and u.hostname == "hooks.slack.com"


class SlackNotifier:
    """Posts messages to a Slack incoming webhook or a slash-command ``response_url``."""

    def __init__(self, webhook_url: str | None, client: httpx.Client | None = None) -> None:
        self.webhook_url = webhook_url
        self._client = client or httpx.Client(timeout=10.0)

    def post(self, message: dict[str, Any], url: str | None = None) -> bool:
        target = url or self.webhook_url
        if not target:
            return False
        resp = self._client.post(target, json=message)
        resp.raise_for_status()
        return True


# --------------------------------------------------------------------------- signatures


def sign(secret: str, timestamp: str, body: bytes) -> str:
    base = b"v0:" + timestamp.encode() + b":" + body
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


def verify_signature(secret: str, timestamp: str | None, body: bytes,
                     signature: str | None, *, now: float | None = None) -> bool:
    if not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs((time.time() if now is None else now) - ts) > SIGNATURE_MAX_AGE_S:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), signature)
