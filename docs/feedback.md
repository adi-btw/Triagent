# Reviewer feedback and the eval loop

The labelled eval set is how Triagent measures itself, and it only covers the incidents
someone thought to write. Reviewer feedback adds the incidents people actually triage:

```
triage ──▶ reviewer rates it ──▶ feedback DB ──▶ report: what to fix next
                                            └──▶ candidate eval cases ──▶ human review ──▶ cases.jsonl
                                                                                           │
                         prompt / retrieval / model change ◀── run_eval measures it ◀──────┘
```

Code: `app/feedback.py` (store), `POST /feedback` in `app/main.py`, the feedback card in
`app/static/`, and `eval/feedback.py` (report and export). Tests: `tests/test_feedback.py`.

## What a reviewer does

After every report, the demo UI asks **"Was this triage right?"**

* **Looks right** records a thumbs-up.
* **Something's wrong** opens a short form. Every field is optional, and each one maps
  onto an eval label:

| Form field | Becomes |
|---|---|
| Correct severity | `expected_severity` |
| "The runbooks don't cover this" | `should_abstain` (category `insufficient_evidence`) |
| Citations that don't support their claim | removed from `expected_chunk_ids`; counted in the report |
| Comment | the case's `notes` |

The API is `POST /feedback` with `{triage_id, rating: "up"|"down", correct_severity?,
should_abstain?, wrong_citations?, comment?}`. It returns 201, 404 for an unknown triage,
or 503 when feedback is disabled. Posting again for the same triage replaces the earlier
verdict.

## Design decisions

**The server records what it showed.** Every `/triage` and `/triage/stream` response
carries a `triage_id`. The server has already stored the incident, mode, model, prompt
versions, report and cited ids under that id. Feedback refers to the id. It never carries
the report back, so a client can't rate a report the system didn't produce, or attach a
correction to the wrong prompt version. Recording can fail (disk full, locked database).
When it does, the triage is still returned, without an id, and the UI hides the card.

**SQLite.** One file, in the standard library, transactional, readable with any SQL tool.
One connection per operation, and WAL mode, make it safe under FastAPI's thread pool. At
one row per human request, a database server adds nothing. Several replicas would need
Postgres, behind the same three methods.

**Bounded, and labelled data survives.** `FEEDBACK_MAX_TRIAGES` (default 20,000) caps the
table. Eviction removes the oldest triages *without* feedback, so the public demo can't
fill its disk and nothing a reviewer labelled is lost.

**Feedback doesn't edit the eval set directly.** `export-cases` writes candidates to
`data/eval/feedback_candidates.jsonl`. Each candidate passes the same `EvalCase`
validation as hand-written cases, and a person reads it before appending it to
`cases.jsonl`. One mis-click shouldn't change the benchmark the next model is judged on.
Incidents already in the eval set are skipped, matched on normalised text. If an incident
was reviewed twice, the later verdict wins.

**A thumbs-down with no correction isn't a label.** It says something is wrong but not
what. The report counts these as "needs labelling" and they aren't exported. A thumbs-up
on an accepted report *is* a label: the report's own severity and citations become a
regression case for behaviour a reviewer confirmed.

**Privacy.** Incident text is stored, because without it a correction can't become a
case. `FEEDBACK_ENABLED=false` turns off both the recording and the endpoint, for
deployments where incidents must not be kept.

## Using it

```bash
python -m eval.feedback report         # -> eval/results/feedback-latest.md
python -m eval.feedback export-cases   # -> data/eval/feedback_candidates.jsonl
# read the candidates, append the good ones to data/eval/cases.jsonl, then:
python -m eval.run_eval
```

The report covers:

* acceptance rate by mode, model and prompt version, to check whether a prompt change helped;
* severity corrections, split into under-rated and over-rated, since under-rating an
  outage is the costlier mistake;
* missed and wrongful abstentions;
* the chunks most often flagged as not supporting their claim, which points at corpus
  or retrieval fixes rather than prompt fixes.

## Limits

Reviewers are self-selected, so acceptance rate measures the incidents people bothered
to rate, not all traffic. One reviewer's labels aren't ground truth, which is why export
stops at candidates. Slack triage (docs/integrations.md) isn't recorded yet. Rating from
Slack would need interactive buttons and a signed `/slack/interactions` endpoint.
