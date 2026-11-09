# Evaluation report: 20261109T234650Z-6047dbc

> **SMOKE TEST: THESE NUMBERS ARE MEANINGLESS.** This run used a fake LLM (`LLM_PROVIDER=fake`, which pattern-fills reports without reading the incident) and/or a fake keyword-overlap retriever. It only proves the harness runs end to end. Do not quote any number below.

> Produced offline with `LLM_PROVIDER=fake python -m eval.run_eval --modes no_retrieval rag agent --fake-retriever`. The agent column errors because agent mode is not merged on this branch (`AgentNotAvailable`), and the fake LLM used as judge returns no verdicts, so every claim is "unjudged". Both are recorded, not dropped, which is what this file demonstrates.

## Run metadata

- **Run id:** `20261109T234650Z-6047dbc`
- **Timestamp (UTC):** `2026-11-09T23:46:50+00:00`
- **Git sha:** `6047dbc`
- **Uncommitted changes:** `False`
- **LLM provider:** `fake`
- **LLM model:** `fake-demo`
- **Temperature:** `0.0`
- **Prompt versions (from traces):** `triage-v1`
- **Judge enabled:** `True`
- **Judge model:** `fake-demo`
- **Judge prompt version:** `judge-v1`
- **Retriever:** `FAKE keyword-overlap over data/corpus (smoke test only, NOT a real retriever)`
- **Embedder:** `fastembed (BAAI/bge-small-en-v1.5)`
- **Retrieval mode:** `vector`
- **top_k:** `5`
- **cases.jsonl sha256:** `98ea6234094901b5247472171658d9e450c025f2aabc8db088161f589c53bf5a`
- **Corpus sha256:** `c7f509117d894593f36a623aae3aa58537a771bbb625b6063e4f939d295fcdb0`
- **Cases:** `32`
- **Repeats:** `1`
- **Modes:** `no_retrieval, rag, agent`
- **Bootstrap:** `percentile, 2000 resamples over cases, seed 20261109`
- **LLM calls made (generation):** `64`
- **LLM calls made (judge):** `32`

## Comparison

Same LLM in every mode; only the evidence and control flow differ. n = 32 cases (one case is about 3 percentage points). Brackets are 95% bootstrap CIs (2000 resamples over cases). **With this n, differences under ~10 pp are not meaningful, and overlapping intervals mean the data do not separate the modes.**

| Metric | no_retrieval | rag | agent |
|---|---|---|---|
| Results (cases x repeats) | 32 | 32 | 32 |
| Status ok | 100% (32/32) | 100% (32/32) | 0% (0/32) |
| Status invalid_output | 0% (0/32) | 0% (0/32) | 0% (0/32) |
| Status needs_clarification | 0% (0/32) | 0% (0/32) | 0% (0/32) |
| Status error (crashed) | 0% (0/32) | 0% (0/32) | 100% (32/32) |
| Citation validity (no unknown ids) | 100% (32/32) | 100% (32/32) | n/a (n=0) |
| Severity exact [95% CI] | 0% (0/29) [0-0] | 3% (1/29) [0-10] | n/a (n=0) |
| Severity within one level | 0% (0/29) | 14% (4/29) | n/a (n=0) |
| Correct abstention (insufficient_evidence cases) | 100% (7/7) | 71% (5/7) | n/a (n=0) |
| False abstention (answerable cases, lower is better) | 100% (20/20) | 95% (19/20) | n/a (n=0) |
| Abstention accuracy [95% CI] | 26% (7/27) [11-44] | 22% (6/27) [7-37] | n/a (n=0) |
| Retrieval doc recall@k | n/a | 52% (n=29) | n/a |
| Retrieval chunk recall@k | n/a | 49% (n=29) | n/a |
| Cited-doc precision (PROXY vs labels) | n/a (n=0) | 61% (n=29) | n/a (n=0) |
| Claims supported (judge) [95% CI] | n/a (n=0) | n/a (n=0) | n/a |
| Claims partially supported | n/a (n=0) | n/a (n=0) | n/a |
| Claims not supported | n/a (n=0) | n/a (n=0) | n/a |
| Claims unjudged (judge gave no verdict) | 0 | 128 | n/a |
| Clarification rate (ambiguous, agent only) | n/a | n/a | n/a (n=0) |
| Over-asking (unambiguous, agent only) | n/a | n/a | n/a (n=0) |
| Latency p50 | 0 ms | 0 ms | n/a |
| Latency p95 | 0 ms | 1 ms | n/a |
| Latency mean | 0 ms | 0 ms | n/a |
| Mean LLM calls per case (excl. judge) | 1.00 | 1.00 | n/a |
| Mean tokens per case (in+out, if reported) | 130 | 361 | n/a |

## By category

### ambiguous

| Metric | no_retrieval | rag | agent |
|---|---|---|---|
| Results | 5 | 5 | 5 |
| Status ok | 100% (5/5) | 100% (5/5) | 0% (0/5) |
| Status error | 0% (0/5) | 0% (0/5) | 100% (5/5) |
| Severity exact | 0% (0/5) | 0% (0/5) | n/a (n=0) |
| Correct abstention | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| False abstention | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| Doc recall@k | n/a | 20% (n=5) | n/a |
| Claims supported | n/a (n=0) | n/a (n=0) | n/a |
| Clarification rate | n/a | n/a | n/a (n=0) |

### answerable

| Metric | no_retrieval | rag | agent |
|---|---|---|---|
| Results | 20 | 20 | 20 |
| Status ok | 100% (20/20) | 100% (20/20) | 0% (0/20) |
| Status error | 0% (0/20) | 0% (0/20) | 100% (20/20) |
| Severity exact | 0% (0/20) | 5% (1/20) | n/a (n=0) |
| Correct abstention | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| False abstention | 100% (20/20) | 95% (19/20) | n/a (n=0) |
| Doc recall@k | n/a | 60% (n=20) | n/a |
| Claims supported | n/a (n=0) | n/a (n=0) | n/a |
| Clarification rate | n/a | n/a | n/a (n=0) |

### insufficient_evidence

| Metric | no_retrieval | rag | agent |
|---|---|---|---|
| Results | 7 | 7 | 7 |
| Status ok | 100% (7/7) | 100% (7/7) | 0% (0/7) |
| Status error | 0% (0/7) | 0% (0/7) | 100% (7/7) |
| Severity exact | 0% (0/4) | 0% (0/4) | n/a (n=0) |
| Correct abstention | 100% (7/7) | 71% (5/7) | n/a (n=0) |
| False abstention | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| Doc recall@k | n/a | 50% (n=4) | n/a |
| Claims supported | n/a (n=0) | n/a (n=0) | n/a |
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
| SEV2 | 0 | 1 | 0 | 0 | 9 |
| SEV3 | 0 | 3 | 0 | 0 | 9 |
| SEV4 | 0 | 0 | 0 | 0 | 3 |

### agent

_No labelled cases with a parsed report._

## Failed and erroring cases

### rag (32)

| case | repeat | status | detail |
|---|---|---|---|
| case-001 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-002 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-003 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-004 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-005 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-006 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-007 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-008 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-009 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-010 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-011 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-012 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-013 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-014 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-015 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-016 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-017 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-018 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-019 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-020 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-021 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-022 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-023 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-024 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-025 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-026 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-027 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-028 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-029 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-030 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-031 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |
| case-032 | 0 | ok | judge: judge returned no verdict for claim ids [0, 1, 2, 3] |

### agent (32)

| case | repeat | status | detail |
|---|---|---|---|
| case-001 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-002 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-003 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-004 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-005 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-006 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-007 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-008 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-009 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-010 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-011 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-012 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-013 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-014 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-015 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-016 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-017 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-018 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-019 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-020 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-021 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-022 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-023 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-024 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-025 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-026 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-027 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-028 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-029 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-030 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-031 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |
| case-032 | 0 | error | `AgentNotAvailable`: mode='agent' is not implemented yet (stage 2) |

## How to read this

- **Every rate shows k/n.** Quality rows (severity, abstention, citations, claims) only count results with a parsed report; check the status rows to see how many were dropped from them. Errors are never silently removed.
- **Severity exact** compares to a single labeller's reading of POL-SEV-001; *within one level* shows whether misses are near-misses.
- **Citation validity** only proves cited ids were retrieved. **Claims supported** is an LLM judge's opinion that the cited passage backs the claim; it has its own error rate and should be calibrated against a human spot-check. In `no_retrieval` every claim is not supported by construction (no passages).
- **Cited-doc precision** is a cheap label-based proxy: it penalises citing a sensible doc the labeller did not list.
- **Recall@k** measures retrieval, not the answer: a mode can retrieve the right doc and still misread it.
- **Latency** excludes judge calls; p95 over ~30 samples is about the second-slowest case.
- The corpus and the eval cases were written by the same author, so retrieval numbers are likely optimistic compared with real tickets.
- n = 32: treat differences under ~10 pp as noise and read the CIs.
