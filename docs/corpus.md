# The knowledge corpus

The triage assistant can only be as good as what it can retrieve. `data/corpus/` is a small,
synthetic knowledge base for a fictional e-commerce company: 26 Markdown docs (15 runbooks,
9 past incidents, 2 policies). This page explains how it was designed and why.

## Format

Each doc is YAML front-matter (`doc_id`, `type`, `title`, `services`, and `severity` for
incidents) followed by 2-4 `## ` sections. Each section becomes one retrievable chunk with ID
`<doc_id>#s<n>` (1-based heading index), so a citation like `RB-DB-001#s3` points at exactly
one paragraph a human can open and check. Sections are kept short (under ~100 words) so a
chunk is about one idea: symptoms, diagnosis, mitigation, root cause.

The company: revenue paths checkout-api, payments-api and cart-api; non-revenue search-api,
recommendations-api, notifications-api and inventory-api; plus auth-service, orders-db
(Postgres, max_connections=200, a read replica), redis-cache, an object store, a CDN,
Kubernetes and CoreDNS. Payments go to a fictional processor, PayFlux, with Ledgerly as backup.

## Three doc types, three jobs

- **Runbooks** (`RB-<AREA>-NNN`) say how to recognise, diagnose and fix a failure class.
  They provide the "next steps".
- **Past incidents** (`INC-YYYY-NNN`) are precedents with concrete numbers (pod counts, pool
  sizes, error %). They support "likely cause" claims ("this happened before, here is what it
  was") and show severity being applied.
- **Policies** (`POL-*`) define severity and paging. Every severity in a report should cite
  `POL-SEV-001`, so the model's severity is checkable, not vibes.

## Why near-miss distractors

If every doc used different vocabulary, retrieval would be trivially easy and the evaluation
would prove nothing. Real runbooks share symptoms: a timeout is a timeout. So the corpus
deliberately contains docs that share surface strings but have different root causes:

| Shared surface | Docs | What actually tells them apart |
|---|---|---|
| `timed out after 5000ms` | RB-DB-001, RB-DB-004, RB-NET-002, RB-PAY-001 | connection count at max vs Lock waits vs `EAI_AGAIN` vs only the provider host is slow |
| `connection refused` | RB-CACHE-001, RB-K8S-001, RB-DB-003 | Redis pod OOMKilled vs app pod crashlooping vs Postgres stopped on full disk |
| `OOMKilled` / exit 137 | RB-K8S-001, RB-APP-001, INC-2026-015 | killed in the first minute (limit too low) vs after hours of linear growth (leak) |
| `503` | RB-CDN-001, RB-K8S-001, RB-K8S-002, RB-PAY-001 | object store SlowDown vs no ready endpoints vs failing readiness probes vs provider |
| certificates / signatures | RB-TLS-001, RB-AUTH-001 | `x509 expired` vs JWT `kid not found in JWKS` |
| WAL | RB-DB-002, RB-DB-003 | replica cannot replay (stale reads) vs slot retains WAL (disk fills) |
| same cause, different severity | INC-2025-014 vs eval case-020 | connection exhaustion on checkout-api (SEV2) vs inventory-api (SEV3) |

Some incidents even narrate the trap: INC-2026-003 says the responder first followed the DNS
runbook because of the 5000ms timeout, and INC-2026-011 says connection exhaustion was
suspected but connections were 88/200. A good retriever plus reader must use the
discriminating detail, not the shared keyword. Keyword (BM25) search is especially exposed
to these, which is one reason hybrid retrieval is worth measuring.

## Why deliberately uncovered topics

A grounded assistant has to know when it does not know. These topics appear in no doc, and
`tests/test_corpus.py` fails if a doc mentions them:

- Kafka / message-queue consumer lag and broker replication
- Elasticsearch cluster health and JVM heap
- Mobile app crash reports
- BGP / ISP routing problems
- GPU / ML model serving

The `insufficient_evidence` eval cases are about these topics. The correct behaviour is
`insufficient_evidence: true` with no invented cause. Several are written to tempt the model:
the GPU case says "out of memory" on recommendations-api, which is exactly the service in the
memory-leak incident INC-2026-015. Severity may still be known (checkout-api at 8% errors is
SEV2 whatever the cause), which tests that the model separates "how bad" from "why".

## Doc index

| doc_id | type | title | covered topic |
|---|---|---|---|
| POL-SEV-001 | policy | Incident severity levels | SEV1-4 definitions, revenue paths |
| POL-ESC-001 | policy | Paging and escalation | who is paged per severity, escalation, vendor tickets |
| RB-DB-001 | runbook | PostgreSQL connection exhaustion | too many clients, pool size x replicas |
| RB-DB-002 | runbook | PostgreSQL replica replication lag | stale reads from the replica |
| RB-DB-003 | runbook | PostgreSQL disk full from WAL growth | inactive replication slots, pg_wal |
| RB-DB-004 | runbook | PostgreSQL lock contention from long-running migrations | blocking locks, migrations |
| RB-CACHE-001 | runbook | Redis memory exhaustion and eviction | maxmemory, eviction, Redis OOMKilled |
| RB-TLS-001 | runbook | TLS certificate expiry | expired certs, cert-manager renewal |
| RB-DEPLOY-001 | runbook | Rolling back a bad deploy | when and how to roll back |
| RB-K8S-001 | runbook | Pods in CrashLoopBackOff or OOMKilled | crash loops, startup OOM |
| RB-K8S-002 | runbook | Latency from CPU throttling | CFS throttling, tight CPU limits |
| RB-PAY-001 | runbook | Payment provider errors and timeouts | third-party 5xx/timeouts, failover |
| RB-AUTH-001 | runbook | JWT signing key rotation failure | JWKS cache, 401 storms |
| RB-CDN-001 | runbook | CDN cache purge storm overloading origin | purge-all, origin 503 SlowDown |
| RB-NET-002 | runbook | Upstream timeouts caused by DNS resolution failures | CoreDNS, EAI_AGAIN |
| RB-NET-003 | runbook | Unexpected 429s from ingress rate limiting | per-IP limits behind a CDN |
| RB-APP-001 | runbook | Memory leak after a deploy | gradual memory growth, OOM cycles |
| INC-2025-014 | incident (SEV2) | Checkout errors after autoscaling event | connection exhaustion after scale-out |
| INC-2025-021 | incident (SEV2) | Cart updates failing after Redis hit maxmemory | keys without TTL, noeviction |
| INC-2025-033 | incident (SEV1) | Payments outage from expired card-vault mTLS certificate | silent renewal failure |
| INC-2025-040 | incident (SEV3) | Stale inventory from orders-db replica lag | backfill WAL flood |
| INC-2026-003 | incident (SEV2) | Payment failures from PayFlux provider timeouts | provider outage, DNS red herring |
| INC-2026-009 | incident (SEV2) | Mass 401s after auth-service signing key rotation | activate-before-publish |
| INC-2026-011 | incident (SEV1) | Checkout outage from migration holding a table lock | non-concurrent index build |
| INC-2026-015 | incident (SEV3) | recommendations-api memory leak after v4.2.0 | unbounded in-process cache |
| INC-2026-022 | incident (SEV4) | orders-db disk growth from an abandoned replication slot | leftover slot, no impact |

## Rules for editing

- Never reorder or insert `## ` sections in an existing doc; chunk IDs are positional and the
  eval set and other tests reference them. Append new sections at the end.
- Keep incident severities consistent with POL-SEV-001 and state the numbers that justify them.
- Run `python -m pytest tests/test_corpus.py -q` after any change.
