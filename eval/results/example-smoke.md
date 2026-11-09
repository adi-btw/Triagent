# Evaluation report: 20261109T235113Z-b466541

> **SMOKE TEST: THESE NUMBERS ARE MEANINGLESS.** This run used a fake LLM (`LLM_PROVIDER=fake`, which pattern-fills reports without reading the incident) and/or a fake keyword-overlap retriever. It only proves the harness runs end to end. Do not quote any number below.

## Run metadata

- **Run id:** `20261109T235113Z-b466541`
- **Timestamp (UTC):** `2026-11-09T23:51:42+00:00`
- **Git sha:** `b466541`
- **Uncommitted changes:** `True`
- **LLM provider:** `fake`
- **LLM model:** `fake-demo`
- **Temperature:** `0.0`
- **Prompt versions (from traces):** `agent-v1, triage-v1`
- **Judge enabled:** `False`
- **Retriever:** `app.retrieval.factory.build_retriever`
- **Embedder:** `fastembed (BAAI/bge-small-en-v1.5)`
- **Retrieval mode:** `vector`
- **top_k:** `5`
- **cases.jsonl sha256:** `98ea6234094901b5247472171658d9e450c025f2aabc8db088161f589c53bf5a`
- **Corpus sha256:** `c7f509117d894593f36a623aae3aa58537a771bbb625b6063e4f939d295fcdb0`
- **Cases:** `32`
- **Repeats:** `1`
- **Modes:** `no_retrieval, rag, agent`
- **Bootstrap:** `percentile, 2000 resamples over cases, seed 20261109`
- **LLM calls made (generation):** `133`
- **LLM calls made (judge):** `0`

## Comparison

Same LLM in every mode; only the evidence and control flow differ. n = 32 cases (one case is about 3 percentage points). Brackets are 95% bootstrap CIs (2000 resamples over cases). **With this n, differences under ~10 pp are not meaningful, and overlapping intervals mean the data do not separate the modes.**

| Metric | no_retrieval | rag | agent |
|---|---|---|---|
| Results (cases x repeats) | 32 | 32 | 32 |
| Status ok | 100% (32/32) | 100% (32/32) | 100% (32/32) |
| Status invalid_output | 0% (0/32) | 0% (0/32) | 0% (0/32) |
| Status needs_clarification | 0% (0/32) | 0% (0/32) | 0% (0/32) |
| Status error (crashed) | 0% (0/32) | 0% (0/32) | 0% (0/32) |
| Citation validity (no unknown ids) | 100% (32/32) | 100% (32/32) | 100% (32/32) |
| Severity exact [95% CI] | 0% (0/29) [0-0] | 0% (0/29) [0-0] | 0% (0/29) [0-0] |
| Severity within one level | 0% (0/29) | 0% (0/29) | 0% (0/29) |
| Correct abstention (insufficient_evidence cases) | 100% (7/7) | 100% (7/7) | 100% (7/7) |
| False abstention (answerable cases, lower is better) | 100% (20/20) | 100% (20/20) | 100% (20/20) |
| Abstention accuracy [95% CI] | 26% (7/27) [11-44] | 26% (7/27) [11-44] | 26% (7/27) [11-44] |
| Retrieval doc recall@k | n/a | 40% (n=29) | 45% (n=29) |
| Retrieval chunk recall@k | n/a | 40% (n=29) | 46% (n=29) |
| Cited-doc precision (PROXY vs labels) | n/a (n=0) | 59% (n=29) | 64% (n=29) |
| Claims supported (judge) [95% CI] | n/a | n/a | n/a |
| Claims partially supported | n/a | n/a | n/a |
| Claims not supported | n/a | n/a | n/a |
| Claims unjudged (judge gave no verdict) | n/a | n/a | n/a |
| Clarification rate (ambiguous, agent only) | n/a | n/a | 100% (5/5) |
| Over-asking (unambiguous, agent only) | n/a | n/a | 0% (0/27) |
| Latency p50 | 0 ms | 203 ms | 629 ms |
| Latency p95 | 0 ms | 1,004 ms | 1,040 ms |
| Latency mean | 1 ms | 399 ms | 500 ms |
| Mean LLM calls per case (excl. judge) | 1.00 | 1.00 | 2.16 |
| Mean tokens per case (in+out, if reported) | 130 | 361 | 459 |

## By category

### ambiguous

| Metric | no_retrieval | rag | agent |
|---|---|---|---|
| Results | 5 | 5 | 5 |
| Status ok | 100% (5/5) | 100% (5/5) | 100% (5/5) |
| Status error | 0% (0/5) | 0% (0/5) | 0% (0/5) |
| Severity exact | 0% (0/5) | 0% (0/5) | 0% (0/5) |
| Correct abstention | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| False abstention | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| Doc recall@k | n/a | 20% (n=5) | 47% (n=5) |
| Claims supported | n/a | n/a | n/a |
| Clarification rate | n/a | n/a | 100% (5/5) |

### answerable

| Metric | no_retrieval | rag | agent |
|---|---|---|---|
| Results | 20 | 20 | 20 |
| Status ok | 100% (20/20) | 100% (20/20) | 100% (20/20) |
| Status error | 0% (0/20) | 0% (0/20) | 0% (0/20) |
| Severity exact | 0% (0/20) | 0% (0/20) | 0% (0/20) |
| Correct abstention | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| False abstention | 100% (20/20) | 100% (20/20) | 100% (20/20) |
| Doc recall@k | n/a | 53% (n=20) | 53% (n=20) |
| Claims supported | n/a | n/a | n/a |
| Clarification rate | n/a | n/a | n/a (n=0) |

### insufficient_evidence

| Metric | no_retrieval | rag | agent |
|---|---|---|---|
| Results | 7 | 7 | 7 |
| Status ok | 100% (7/7) | 100% (7/7) | 100% (7/7) |
| Status error | 0% (0/7) | 0% (0/7) | 0% (0/7) |
| Severity exact | 0% (0/4) | 0% (0/4) | 0% (0/4) |
| Correct abstention | 100% (7/7) | 100% (7/7) | 100% (7/7) |
| False abstention | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| Doc recall@k | n/a | 0% (n=4) | 0% (n=4) |
| Claims supported | n/a | n/a | n/a |
| Clarification rate | n/a | n/a | n/a (n=0) |

Ambiguous cases are asymmetric by design: `agent` may ask a clarifying question and is then re-run with the scripted answer; `no_retrieval` and `rag` cannot ask and are scored on the vague incident alone, against labels that describe the incident *after* clarification. Their low scores there are expected.

## Severity confusion matrices

### no_retrieval

| expected \ predicted | SEV1 | SEV2 | SEV3 | SEV4 | null |
|---|---|---|---|---|---|
| SEV1 | 0 | 0 | 0 | 0 | 4 |
| SEV2 | 0 | 0 | 0 | 0 | 10 |
| SEV3 | 0 | 0 | 0 | 0 | 12 |
| SEV4 | 0 | 0 | 0 | 0 | 3 |

### rag

| expected \ predicted | SEV1 | SEV2 | SEV3 | SEV4 | null |
|---|---|---|---|---|---|
| SEV1 | 0 | 0 | 0 | 0 | 4 |
| SEV2 | 0 | 0 | 0 | 0 | 10 |
| SEV3 | 0 | 0 | 0 | 0 | 12 |
| SEV4 | 0 | 0 | 0 | 0 | 3 |

### agent

| expected \ predicted | SEV1 | SEV2 | SEV3 | SEV4 | null |
|---|---|---|---|---|---|
| SEV1 | 0 | 0 | 0 | 0 | 4 |
| SEV2 | 0 | 0 | 0 | 0 | 10 |
| SEV3 | 0 | 0 | 0 | 0 | 12 |
| SEV4 | 0 | 0 | 0 | 0 | 3 |

## Failed and erroring cases

_None: every result was `ok` and every judge call succeeded._

## How to read this

- **Every rate shows k/n.** Quality rows (severity, abstention, citations, claims) only count results with a parsed report; check the status rows to see how many were dropped from them. Errors are never silently removed.
- **Severity exact** compares to a single labeller's reading of POL-SEV-001; *within one level* shows whether misses are near-misses.
- **Citation validity** only proves cited ids were retrieved. **Claims supported** is an LLM judge's opinion that the cited passage backs the claim; it has its own error rate and should be calibrated against a human spot-check. In `no_retrieval` every claim is not supported by construction (no passages).
- **Cited-doc precision** is a cheap label-based proxy: it penalises citing a sensible doc the labeller did not list.
- **Recall@k** measures retrieval, not the answer: a mode can retrieve the right doc and still misread it.
- **Latency** excludes judge calls; p95 over ~30 samples is about the second-slowest case.
- The corpus and the eval cases were written by the same author, so retrieval numbers are likely optimistic compared with real tickets.
- n = 32: treat differences under ~10 pp as noise and read the CIs.
