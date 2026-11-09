# Retrieval evaluation: 20261109T234925Z-b466541-retrieval

- **run_id:** `20261109T234925Z-b466541-retrieval`
- **timestamp_utc:** `2026-11-09T23:49:25+00:00`
- **git_sha:** `b466541`
- **git_dirty:** `False`
- **retriever:** `SearchRetriever`
- **injected_retriever:** `False`
- **store_backend:** `memory`
- **embedder:** `fastembed (BAAI/bge-small-en-v1.5)`
- **k:** `5`
- **modes:** `['vector', 'keyword', 'hybrid']`
- **cases_sha256:** `98ea6234094901b5247472171658d9e450c025f2aabc8db088161f589c53bf5a`
- **corpus_sha256:** `c7f509117d894593f36a623aae3aa58537a771bbb625b6063e4f939d295fcdb0`
- **n_cases_scored:** `25`
- **n_cases_skipped:** `7`

## Overall

Answerable + insufficient_evidence cases with a non-policy expected doc + ambiguous cases *with* clarification. Brackets: 95% bootstrap CI over cases. k = 5. Same cases and labels for every mode, so differences are paired; still, with ~25 cases a gap under ~10 pp is not meaningful.

| Metric | vector | keyword | hybrid |
|---|---|---|---|
| Doc recall@k | 52% (n=25) [44-59] | 61% (n=25) [55-67] | 59% (n=25) [55-64] |
| Chunk recall@k | 53% (n=25) [41-65] | 66% (n=25) [56-75] | 61% (n=25) [52-70] |
| Primary-doc hit@k | 88% (n=25) [72-100] | 100% (n=25) [100-100] | 100% (n=25) [100-100] |
| MRR (chunk level) | 71% (n=25) [56-86] | 80% (n=25) [68-91] | 78% (n=25) [65-90] |
| Retriever errors (scored as 0) | 0 | 0 | 0 |

## Doc recall@k by slice

| Slice | vector | keyword | hybrid |
|---|---|---|---|
| answerable | 53% (n=20) | 60% (n=20) | 57% (n=20) |
| insufficient_evidence | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| ambiguous (vague) | 20% (n=5) | 33% (n=5) | 40% (n=5) |
| ambiguous (+clarification) | 47% (n=5) | 67% (n=5) | 67% (n=5) |

## Chunk recall@k by slice

| Slice | vector | keyword | hybrid |
|---|---|---|---|
| answerable | 53% (n=20) | 65% (n=20) | 60% (n=20) |
| insufficient_evidence | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| ambiguous (vague) | 20% (n=5) | 27% (n=5) | 33% (n=5) |
| ambiguous (+clarification) | 53% (n=5) | 67% (n=5) | 67% (n=5) |

## Primary-doc hit@k by slice

| Slice | vector | keyword | hybrid |
|---|---|---|---|
| answerable | 90% (n=20) | 100% (n=20) | 100% (n=20) |
| insufficient_evidence | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| ambiguous (vague) | 40% (n=5) | 60% (n=5) | 60% (n=5) |
| ambiguous (+clarification) | 80% (n=5) | 100% (n=5) | 100% (n=5) |

## MRR (chunk level) by slice

| Slice | vector | keyword | hybrid |
|---|---|---|---|
| answerable | 73% (n=20) | 75% (n=20) | 75% (n=20) |
| insufficient_evidence | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| ambiguous (vague) | 20% (n=5) | 16% (n=5) | 30% (n=5) |
| ambiguous (+clarification) | 67% (n=5) | 100% (n=5) | 90% (n=5) |

## Primary doc rank per case

Rank of the first chunk from the primary doc (blank = not in top k).

| Case | Slice | Primary doc | vector | keyword | hybrid |
|---|---|---|---|---|---|
| case-001 | answerable | RB-DB-001 |  | 2 | 4 |
| case-002 | answerable | RB-DB-002 | 4 | 2 | 3 |
| case-003 | answerable | RB-DB-003 | 2 | 1 | 1 |
| case-004 | answerable | RB-DB-004 | 2 | 1 | 2 |
| case-005 | answerable | RB-CACHE-001 | 2 | 2 | 3 |
| case-006 | answerable | RB-TLS-001 | 5 | 3 | 3 |
| case-007 | answerable | RB-DEPLOY-001 | 1 | 1 | 1 |
| case-008 | answerable | RB-K8S-001 | 1 | 1 | 1 |
| case-009 | answerable | RB-K8S-001 | 1 | 1 | 1 |
| case-010 | answerable | RB-K8S-002 | 1 | 1 | 1 |
| case-011 | answerable | RB-PAY-001 | 1 | 1 | 1 |
| case-012 | answerable | RB-AUTH-001 | 3 | 2 | 3 |
| case-013 | answerable | RB-CDN-001 | 1 | 1 | 1 |
| case-014 | answerable | RB-NET-003 | 1 | 1 | 1 |
| case-015 | answerable | RB-APP-001 | 2 | 3 | 2 |
| case-016 | answerable | RB-CACHE-001 | 1 | 3 | 1 |
| case-017 | answerable | RB-NET-002 | 1 | 1 | 1 |
| case-018 | answerable | RB-TLS-001 | 1 | 1 | 1 |
| case-019 | answerable | RB-PAY-001 | 1 | 1 | 1 |
| case-020 | answerable | RB-DB-001 |  | 2 | 4 |
| case-028 | ambiguous (vague) | RB-K8S-002 |  |  |  |
| case-028 | ambiguous (+clarification) | RB-K8S-002 | 3 | 1 | 1 |
| case-029 | ambiguous (vague) | RB-AUTH-001 |  | 4 |  |
| case-029 | ambiguous (+clarification) | RB-AUTH-001 | 2 | 2 | 2 |
| case-030 | ambiguous (vague) | RB-DB-003 |  |  | 2 |
| case-030 | ambiguous (+clarification) | RB-DB-003 | 1 | 1 | 1 |
| case-031 | ambiguous (vague) | RB-DEPLOY-001 | 2 | 2 | 1 |
| case-031 | ambiguous (+clarification) | RB-DEPLOY-001 |  | 1 | 5 |
| case-032 | ambiguous (vague) | RB-PAY-001 | 2 | 5 | 2 |
| case-032 | ambiguous (+clarification) | RB-PAY-001 | 1 | 1 | 1 |

## Not scored (nothing case-specific to retrieve)

insufficient_evidence cases whose expected docs are [] or only POL-SEV-001. Shown so you can see that the retriever still returns k chunks for them: recognising that those chunks do not explain the incident is the generator's job (abstention).

- **case-021** (expected ['POL-SEV-001']):
  - vector: INC-2025-040#s1, INC-2025-014#s1, INC-2025-040#s3, INC-2025-021#s3, INC-2025-021#s1
  - keyword: POL-SEV-001#s2, INC-2025-040#s1, INC-2026-009#s1, INC-2025-040#s2, INC-2026-009#s2
  - hybrid: INC-2025-040#s1, INC-2026-009#s1, INC-2025-040#s2, INC-2025-040#s3, RB-DB-002#s1
- **case-022** (expected ['POL-SEV-001']):
  - vector: INC-2025-021#s3, INC-2025-021#s2, RB-CACHE-001#s2, RB-CACHE-001#s1, INC-2025-021#s1
  - keyword: INC-2025-014#s1, POL-SEV-001#s2, INC-2026-022#s1, INC-2026-015#s3, INC-2026-011#s3
  - hybrid: INC-2025-021#s3, INC-2025-021#s2, INC-2026-015#s3, INC-2026-011#s3, INC-2026-022#s2
- **case-023** (expected []):
  - vector: RB-K8S-001#s3, RB-K8S-001#s1, INC-2026-015#s2, RB-APP-001#s2, INC-2026-015#s1
  - keyword: INC-2026-015#s1, RB-DEPLOY-001#s4, INC-2026-011#s2, RB-APP-001#s2, RB-DB-002#s2
  - hybrid: INC-2026-015#s1, RB-APP-001#s2, RB-K8S-001#s1, RB-K8S-001#s2, INC-2026-011#s1
- **case-024** (expected []):
  - vector: INC-2026-011#s1, INC-2026-011#s2, RB-NET-002#s2, RB-PAY-001#s2, INC-2026-003#s2
  - keyword: RB-NET-003#s1, INC-2025-014#s1, RB-PAY-001#s2, RB-PAY-001#s3, RB-DEPLOY-001#s1
  - hybrid: RB-PAY-001#s2, RB-NET-003#s1, POL-SEV-001#s1, RB-NET-003#s2, RB-K8S-002#s1
- **case-025** (expected ['POL-SEV-001']):
  - vector: INC-2026-015#s1, INC-2025-021#s2, INC-2025-021#s3, INC-2026-015#s2, INC-2025-014#s2
  - keyword: INC-2025-021#s2, INC-2026-015#s1, INC-2025-021#s3, INC-2026-011#s2, INC-2026-015#s3
  - hybrid: INC-2025-021#s2, INC-2026-015#s1, INC-2025-021#s3, INC-2026-015#s2, INC-2025-014#s2
- **case-026** (expected ['POL-SEV-001']):
  - vector: INC-2025-040#s2, INC-2025-040#s3, INC-2026-011#s2, INC-2025-014#s2, INC-2025-040#s1
  - keyword: INC-2025-014#s1, INC-2026-011#s1, INC-2025-014#s2, INC-2025-021#s1, INC-2026-009#s1
  - hybrid: INC-2025-014#s1, INC-2025-014#s2, INC-2026-011#s2, INC-2026-011#s1, INC-2025-021#s1
- **case-027** (expected []):
  - vector: RB-DB-001#s3, INC-2025-021#s2, RB-NET-003#s1, RB-CACHE-001#s2, RB-DB-001#s2
  - keyword: INC-2026-003#s3, INC-2026-015#s2, RB-K8S-002#s3, RB-PAY-001#s2, RB-CACHE-001#s2
  - hybrid: RB-NET-003#s1, RB-CACHE-001#s2, INC-2026-015#s2, RB-K8S-002#s3, RB-NET-003#s2

## Caveats

- Recall says the passage was *retrieved*, not that the model used it well.
- Labels and corpus share an author; absolute numbers are optimistic.
- Expected docs are a floor: a sensible extra doc lowers nothing here, but a near-miss distractor ranked above the right doc pushes it out of the top k.
