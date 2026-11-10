"""Turn alert-manager webhooks into incident text the triage pipeline can read.

Two payload shapes are accepted:

* **Prometheus Alertmanager** (webhook ``version: "4"``): ``{"status", "groupKey",
  "commonLabels", "commonAnnotations", "alerts": [{"status", "labels", "annotations",
  "startsAt", "fingerprint"}]}``. Grafana's Alertmanager-compatible contact point sends
  the same shape.
* **Generic**: ``{"title", "description", "service"?, "severity"?}``, for anything that can
  POST JSON (a cron job, a CI step, a curl).

Only firing alerts are triaged. A "resolved" notification needs no triage.

**Deduplication.** Alertmanager re-sends a still-firing group every ``repeat_interval``.
Each resend would otherwise be a new LLM call and a new Slack message. ``Deduper``
remembers each alert's fingerprint for a TTL and drops repeats.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

MAX_INCIDENT_CHARS = 7500  # TriageRequest allows 8000


@dataclass(frozen=True)
class Incident:
    title: str
    text: str
    key: str  # stable identity for deduplication


def _fingerprint(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:16]


def _alert_lines(alert: dict[str, Any]) -> list[str]:
    labels = alert.get("labels") or {}
    ann = alert.get("annotations") or {}
    out = []
    for key in ("summary", "description", "message"):
        if ann.get(key):
            out.append(str(ann[key]))
    shown = {k: v for k, v in labels.items() if k not in ("alertname",)}
    if shown:
        out.append("Labels: " + ", ".join(f"{k}={v}" for k, v in sorted(shown.items())))
    if alert.get("startsAt"):
        out.append(f"Started: {alert['startsAt']}")
    return out


def from_alertmanager(payload: dict[str, Any]) -> list[Incident]:
    """One incident per alert group: alerts in a group share a cause by construction."""
    firing = [a for a in payload.get("alerts") or [] if a.get("status", "firing") == "firing"]
    if not firing:
        return []
    common = payload.get("commonLabels") or {}
    names = sorted({a.get("labels", {}).get("alertname", "alert") for a in firing})
    service = common.get("service") or common.get("job") or common.get("app")
    title = ", ".join(names) + (f" on {service}" if service else "")
    lines = [f"Alert firing: {title} ({len(firing)} alert(s))."]
    ca = payload.get("commonAnnotations") or {}
    for key in ("summary", "description"):
        if ca.get(key):
            lines.append(str(ca[key]))
    for i, alert in enumerate(firing[:10], 1):
        lines.append(f"\nAlert {i}: {alert.get('labels', {}).get('alertname', 'alert')}")
        lines += _alert_lines(alert)
    if len(firing) > 10:
        lines.append(f"\n...and {len(firing) - 10} more alerts in this group.")
    ids = sorted(a.get("fingerprint") or _fingerprint(a.get("labels", {})) for a in firing)
    key = "am:" + _fingerprint([payload.get("groupKey"), ids,
                                sorted(a.get("startsAt", "") for a in firing)])
    return [Incident(title=title, text="\n".join(lines)[:MAX_INCIDENT_CHARS], key=key)]


def from_generic(payload: dict[str, Any]) -> list[Incident]:
    title = str(payload.get("title") or "").strip()
    desc = str(payload.get("description") or "").strip()
    if not title and not desc:
        return []
    lines = [title] if title else []
    if payload.get("service"):
        lines.append(f"Service: {payload['service']}")
    if payload.get("severity"):
        lines.append(f"Reported severity: {payload['severity']}")
    if desc:
        lines.append(desc)
    text = "\n".join(lines)[:MAX_INCIDENT_CHARS]
    return [Incident(title=(title or desc)[:150], text=text, key="gen:" + _fingerprint(text))]


def parse(payload: dict[str, Any]) -> list[Incident]:
    """Detect the shape and extract incidents. Raises ``ValueError`` on an unknown shape."""
    if isinstance(payload.get("alerts"), list):
        return from_alertmanager(payload)
    if "title" in payload or "description" in payload:
        return from_generic(payload)
    raise ValueError("expected an Alertmanager webhook (with 'alerts') or "
                     "{'title', 'description'}")


class Deduper:
    """Thread-safe 'seen recently' set with a TTL."""

    def __init__(self, ttl_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl_s = ttl_s
        self._clock = clock
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def first_time(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            self._seen = {k: t for k, t in self._seen.items() if now - t < self.ttl_s}
            if key in self._seen:
                return False
            self._seen[key] = now
            return True
