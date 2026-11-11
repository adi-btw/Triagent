"""Build the severity-classification dataset: templates -> train / val / test JSONL.

    python -m finetune.build_dataset            # writes finetune/data/{train,val,test}.jsonl

Labels are **computed from the facts, never written by hand or by a model**. Each
example is generated from a small set of facts (service, error rate, p95 latency
multiple, outage, data loss or security exposure, internal system with or without a
workaround, customer impact). The text is rendered from those facts, and
``label(facts)`` applies POL-SEV-001 to the same facts. The label can't drift from the
text, and the rubric is one function that tests check against the policy wording.

**Split by scenario template, not by row.** 32 templates (deploy regression, cert
expiry, leaked credentials, CI down, ...) are assigned whole to train, val or test,
stratified by kind. A test incident is never a paraphrase of a training incident.
Within a template, the numbers and service decide the class, so most templates produce
several classes. The model has to read the numbers, not memorise "cert expiry = SEV2".

**Hard cases on purpose.** Some examples sit on a boundary of the rubric (5% and 50%
error rates, p95 latency just under or over 3x). Error rates are written as percentages,
fractions ("460 of 2,000 requests") or ratios, and latency as two durations the model
has to compare. A model has to do the arithmetic to get these right.

The stage-3 eval cases (data/eval/cases.jsonl) are never used: they are a different,
hand-written set, and ``leakage_report`` checks the closest text overlap with them.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

OUT_DIR = Path("finetune/data")
POLICY_PATH = Path("data/corpus/policies/POL-SEV-001.md")
LABELS = ("SEV1", "SEV2", "SEV3", "SEV4")
REVENUE = ("checkout-api", "payments-api", "cart-api")
NON_REVENUE = ("search-api", "recommendations-api", "notifications-api")
INTERNAL = ("CI (Jenkins)", "Grafana", "the corporate VPN", "the admin console",
            "the deploy pipeline", "the data warehouse", "the feature-flag dashboard",
            "the on-call paging tool", "the internal wiki")
SEED = 20261110
PER_CLASS = {"train": 250, "val": 40, "test": 50}


# --------------------------------------------------------------------------- facts + rubric


@dataclass
class Facts:
    kind: str  # "service" | "internal" | "no_impact" | "data_security"
    service: str = ""
    error_pct: float = 0.0
    full_outage: bool = False
    latency_mult: float = 1.0
    internal_down: bool = False
    workaround: bool = True
    data_loss_or_exposure: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


def label(f: Facts) -> str:
    """POL-SEV-001, applied to facts. Checked clause by clause in tests/test_finetune_data.py."""
    if f.data_loss_or_exposure:
        return "SEV1"  # "any data loss/security exposure"
    if f.kind == "service":
        if f.service in REVENUE:
            if f.full_outage or f.error_pct > 50:
                return "SEV1"  # "fully unavailable, or >50% error rate on a revenue path"
            if f.error_pct >= 5 or f.latency_mult > 3:
                return "SEV2"  # "5–50% errors or p95 latency >3x baseline"
            return "SEV3"  # "revenue path <5% errors"
        return "SEV3"  # "non-revenue feature degraded"
    if f.kind == "internal":
        return "SEV2" if f.internal_down and not f.workaround else "SEV4"
    return "SEV4"  # "no customer impact; internal tooling or cosmetic issues"


# --------------------------------------------------------------------------- sampling facts


def _error_for(rng: random.Random, target: str, boundary: bool) -> tuple[float, bool]:
    """An error rate (and outage flag) that puts a revenue service in ``target``."""
    if target == "SEV1":
        if rng.random() < 0.3:
            return 100.0, True
        return (rng.choice([51.0, 52.0, 55.0]) if boundary else float(rng.randint(56, 97))), False
    if target == "SEV2":
        if boundary:
            return rng.choice([5.0, 5.5, 6.0, 48.0, 49.0, 50.0]), False
        return float(rng.randint(7, 45)), False
    low = rng.choice([4.0, 4.5, 4.8]) if boundary else rng.choice([0.4, 0.8, 1.2, 2.0, 3.0])
    return low, False


def sample_service(rng: random.Random, target: str) -> Facts | None:
    """Customer-facing degradation whose label is ``target`` (SEV1–SEV3), or None."""
    boundary = rng.random() < 0.25
    if target == "SEV3" and rng.random() < 0.45:  # non-revenue: any degradation is SEV3
        err = float(rng.choice([2, 8, 15, 30, 60, 100]))
        return Facts("service", service=rng.choice(NON_REVENUE), error_pct=err,
                     full_outage=err == 100, latency_mult=round(rng.uniform(1.0, 8.0), 1))
    if target == "SEV4":
        return None
    svc = rng.choice(REVENUE)
    if target == "SEV2" and rng.random() < 0.3:  # latency-driven SEV2: low errors, >3x
        mult = rng.choice([3.1, 3.2, 3.4]) if boundary else round(rng.uniform(3.6, 9.0), 1)
        return Facts("service", service=svc, error_pct=rng.choice([0.0, 0.5, 1.5, 3.0]),
                     latency_mult=mult)
    err, outage = _error_for(rng, target, boundary)
    mult = (rng.choice([2.6, 2.8, 3.0]) if boundary and target == "SEV3"
            else round(rng.uniform(1.0, 2.8 if target == "SEV3" else 6.0), 1))
    return Facts("service", service=svc, error_pct=err, full_outage=outage, latency_mult=mult)


def sample_internal(rng: random.Random, target: str) -> Facts | None:
    if target == "SEV2":
        return Facts("internal", service=rng.choice(INTERNAL), internal_down=True, workaround=False)
    if target == "SEV4":
        down = rng.random() < 0.6
        return Facts("internal", service=rng.choice(INTERNAL), internal_down=down, workaround=True)
    return None


def sample_no_impact(rng: random.Random, target: str) -> Facts | None:
    if target != "SEV4":
        return None
    return Facts("no_impact", service=rng.choice(REVENUE + NON_REVENUE))


def sample_data_security(rng: random.Random, target: str) -> Facts | None:
    if target != "SEV1":
        return None
    return Facts("data_security", service=rng.choice(REVENUE + NON_REVENUE + ("orders-db",)),
                 data_loss_or_exposure=True)


SAMPLERS: dict[str, Callable[[random.Random, str], Facts | None]] = {
    "service": sample_service, "internal": sample_internal,
    "no_impact": sample_no_impact, "data_security": sample_data_security,
}


# --------------------------------------------------------------------------- rendering helpers


def fmt_errors(rng: random.Random, f: Facts) -> str:
    """The error rate in one of several forms the model must read."""
    if f.full_outage:
        return rng.choice(["every request is failing", "100% of requests return 5xx",
                           "the service is completely down, 0 successful requests"])
    pct = f.error_pct
    if pct == 0:
        return rng.choice(["no errors", "error rate is flat at 0%", "zero 5xx"])
    form = rng.random()
    if form < 0.55:
        return f"{pct:g}% of requests failing" if rng.random() < 0.5 else f"error rate {pct:g}%"
    if form < 0.8:
        total = rng.choice([2000, 4000, 5000, 10000])
        return f"{round(total * pct / 100):,} of {total:,} requests returned 5xx in the last minute"
    return f"error ratio {pct / 100:.3f}".rstrip("0").rstrip(".")


def fmt_latency(rng: random.Random, f: Facts) -> str:
    base = rng.choice([120, 200, 250, 300, 400, 600, 800])
    now = round(base * f.latency_mult)
    def ms(v: int) -> str:
        return f"{v / 1000:.2f}s".replace(".00s", "s") if v >= 1000 else f"{v}ms"
    return rng.choice([f"p95 latency {ms(now)} (baseline ~{ms(base)})",
                       f"p95 went from {ms(base)} to {ms(now)}",
                       f"p95 is {ms(now)}; it's normally around {ms(base)}"])


def ts(rng: random.Random) -> str:
    return f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}T{rng.randint(0, 23):02d}:" \
           f"{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}Z"


def ver(rng: random.Random) -> str:
    return f"v{rng.randint(1, 9)}.{rng.randint(0, 40)}.{rng.randint(0, 9)}"


def impact(rng: random.Random, f: Facts) -> str:
    if f.full_outage:  # nothing succeeds, so there is no latency to quote
        return f"{f.service}: {fmt_errors(rng, f)}."
    return f"{f.service}: {fmt_errors(rng, f)}, {fmt_latency(rng, f)}."


# --------------------------------------------------------------------------- templates
# Each template turns facts into an incident report. The facts decide the label; the
# template supplies the story, wording and log lines. Kind decides which facts it accepts.

T = Callable[[random.Random, Facts], str]
TEMPLATES: dict[str, tuple[str, T]] = {}


def template(name: str, kind: str) -> Callable[[T], T]:
    def deco(fn: T) -> T:
        TEMPLATES[name] = (kind, fn)
        return fn
    return deco


@template("deploy_regression", "service")
def _(r, f):
    return (f"We rolled out {f.service} {ver(r)} at {r.randint(8, 18)}:{r.randint(10, 59)} UTC. "
            f"Since then: {impact(r, f)}\n{ts(r)} ERROR {f.service} handler panicked: "
            "nil pointer dereference in OrderSerializer")


@template("db_pool_exhaustion", "service")
def _(r, f):
    return (f"{f.service} is timing out acquiring DB connections. {impact(r, f)}\n"
            f"{ts(r)} ERROR {f.service} pool.acquire timed out after 5000ms\n"
            f"{ts(r)} WARN db connections active={r.randint(180, 200)} max_connections=200")


@template("cert_expiry", "service")
def _(r, f):
    return (f"TLS handshake failures from {f.service} to an upstream since midnight. "
            f"{impact(r, f)}\n{ts(r)} ERROR x509: certificate has expired or is not yet valid")


@template("dns_failure", "service")
def _(r, f):
    return (f"Intermittent name resolution errors in {f.service} pods after a CoreDNS change. "
            f"{impact(r, f)}\n{ts(r)} ERROR dial tcp: lookup redis.internal: i/o timeout")


@template("cache_stampede", "service")
def _(r, f):
    return (f"Redis was flushed during maintenance and {f.service} is hammering the database "
            f"on cache misses. {impact(r, f)} Cache hit ratio dropped from 0.97 to "
            f"{r.uniform(0.1, 0.5):.2f}.")


@template("third_party_outage", "service")
def _(r, f):
    vendor = r.choice(["our card processor", "the SMS provider", "the address-validation vendor",
                       "the fraud-scoring API"])
    return (f"Calls from {f.service} to {vendor} are failing or slow; their status page shows "
            f"a partial outage. Our side: {impact(r, f)}")


@template("oom_crashloop", "service")
def _(r, f):
    return (f"{f.service} pods are OOMKilled and restarting every few minutes "
            f"(restarts={r.randint(8, 60)}). {impact(r, f)}\n"
            f"{ts(r)} Warning BackOff kubelet Back-off restarting failed container")


@template("disk_full", "service")
def _(r, f):
    return (f"The volume behind {f.service} hit {r.randint(97, 100)}% disk usage and writes "
            f"are failing. {impact(r, f)}\n{ts(r)} ERROR write /data/wal: no space left on device")


@template("slow_query_lock", "service")
def _(r, f):
    return (f"A migration is holding a lock on the orders table. {impact(r, f)}\n"
            f"{ts(r)} LOG process {r.randint(1000, 9999)} still waiting for AccessExclusiveLock "
            f"after {r.randint(1000, 60000)} ms")


@template("rate_limit_misconfig", "service")
def _(r, f):
    return (f"A gateway config push lowered the rate limit for {f.service}. Clients get 429s. "
            f"{impact(r, f)}")


@template("feature_flag_bug", "service")
def _(r, f):
    flag = r.choice(["new_pricing_engine", "async_tax_calc", "v2_search_ranker", "batch_emails"])
    return (f"Enabling the `{flag}` flag for {r.choice([10, 25, 50, 100])}% of users caused "
            f"errors in {f.service}. {impact(r, f)}")


@template("az_network_partition", "service")
def _(r, f):
    return (f"AWS reports packet loss in {r.choice(['us-east-1a', 'eu-west-1b', 'us-west-2c'])}. "
            f"{f.service} replicas in that zone are flapping. {impact(r, f)}")


@template("queue_backlog", "service")
def _(r, f):
    return (f"The {r.choice(['orders', 'events', 'emails'])} queue has a backlog of "
            f"{r.randint(20, 900)}k messages and consumers behind {f.service} are lagging. "
            f"{impact(r, f)}")


@template("gc_pauses", "service")
def _(r, f):
    return (f"Long GC pauses on {f.service} JVMs after the heap size change. {impact(r, f)}\n"
            f"{ts(r)} [gc] Pause Full (Allocation Failure) {r.randint(800, 4000)}ms")


@template("dependency_timeout", "service")
def _(r, f):
    dep = r.choice(["inventory-service", "pricing-service", "user-profile", "tax-service"])
    return (f"{dep} is slow and {f.service} calls to it time out at 2s. {impact(r, f)}\n"
            f"{ts(r)} WARN {f.service} upstream {dep} timeout after 2000ms")


@template("autoscaler_stuck", "service")
def _(r, f):
    return (f"The HPA for {f.service} is stuck at {r.randint(2, 4)} replicas during the "
            f"traffic peak (metrics-server unavailable). {impact(r, f)}")


def _internal_text(r: random.Random, f: Facts, what: str) -> str:
    state = "is completely down" if f.internal_down else "is slow and some pages fail to load"
    wa = (r.choice(["There is no workaround right now.", "Nobody can work around it.",
                    "No fallback exists."]) if not f.workaround else
          r.choice(["People can use the CLI as a workaround.", "A manual fallback works.",
                    "The backup instance still works."]))
    return f"{f.service} {state} {what}. {wa} No customer-facing service is affected."


@template("ci_down", "internal")
def _(r, f):
    return _internal_text(r, f, "after the runner pool was rotated")


@template("observability_down", "internal")
def _(r, f):
    return _internal_text(r, f, f"since {ts(r)} following a storage upgrade")


@template("vpn_outage", "internal")
def _(r, f):
    return _internal_text(r, f, "for engineers outside the office")


@template("admin_console_down", "internal")
def _(r, f):
    return _internal_text(r, f, f"after {ver(r)} was deployed")


@template("pipeline_broken", "internal")
def _(r, f):
    return _internal_text(r, f, "because an auth token for the artifact registry expired")


@template("warehouse_job_failed", "internal")
def _(r, f):
    return _internal_text(r, f, "and last night's ETL job failed")


@template("ui_typo", "no_impact")
def _(r, f):
    return (f"Reported by support: a typo on the {f.service} confirmation page "
            f"(\"{r.choice(['Recieved', 'Sucessful', 'Adress'])}\"). Orders go through normally; "
            "error rate and latency are at baseline.")


@template("staging_down", "no_impact")
def _(r, f):
    return (f"The staging environment for {f.service} is down after a bad Terraform apply. "
            "Production is unaffected, error rate 0%.")


@template("flapping_alert", "no_impact")
def _(r, f):
    return (f"The {f.service} disk alert has fired and resolved {r.randint(5, 40)} times today. "
            "Disk usage is steady at 61%; no user impact, no errors.")


@template("log_volume_spike", "no_impact")
def _(r, f):
    return (f"{f.service} started logging {r.randint(5, 40)}x more debug lines after "
            f"{ver(r)}. Requests, errors and latency are all normal.")


@template("dashboard_units", "no_impact")
def _(r, f):
    return (f"The {f.service} dashboard shows latency in seconds labelled as ms, so it looks "
            "1000x worse than it is. Real p95 is at baseline; customers are unaffected.")


@template("leaked_credentials", "data_security")
def _(r, f):
    return (f"A {f.service} API key with write access was committed to a public GitHub repo "
            f"{r.randint(2, 40)} hours ago. The service itself is healthy, error rate "
            f"{r.choice([0, 0.2, 0.5])}%.")


@template("migration_data_loss", "data_security")
def _(r, f):
    return (f"A cleanup migration on {f.service} deleted {r.randint(200, 90000):,} rows that were "
            "still in use, and backups are 26 hours old. Traffic and errors look normal.")


@template("pii_in_logs", "data_security")
def _(r, f):
    return (f"{f.service} has been writing full card numbers and emails to logs shipped to a "
            f"third-party log vendor since {ver(r)}. No errors; latency normal.")


@template("public_bucket", "data_security")
def _(r, f):
    return (f"An S3 bucket with {f.service} exports (customer names and addresses) was "
            "publicly readable for 3 days. Access logs show downloads from unknown IPs.")


@template("replica_data_loss", "data_security")
def _(r, f):
    return (f"Failover promoted a replica of {f.service}'s database that was "
            f"{r.randint(3, 40)} minutes behind; those writes are lost. Service is otherwise up.")


SPLIT_TEMPLATES = {
    # Assigned whole, stratified by kind: service 10/2/4, internal 4/1/1,
    # no_impact 3/1/1, data_security 3/1/1. Never change this after reporting results.
    "test": ["cert_expiry", "cache_stampede", "queue_backlog", "autoscaler_stuck",
             "pipeline_broken", "staging_down", "public_bucket"],
    "val": ["dns_failure", "gc_pauses", "vpn_outage", "log_volume_spike", "pii_in_logs"],
}
SPLIT_TEMPLATES["train"] = [t for t in TEMPLATES if not any(
    t in v for v in SPLIT_TEMPLATES.values())]


# --------------------------------------------------------------------------- prompt


def policy_text(path: Path = POLICY_PATH) -> str:
    text = path.read_text(encoding="utf-8")
    return text.split("---", 2)[2].strip() if text.startswith("---") else text.strip()


INSTRUCTION = ("Classify the incident's severity using this policy. Answer with exactly one "
               "label: SEV1, SEV2, SEV3 or SEV4.")


def build_prompt(policy: str, incident: str) -> str:
    """The user message; train.py and evaluate.py wrap it in the model's chat template."""
    return f"{INSTRUCTION}\n\n{policy}\n\nIncident:\n{incident}"


# --------------------------------------------------------------------------- generation


def generate(split: str, per_class: int, rng: random.Random) -> list[dict[str, Any]]:
    names = SPLIT_TEMPLATES[split]
    rows, seen = [], set()
    for target in LABELS:
        makers = [(n, TEMPLATES[n]) for n in names]
        made, tries = 0, 0
        while made < per_class:
            tries += 1
            if tries > per_class * 200:
                raise RuntimeError(f"{split}: no template in this split can make {target}")
            name, (kind, render) = rng.choice(makers)
            facts = SAMPLERS[kind](rng, target)
            if facts is None:
                continue
            assert label(facts) == target, (name, facts)
            text = render(rng, facts)
            text = text[0].upper() + text[1:]
            key = re.sub(r"\s+", " ", text.lower())
            if key in seen:
                continue
            seen.add(key)
            rows.append({"id": f"{split}-{len(rows):04d}", "template": name, "kind": kind,
                         "incident": text, "label": target,
                         "facts": {k: v for k, v in asdict(facts).items() if k != "extra"}})
            made += 1
    rng.shuffle(rows)
    return rows


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z0-9_-]+", text.lower()))


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def leakage_report(splits: dict[str, list[dict]], eval_cases: list[str]) -> dict[str, float]:
    """Highest word-set overlap of any test row with any train row / any stage-3 case."""
    train = [tokens(r["incident"]) for r in splits["train"]]
    cases = [tokens(c) for c in eval_cases]
    out = {"test_vs_train": 0.0, "test_vs_eval_cases": 0.0, "train_vs_eval_cases": 0.0}
    for r in splits["test"]:
        t = tokens(r["incident"])
        out["test_vs_train"] = max(out["test_vs_train"], max(jaccard(t, x) for x in train))
        out["test_vs_eval_cases"] = max(out["test_vs_eval_cases"],
                                        max((jaccard(t, c) for c in cases), default=0.0))
    for t in train:
        out["train_vs_eval_cases"] = max(out["train_vs_eval_cases"],
                                         max((jaccard(t, c) for c in cases), default=0.0))
    return {k: round(v, 3) for k, v in out.items()}


def build(out_dir: Path = OUT_DIR, seed: int = SEED) -> dict[str, Any]:
    rng = random.Random(seed)
    policy = policy_text()
    splits = {s: generate(s, PER_CLASS[s], rng) for s in ("train", "val", "test")}
    out_dir.mkdir(parents=True, exist_ok=True)
    for split, rows in splits.items():
        with (out_dir / f"{split}.jsonl").open("w", encoding="utf-8", newline="\n") as f:
            for row in rows:
                f.write(json.dumps({**row, "prompt": build_prompt(policy, row["incident"])},
                                   ensure_ascii=False) + "\n")
    cases_path = Path("data/eval/cases.jsonl")  # absent in the Colab bundle: no overlap check
    lines = cases_path.read_text(encoding="utf-8").splitlines() if cases_path.exists() else []
    cases = [json.loads(x)["incident"] for x in lines if x]
    stats = {
        "seed": seed,
        "sizes": {s: len(r) for s, r in splits.items()},
        "labels": {s: dict(sorted(Counter(r["label"] for r in rows).items()))
                   for s, rows in splits.items()},
        "templates": {s: sorted({r["template"] for r in rows}) for s, rows in splits.items()},
        "leakage_max_jaccard": leakage_report(splits, cases),
    }
    (out_dir / "stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8",
                                        newline="\n")
    return stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m finetune.build_dataset")
    p.add_argument("--out", type=Path, default=OUT_DIR)
    p.add_argument("--seed", type=int, default=SEED)
    args = p.parse_args(argv)
    stats = build(args.out, args.seed)
    print(json.dumps({k: stats[k] for k in ("sizes", "labels", "leakage_max_jaccard")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
