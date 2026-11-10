# Evaluation report: 20261110T024152Z-738ce87

## Run metadata

- **Run id:** `20261110T024152Z-738ce87`
- **Timestamp (UTC):** `2026-11-10T02:46:30+00:00`
- **Git sha:** `738ce87`
- **Uncommitted changes:** `True`
- **LLM provider:** `gemini`
- **LLM model:** `gemini-3.5-flash-lite`
- **Temperature:** `0.0`
- **Prompt versions (from traces):** `agent-v1, triage-v1`
- **Judge enabled:** `True`
- **Judge model:** `gemini-3.5-flash-lite`
- **Judge prompt version:** `judge-v1`
- **Retriever:** `app.retrieval.factory.build_retriever`
- **Embedder:** `fastembed (BAAI/bge-small-en-v1.5)`
- **Retrieval mode:** `hybrid`
- **top_k:** `5`
- **cases.jsonl sha256:** `98ea6234094901b5247472171658d9e450c025f2aabc8db088161f589c53bf5a`
- **Corpus sha256:** `c7f509117d894593f36a623aae3aa58537a771bbb625b6063e4f939d295fcdb0`
- **Cases:** `32`
- **Repeats:** `1`
- **Modes:** `no_retrieval, rag, agent`
- **Bootstrap:** `percentile, 2000 resamples over cases, seed 20261109`
- **LLM calls made (generation):** `140`
- **LLM calls made (judge):** `52`
- **LLM calls replayed from cache (latency excludes model time):** `176/192`

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
| Severity exact [95% CI] | 38% (11/29) [21-55] | 79% (23/29) [66-93] | 93% (27/29) [83-100] |
| Severity within one level | 79% (23/29) | 79% (23/29) | 93% (27/29) |
| Correct abstention (insufficient_evidence cases) | 0% (0/7) | 71% (5/7) | 100% (7/7) |
| False abstention (answerable cases, lower is better) | 0% (0/20) | 0% (0/20) | 0% (0/20) |
| Abstention accuracy [95% CI] | 74% (20/27) [56-89] | 93% (25/27) [81-100] | 100% (27/27) [100-100] |
| Retrieval doc recall@k | n/a | 47% (n=29) | 51% (n=29) |
| Retrieval chunk recall@k | n/a | 47% (n=29) | 53% (n=29) |
| Cited-doc precision (PROXY vs labels) | n/a (n=0) | 90% (n=26) | 94% (n=28) |
| Claims supported (judge) [95% CI] | 0% (0/73) [0-0] | 67% (47/70) [53-79] | 75% (53/71) [64-84] |
| Claims partially supported | 0% (0/73) | 17% (12/70) | 17% (12/71) |
| Claims not supported | 100% (73/73) | 16% (11/70) | 8% (6/71) |
| Claims unjudged (judge gave no verdict) | 0 | 0 | 0 |
| Clarification rate (ambiguous, agent only) | n/a | n/a | 80% (4/5) |
| Over-asking (unambiguous, agent only) | n/a | n/a | 0% (0/27) |
| Latency p50 | 106 ms | 862 ms | 1,108 ms |
| Latency p95 | 1,317 ms | 2,474 ms | 1,671 ms |
| Latency mean | 271 ms | 964 ms | 1,069 ms |
| Mean LLM calls per case (excl. judge) | 1.00 | 1.00 | 2.38 |
| Mean tokens per case (in+out, if reported) | 591 | 1779 | 3790 |

## By category

### ambiguous

| Metric | no_retrieval | rag | agent |
|---|---|---|---|
| Results | 5 | 5 | 5 |
| Status ok | 100% (5/5) | 100% (5/5) | 100% (5/5) |
| Status error | 0% (0/5) | 0% (0/5) | 0% (0/5) |
| Severity exact | 0% (0/5) | 0% (0/5) | 80% (4/5) |
| Correct abstention | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| False abstention | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| Doc recall@k | n/a | 40% (n=5) | 67% (n=5) |
| Claims supported | 0% (0/11) | 50% (2/4) | 80% (8/10) |
| Clarification rate | n/a | n/a | 80% (4/5) |

### answerable

| Metric | no_retrieval | rag | agent |
|---|---|---|---|
| Results | 20 | 20 | 20 |
| Status ok | 100% (20/20) | 100% (20/20) | 100% (20/20) |
| Status error | 0% (0/20) | 0% (0/20) | 0% (0/20) |
| Severity exact | 50% (10/20) | 100% (20/20) | 100% (20/20) |
| Correct abstention | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| False abstention | 0% (0/20) | 0% (0/20) | 0% (0/20) |
| Doc recall@k | n/a | 57% (n=20) | 57% (n=20) |
| Claims supported | 0% (0/46) | 75% (45/60) | 75% (45/60) |
| Clarification rate | n/a | n/a | n/a (n=0) |

### insufficient_evidence

| Metric | no_retrieval | rag | agent |
|---|---|---|---|
| Results | 7 | 7 | 7 |
| Status ok | 100% (7/7) | 100% (7/7) | 100% (7/7) |
| Status error | 0% (0/7) | 0% (0/7) | 0% (0/7) |
| Severity exact | 25% (1/4) | 75% (3/4) | 75% (3/4) |
| Correct abstention | 0% (0/7) | 71% (5/7) | 100% (7/7) |
| False abstention | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| Doc recall@k | n/a | 0% (n=4) | 0% (n=4) |
| Claims supported | 0% (0/16) | 0% (0/6) | 0% (0/1) |
| Clarification rate | n/a | n/a | n/a (n=0) |

Ambiguous cases are asymmetric by design: `agent` may ask a clarifying question and is then re-run with the scripted answer; `no_retrieval` and `rag` cannot ask and are scored on the vague incident alone, against labels that describe the incident *after* clarification. Their low scores there are expected.

## Severity confusion matrices

### no_retrieval

| expected \ predicted | SEV1 | SEV2 | SEV3 | SEV4 | null |
|---|---|---|---|---|---|
| SEV1 | 4 | 0 | 0 | 0 | 0 |
| SEV2 | 3 | 5 | 0 | 0 | 2 |
| SEV3 | 0 | 8 | 2 | 0 | 2 |
| SEV4 | 0 | 1 | 1 | 0 | 1 |

### rag

| expected \ predicted | SEV1 | SEV2 | SEV3 | SEV4 | null |
|---|---|---|---|---|---|
| SEV1 | 4 | 0 | 0 | 0 | 0 |
| SEV2 | 0 | 8 | 0 | 0 | 2 |
| SEV3 | 0 | 0 | 9 | 0 | 3 |
| SEV4 | 0 | 0 | 0 | 2 | 1 |

### agent

| expected \ predicted | SEV1 | SEV2 | SEV3 | SEV4 | null |
|---|---|---|---|---|---|
| SEV1 | 4 | 0 | 0 | 0 | 0 |
| SEV2 | 0 | 10 | 0 | 0 | 0 |
| SEV3 | 0 | 0 | 10 | 0 | 2 |
| SEV4 | 0 | 0 | 0 | 3 | 0 |

## Latency note for this run

This report was completed in two passes. The first pass (run `20261110T023235Z-145f0f9`) made
fresh calls, and 82 of 96 units succeeded before the API key's prepaid credits ran out. The second pass
replayed those answers from the LLM cache (`app/llm/cache.py`) and made the 16 missing calls. The
latency rows above therefore mostly measure cache replay, **not model time**. Latency measured
on the first pass's fresh calls (successful units only):

| | no_retrieval | rag | agent |
|---|---|---|---|
| Units with fresh calls | 27 | 27 | 28 |
| Latency p50 | 1,122 ms | 1,730 ms | 2,117 ms |
| Latency p95 | 1,638 ms | 2,959 ms | 4,348 ms |

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
