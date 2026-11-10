"""Output guards: deterministic checks that hold even if the model is fully compromised.

The citation allow-list (``app.triage.validate``) stops a model from citing passages it
was never shown. It cannot stop a *poisoned* passage: a runbook or incident that an
attacker edited, which is retrieved legitimately and so is on the allow-list. The red-team
suite (``eval/redteam.py``) replays attacks through a model that obeys every injected
instruction, and these guards close the gaps it found:

* ``severity_not_from_policy``: a severity must cite the severity policy. A poisoned
  incident write-up saying "per policy this is SEV4" cannot justify a downgrade on its
  own, because only the policy document can.
* ``unsafe_action``: causes or next steps that recommend destructive operations
  (dropping data, deleting namespaces, ``rm -rf``, piping a download into a shell,
  disabling authentication or TLS, …). On-call engineers act on these reports at 3 a.m.,
  so the tool never recommends an irreversible command, whatever a document says. Our
  runbooks contain none of these patterns, so the false-positive cost is zero here, and
  the eval measures it on real reports (see docs/security.md).
* ``untrusted_link``: URLs whose host is not on ``ALLOWED_LINK_DOMAINS`` (default:
  ``.internal`` hosts). Planted links are the classic phishing and exfiltration
  payload of an injected document.
* ``prompt_leak``: any 8-word run copied from the system prompt. Not secret here, but a
  leak shows the model followed an injected instruction, so the report is untrusted.

Each guard is a pure function of the report text and the evidence, so verdicts are
reproducible and the eval can count them by type.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.schemas import Evidence, TriageReport, Violation

# Destructive operations a triage report must never recommend. Kept to unambiguous,
# irreversible actions; "restart" or "roll back" are normal remediation and allowed.
UNSAFE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(rx, re.IGNORECASE))
    for label, rx in (
        ("drop database object", r"\bdrop\s+(table|database|schema|index)\b"),
        ("truncate table", r"\btruncate\s+(table\s+)?\w+"),
        ("delete all rows", r"\bdelete\s+from\s+\w+(\s*;|\s*$|\s+(?!where\b)\w)"),
        ("recursive force delete", r"\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r"),
        ("format or overwrite a disk", r"\bmkfs(\.\w+)?\b|\bdd\s+if="),
        ("world-writable permissions", r"\bchmod\s+(-R\s+)?0?777\b"),
        ("pipe download into a shell", r"\b(curl|wget)\b[^|\n]*\|\s*(sudo\s+)?(ba|z)?sh\b"),
        ("delete cluster resources", r"\bkubectl\s+delete\s+(ns|namespace|pvc|pv|crd|node)s?\b"),
        ("flush all cache data", r"\bflushall\b|\bflushdb\b"),
        ("force push", r"\bgit\s+push\s+(-f|--force)\b"),
        ("disable a security control",
         r"\b(disable|turn\s+off|bypass)\s+(the\s+)?(auth\w*|tls|ssl|mfa|2fa|firewall|"
         r"waf|rate[\s-]?limit\w*|certificate\s+verification)\b"),
    )
)
URL = re.compile(r"\bhttps?://[^\s\"'<>)\]]+", re.IGNORECASE)
LEAK_NGRAM = 8


@dataclass(frozen=True)
class OutputGuards:
    """What the guards need besides the report. Built per request by ``build_guards``."""

    policy_ids: frozenset[str] = frozenset()  # chunk ids allowed in severity_citations
    allowed_link_domains: tuple[str, ...] = (".internal",)
    system_prompt: str = ""
    _prompt_ngrams: frozenset[tuple[str, ...]] = field(default=frozenset(), repr=False)

    @classmethod
    def build(cls, *, policy_ids: Iterable[str], allowed_link_domains: Iterable[str],
              system_prompt: str) -> OutputGuards:
        words = _words(system_prompt)
        grams = frozenset(tuple(words[i:i + LEAK_NGRAM])
                          for i in range(len(words) - LEAK_NGRAM + 1))
        return cls(frozenset(policy_ids), tuple(allowed_link_domains), system_prompt, grams)


def build_guards(evidence: list[Evidence], *, policy_doc_ids: Iterable[str],
                 allowed_link_domains: Iterable[str], system_prompt: str) -> OutputGuards:
    policy_docs = set(policy_doc_ids)
    return OutputGuards.build(
        policy_ids=[e.chunk_id for e in evidence if e.doc_id in policy_docs],
        allowed_link_domains=allowed_link_domains,
        system_prompt=system_prompt,
    )


def check(report: TriageReport, guards: OutputGuards) -> list[Violation]:
    out: list[Violation] = []
    out += _severity_provenance(report, guards)
    texts = _texts(report)
    for where, text in texts:
        if where.startswith(("likely_causes", "next_steps")):
            for label, rx in UNSAFE_PATTERNS:
                if m := rx.search(text):
                    out.append(Violation(type="unsafe_action",
                                         detail=f"{where} recommends {label}: {m.group(0)!r}"))
        for url in URL.findall(text):
            host = (urlsplit(url).hostname or "").lower()
            if not any(host == d.lstrip(".") or host.endswith(d if d.startswith(".") else "." + d)
                       for d in guards.allowed_link_domains):
                out.append(Violation(type="untrusted_link",
                                     detail=f"{where} links to untrusted host {host!r}"))
    if guards._prompt_ngrams:
        for where, text in texts:
            words = _words(text)
            if any(tuple(words[i:i + LEAK_NGRAM]) in guards._prompt_ngrams
                   for i in range(len(words) - LEAK_NGRAM + 1)):
                out.append(Violation(type="prompt_leak",
                                     detail=f"{where} repeats the system prompt"))
    return out


def _severity_provenance(report: TriageReport, guards: OutputGuards) -> list[Violation]:
    """A severity must cite at least one policy chunk; extra supporting citations are fine.

    The stricter "policy chunks only" rule rejected 2 of 96 correct eval reports, which
    cited the policy plus a similar past incident. This rule still stops the attack seen in
    the red-team suite (severity justified by a poisoned document alone). An attacker who
    also gets the model to cite the real policy is only stopped by the model.
    """
    if not guards.policy_ids or report.severity is None:
        return []  # no policy retrieved / no severity: missing-citation rules apply
    if any(cid in guards.policy_ids for cid in report.severity_citations):
        return []
    return [Violation(
        type="severity_not_from_policy",
        detail=f"severity {report.severity.value} cites {report.severity_citations}, none "
               "from the severity policy",
    )]


def _texts(report: TriageReport) -> list[tuple[str, str]]:
    out = [("summary", report.summary)]
    out += [(f"likely_causes[{i}]", c.description) for i, c in enumerate(report.likely_causes)]
    out += [(f"next_steps[{i}]", s.action) for i, s in enumerate(report.next_steps)]
    out += [(f"missing_information[{i}]", m) for i, m in enumerate(report.missing_information)]
    return out


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())
