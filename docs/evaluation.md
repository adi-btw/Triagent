# Evaluation

How the project measures whether retrieval and the agent loop actually help, what each
number means, and what it does **not** mean. Code: `eval/`. Labels: `data/eval/cases.jsonl`
(see `data/eval/README.md`). Example output (fake LLM, meaningless numbers):
`eval/results/example-smoke.md`.

## 1. What is compared, and why the same model

Three modes run on the same 32 labelled incidents:

| Mode | What the model gets | Can it ask a question? |
|---|---|---|
| `no_retrieval` | the incident only | no |
| `rag` | the incident + top-k retrieved chunks (one fixed retrieve-generate-validate pass) | no |
| `agent` | the incident; the agent decides to retrieve, rewrite the query, or ask | yes (max 1) |

Every mode uses **the same LLM, temperature, and output schema**, and goes through the same
public entry point (`app.triage.service.run_triage`) as the API. Holding the model fixed is
what makes this an experiment: if `rag` beats `no_retrieval`, the only thing that changed is
the evidence, so the difference is attributable to retrieval, not to a better model. Comparing
"GPT-x with RAG" to "Gemini without" would confound two variables.

`no_retrieval` is the control group. It is *expected* to fail grounding metrics (it has
nothing to cite); its value is showing how much of the severity/abstention behaviour comes
from the model's prior knowledge alone.

## 2. Metrics: definition and what each does NOT measure

Every rate is reported as `value (k/n)`. A rate with `n = 0` prints `n/a`, never 0% or 100%.
Quality metrics are computed only over results with a parsed report; validity metrics count
every result. Read both: a mode that crashes on half the cases and is perfect on the rest
has a high accuracy over a small n and a bad validity row.

| Metric | Definition | Does NOT measure |
|---|---|---|
| **Output validity** | Share of results per final status: `ok`, `invalid_output` (any validator violation), `needs_clarification` (ended with a question), `error` (exception: rate limit, timeout, `AgentNotAvailable`). Plus violation counts by type. | Whether a valid report is *correct*. |
| **Citation validity** | Share of parsed reports with zero `unknown_citation` violations (only cited ids that were retrieved). | Whether the cited passage supports the claim, or is the right doc. |
| **Severity exact / within-one** | Predicted == labelled SEV, over cases with a label and a parsed report. A null prediction is wrong. Within-one counts SEV2 vs SEV3 as a near miss. Confusion matrix shows the direction of errors. | Whether the *reasoning* was right (right SEV for the wrong reason counts). Labels are one person's reading of POL-SEV-001. |
| **Retrieval recall@k** (rag/agent) | Per case, share of `expected_doc_ids` whose doc appears in `trace.retrieved` (doc = chunk id before `#`); also chunk-level vs `expected_chunk_ids`. Mean over cases with labels. | Whether the model *used* the retrieved text. Expected docs are a floor, not the only right answer. |
| **Cited-doc precision (PROXY)** | Per report, share of cited doc ids that are in `expected_doc_ids`. | Grounding. It penalises a sensible extra doc and rewards citing the right doc for the wrong claim. A cheap sanity check only. |
| **Claim support (judge)** | Each likely cause and next step is a claim. An LLM judge sees the claim text and the full text of its cited passages and returns `supported` / `partially_supported` / `not_supported` with a one-sentence reason. Claims with no citations, or whose ids have no passage, are `not_supported` by rule. Share of claims, CI resampling reports. | Truth in the world: a claim faithfully supported by a wrong runbook is "supported". Also inherits the judge's own errors (section 3). |
| **Abstention** | On `insufficient_evidence` cases: share with `insufficient_evidence=true` (correct abstention). On answerable cases: share abstaining (false abstention, lower is better). Abstention accuracy: decision == `should_abstain` over both categories (ambiguous cases excluded, see section 5). | Whether the `missing_information` it lists is sensible. |
| **Clarification / over-asking** (agent) | Share of ambiguous cases where the agent asked; share of unambiguous cases where it asked anyway. | Question quality. The scripted answer is fed back regardless of what was asked. |
| **Latency, calls, tokens** | p50/p95/mean of `trace.timings_ms.total` summed over all calls for the case (wall time if missing), mean LLM calls, mean tokens. Errors and judge calls excluded. | Production latency: free-tier queueing and network noise dominate, and p95 over 32 samples is roughly the second-slowest case. |

### Retrieval-only evaluation (no LLM)

`python -m eval.retrieval_eval` scores the retriever alone in `vector`, `keyword` and
`hybrid` modes: doc recall@k, chunk recall@k, **primary-doc hit@k** (the first non-policy
expected doc, usually the runbook that explains the cause; POL-SEV-001 is excluded because it
is expected almost everywhere and inflates doc recall) and chunk-level **MRR** (1 / rank of
the first expected chunk). Ambiguous cases are scored twice, on the vague text and on
incident + clarification. `insufficient_evidence` cases whose expected docs are `[]` or only
the policy are listed separately with what each mode returned: a retriever always returns k
chunks, which is why abstention is the generator's job. It costs zero LLM calls, so run it
first: when end-to-end scores are bad, it tells you whether the evidence was never found
(retrieval problem) or found and misread (generation problem). The demo incident is a known
example: vector search misses RB-DB-001 in the top 5 and hybrid recovers it; this tool shows
whether that pattern holds across all cases. Output: `eval/results/retrieval-latest.md`.

## 3. LLM-as-judge pitfalls

The judge is a measuring instrument with its own error rate. Known biases and what the
harness does about them:

- **Self-preference.** Models rate text in their own style higher. `JUDGE_MODEL` defaults to
  the generation model for convenience; set it to a *different*, ideally stronger, model for
  any result you publish, and record it (it is in the report metadata).
- **Position bias.** Judges favour items early (or late) in a list. Claims are batched in
  report order; a stronger design randomises order or judges claims one at a time (more calls).
- **Verbosity bias.** Longer claims look more "supported". The judge never sees the summary
  or the rest of the report, only the claim and its passages, which limits this.
- **Blinding.** The judge is not told which mode produced the claim.
- **Hidden context.** Claims mention incident details (pod counts) that the passages cannot
  contain. The rubric says not to penalise those, which makes `partially_supported` fuzzy.
- **Calibration is mandatory.** Before trusting the number, a human should label ~20
  verdicts (sample across modes and verdicts from `raw.jsonl`, field `claims`), compare, and
  record the agreement rate (and Cohen's kappa if you want chance-corrected agreement) next to
  the result. If agreement is low, the claim-support row is not evidence of anything.
- **Unjudged claims** (judge returned nothing for a claim, or the call failed) are excluded
  from the denominator and counted in their own row, never silently scored.

For `no_retrieval` every claim is `not_supported` *by construction*: there are no passages.
That is not a flaw in the baseline score; it is the point of the baseline.

## 4. Small-n statistics and bootstrap CIs

32 cases means one case is about 3 percentage points; within the 20 answerable cases it is
5 points. The report shows 95% **bootstrap** confidence intervals for severity accuracy,
abstention accuracy and claim support:

1. Resample the cases with replacement, 2000 times (seeded, so the CI is reproducible).
2. Recompute the metric each time.
3. Take the 2.5th and 97.5th percentiles.

Two details matter. The resampling unit is the **case** (with `--repeats`, all repeats of a
case move together; for claim support, all claims of a report move together), because
claims within one report, or repeats of one case, are correlated and are not independent
evidence. And the bootstrap makes no normal-approximation assumption, which matters near 0%
or 100%. It does **not** fix small n: at 80% accuracy on 32 cases the interval is roughly
±14 points. Rule of thumb in the report: **differences under ~10 pp are not meaningful**,
and overlapping intervals mean the data do not separate the modes. The modes run on the same
cases, so a paired comparison (e.g. McNemar on per-case correctness) would be more powerful;
`raw.jsonl` has everything needed for it.

## 5. The ambiguous-case asymmetry

Five cases are deliberately vague ("Users are complaining about errors."), and their labels
describe the incident *after* a human answers a clarifying question.

- `agent`: if it returns `needs_clarification`, the harness records that it asked, resubmits
  the same incident with the case's scripted `clarification`, and scores the final response.
  Latency and LLM calls add up over both calls.
- `no_retrieval` / `rag`: they cannot ask, so they run on the vague text alone and are scored
  against post-clarification labels. They are expected to do poorly; that gap is what the
  category measures.
- An agent that asks on an unambiguous case gets no scripted answer; that result stays
  `needs_clarification` (no report) and counts as over-asking.

So the ambiguous-category comparison is not apples to apples, by design. Abstention accuracy
excludes ambiguous cases, since abstaining on "the site feels slow" is defensible for a mode
that cannot ask. Also note the scripted answers are cleaner than real users' replies.

## 6. Data leakage and other threats to validity

- **Same author for corpus and eval cases.** Incident wording overlaps the runbooks more than
  real tickets would, so retrieval (especially keyword) scores are likely optimistic. The
  near-miss distractors in the corpus (`docs/corpus.md`) partly counter this.
- **Single labeller**, no adjudication; reasons are in each case's `notes`.
- **Prompt/label co-evolution.** If you tune prompts by looking at these 32 cases, the score
  stops being a held-out estimate. Keep a few cases aside or write new ones before claiming
  generalisation.
- **Non-determinism.** Temperature 0 is not bit-for-bit reproducible on hosted models; use
  `--repeats 3` to see run-to-run variance before reading small differences.
- **Run metadata** pins what produced each number: git sha + dirty flag, model, temperature,
  prompt versions from the traces, judge model and prompt version, embedder, retrieval mode,
  top_k, sha256 of `cases.jsonl` and of the corpus, case count, repeats.

## 7. Reproduce

Prerequisites: `.env` with `GEMINI_API_KEY`, the index built (`python -m scripts.ingest`),
and a model your key can call (`GEMINI_MODEL`).

PowerShell (Windows):

```powershell
.venv\Scripts\python.exe -m scripts.ingest
.venv\Scripts\python.exe -m eval.retrieval_eval --modes vector keyword hybrid --k 5
$env:JUDGE_MODEL = "<stronger model>"   # optional: a different, stronger judge
.venv\Scripts\python.exe -m eval.run_eval --modes no_retrieval rag agent --delay 7
# quick check on two cases, no judge:
.venv\Scripts\python.exe -m eval.run_eval --modes rag --cases case-001,case-005 --no-judge
# offline smoke test (fake LLM, fake retriever; numbers meaningless):
$env:LLM_PROVIDER = "fake"; .venv\Scripts\python.exe -m eval.run_eval --fake-retriever --out .cache/smoke
```

bash:

```bash
python -m scripts.ingest
python -m eval.retrieval_eval --modes vector keyword hybrid --k 5
JUDGE_MODEL=<stronger-model> python -m eval.run_eval --modes no_retrieval rag agent --delay 7
python -m eval.run_eval --modes rag --cases case-001,case-005 --no-judge
LLM_PROVIDER=fake python -m eval.run_eval --fake-retriever --out .cache/smoke
```

Options: `--limit N` (first N cases), `--repeats N`, `--out DIR`, `--judge/--no-judge`.
Outputs: `eval/results/runs/<run_id>/raw.jsonl` and `summary.json` (gitignored), and
`eval/results/<run_id>.md` + `eval/results/latest.md` (commit the one you cite). `run_id` is
`<UTC timestamp>-<short git sha>`. Per-case exceptions never stop the run; they are recorded
with type and message. `raw.jsonl` is written line by line, so an interrupted run keeps its
results.

### Expected LLM calls and cost per full run (32 cases, 3 modes, judge on)

| Part | Calls |
|---|---|
| `no_retrieval` | 32 x 1 = 32 |
| `rag` | 32 x 1 = 32 |
| `agent` | 32 x ~2-5 (decide/retrieve/rewrite steps, capped by `AGENT_MAX_STEPS=4`, + generate) + 5 resubmitted ambiguous cases x ~2-5 = **~75-185** |
| judge | at most 1 per report with a cited claim: ~32 (rag) + ~32 (agent); 0 for `no_retrieval` = **~64** |
| **Total** | **~200-315 calls** |

Roughly 1.5-2.5k input and 0.3-0.5k output tokens per generation call, about 1-2k input per
judge call, so a full run is on the order of 0.5M input and 0.1M output tokens. At paid
Flash-class prices that is cents to well under a dollar; check the provider's current price
list. The real constraint is the **free-tier rate limit** (requests per minute and per day):
`--delay 7` keeps you under ~10 requests/minute. The daily cap matters more: on the free tier,
`gemini-3.8-flash` allows **20 requests per day** (measured 2026-11-09), so a full run needs a
paid-tier key. On the free tier, run a slice per day with `--cases` / `--modes` and
`--no-judge`, or switch `GEMINI_MODEL` to a model with a higher free quota and record that. The
summary records the actual `llm_calls_total` and `judge_calls_total`, so replace these
estimates with measured numbers after the first real run. `retrieval_eval` costs 0 calls.

## 8. Results section template (paste into README)

```markdown
## Results

Same model (`<model>`, temperature 0) in every mode; 32 hand-labelled incidents
(20 answerable, 7 insufficient-evidence, 5 ambiguous). Judge: `<judge model>`, human
agreement on 20 spot-checked verdicts: <x>/20. Full report: `eval/results/<run_id>.md`.

| Metric | no_retrieval | rag | agent |
|---|---|---|---|
| Valid output | | | |
| Severity exact [95% CI] | | | |
| Correct abstention (7 cases) | | | |
| False abstention (20 cases) | | | |
| Doc recall@5 | n/a | | |
| Claims supported by cited text [95% CI] | 0% by construction | | |
| Clarification rate (5 ambiguous) | n/a | n/a | |
| p50 / p95 latency | | | |

Caveats: n = 32, so differences under ~10 pp are not meaningful; corpus and cases share an
author (retrieval likely optimistic); claim support is an LLM judgement calibrated on 20
human labels; ambiguous cases favour the agent by design.
```

## Design FAQ

1. **Why run the same model in all three modes?** To isolate the variable. With the model,
   temperature, schema and validator fixed, a difference between `no_retrieval` and `rag` can
   only come from the evidence; between `rag` and `agent`, from the control flow.
2. **Citation validity is 100%; is the system grounded?** No. It proves every cited id was
   retrieved. Whether the passage supports the claim is claim support, measured by a
   calibrated LLM judge; whether the conclusion is right is severity/abstention vs labels.
3. **How do you know the judge is right?** You don't by default. A human labels ~20 verdicts
   and we report agreement; we use a different (stronger) judge model to reduce
   self-preference, show it only claim + passages (blind to mode, no summary), and count
   unjudged claims instead of hiding them.
4. **RAG scores 75% and agent 80%. Is the agent better?** Not shown. One case is ~3 pp, the
   95% bootstrap intervals are ~±15 pp and overlap. I would say "no measurable difference at
   n = 32", run `--repeats` to check variance, use a paired test, and add cases before
   claiming anything.
5. **Why are errors counted instead of skipped?** Because dropping them biases every quality
   metric upward: a mode that crashes on hard cases would look accurate on the easy ones it
   survived. Errors stay in the validity row with their type, and quality rows show their n.
