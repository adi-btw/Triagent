# Evaluation set

`cases.jsonl` holds 32 hand-labelled incidents, one JSON object per line. The eval harness
runs each case through a triage mode (`no_retrieval`, `rag`, `agent`) and compares the
report with these labels.

## Fields

| Field | Meaning |
|---|---|
| `id` | `case-NNN`, unique and stable. `case-001` is exactly `data/demo_incident.txt`. |
| `category` | `answerable`, `insufficient_evidence` or `ambiguous` (see below). |
| `incident` | What the user pastes: a short report plus 2-6 log lines. Written as an on-call engineer would write it, not copied from the corpus. |
| `expected_severity` | `SEV1`-`SEV4` per POL-SEV-001, or `null` when the incident lacks the facts the policy needs. |
| `expected_doc_ids` | Docs a good answer should cite. Used for document-level recall. |
| `expected_chunk_ids` | The most important sections inside those docs. Used for chunk-level recall@k / MRR. Every chunk's doc is also in `expected_doc_ids`. |
| `should_abstain` | `true` means the report should set `insufficient_evidence: true` (no grounded cause). |
| `clarification` | For `ambiguous` cases only: the answer a human would give to a clarifying question. `null` otherwise. |
| `notes` | Why the labels are what they are, especially non-obvious severities and near-miss docs. |

## Categories

- **answerable (20)**: the corpus contains the runbook and/or past incident that explains the
  cause. `should_abstain=false`. 1-4 expected docs, nearly always including `POL-SEV-001`
  because the severity claim itself must cite the policy.
- **insufficient_evidence (7)**: the incident is about a topic the corpus deliberately does not
  cover (message-queue lag, Elasticsearch, mobile crashes, ISP routing, GPU serving; see
  `docs/corpus.md`). `should_abstain=true`. `expected_doc_ids` is `[]` or `["POL-SEV-001"]`.
  Severity is still labelled when the incident states a service and an error rate, because
  the schema allows "severity known, cause unknown".
- **ambiguous (5)**: too vague to triage ("the site feels slow"). The agent mode should ask a
  clarifying question; the harness then feeds `clarification` back. All `expected_*` labels
  describe the incident *after* clarification. `rag` mode, which cannot ask, is expected to
  do poorly here; that difference is the point of the category.

Severity distribution: SEV1 4, SEV2 10, SEV3 12, SEV4 3, null 3.

## Labelling rubric

1. **Severity** follows POL-SEV-001 literally:
   - Revenue paths are only checkout-api, payments-api and cart-api.
   - SEV1: revenue path fully unavailable or >50% errors (or data loss / security exposure).
   - SEV2: revenue path 5-50% errors, or p95 > 3x baseline.
   - SEV3: non-revenue service degraded (any error rate), or revenue path <5% errors.
   - SEV4: no customer impact.
   Operational urgency does not override the policy: a disk at 92% with no impact is SEV4
   (case-003); 15% errors on inventory-api is SEV3 (case-020) even though the same root cause
   on checkout-api is SEV2 (case-001).
2. **Docs**: the runbook that explains diagnosis/mitigation, plus the past incident when one
   matches the pattern closely, plus the policy. A doc that is merely related is not expected
   (citing it is not penalised by recall, only by precision if you measure it).
3. **Chunks**: the 2-4 sections an engineer would actually need: usually Symptoms or Diagnosis
   to confirm the cause and Mitigation for next steps; Root cause for incidents; `Levels`
   (`#s1`) or `Revenue paths` (`#s2`) of the policy, whichever decides the severity.
4. **Near misses** are called out in `notes` (for example case-004 shares the
   `pool.acquire timed out after 5000ms` line with case-001 but is lock contention).

## How chunk IDs are derived

`f"{doc_id}#s{n}"` where `n` is the 1-based index of the doc's `## ` heading (see the comment
at the top of `app/schemas.py`). Text before the first `## ` is not a chunk. For example
`RB-DB-001.md` has `## Symptoms`, `## Diagnosis`, `## Mitigation`, so `RB-DB-001#s3` is
Mitigation. `tests/test_corpus.py` recomputes this from the files and fails if a label points
to a section that does not exist, so do not reorder or insert `## ` sections in existing docs;
append new sections at the end.

## Limitations

- **Synthetic.** The incidents and the corpus were written by the same author, so wording
  overlaps more than real tickets and runbooks would. Retrieval scores are likely optimistic.
- **Single labeller, no adjudication.** Some labels are judgement calls (case-013: is a
  sitewide image outage "non-revenue degraded"?). The reasoning is in `notes` so it can be
  challenged.
- **Small n.** With 32 cases, one case is about 3 percentage points; with 20 answerable cases
  it is 5 points. A 95% confidence interval on an 80% accuracy over 32 cases is roughly
  ±14 points, so differences of a few points between modes are noise. Report counts
  alongside percentages.
- **Expected docs are a floor, not the only right answer.** A model citing a reasonable
  extra doc is not wrong; chunk recall measures whether the key evidence was found, not
  whether the answer matched a single gold citation list.
- **Ambiguous clarifications are scripted.** Real users answer clarifying questions less
  precisely.
