# The agent (stage 2)

Stage 1 RAG always runs the same three steps: retrieve, generate, validate. Stage 2 lets
the model choose a few extra steps when they would help: search again with a better query,
or stop and ask the reporter a question. It is still a small, bounded workflow, not an
open-ended "use tools until you're done" loop.

Files: `app/agent/schemas.py` (`AgentDecision`), `app/agent/prompts.py` (decide and repair
prompts, `AGENT_PROMPT_VERSION`), `app/agent/workflow.py` (`run_agent`), wired in
`app/triage/service.py` for `mode="agent"`. Tests: `tests/test_agent.py`,
`tests/test_agent_api.py`. Demo UI: `app/static/`.

```python
run_agent(incident: str, *, retriever: Retriever, llm: LLMClient, settings: Settings,
          clarification_given: bool) -> TriageResponse

class AgentDecision(BaseModel):
    action: Literal["draft_report", "rewrite_query", "ask_clarifying_question"]
    rationale: str                     # at most 2 sentences, shown in the UI
    rewritten_query: str | None        # required iff action == "rewrite_query"
    clarifying_question: str | None    # required iff action == "ask_clarifying_question"
```

## 1. The model decides, the application enforces

This split is the main design choice. The model is good at judgement ("this evidence is
about Redis, but the incident is about Postgres"). It is not reliable at following rules
("never more than one rewrite"), and a rule that only holds most of the time is not a rule.
So every rule lives in code, and the model chooses only among actions the code allows.

| Concern | Who | Why |
|---|---|---|
| Which action next: draft, rewrite, ask | **Model** | Needs judgement about relevance and vagueness. This is the only thing the model controls. |
| Wording of the rewritten query / question | **Model** | Language work. |
| Short rationale for the choice | **Model** | Explains the step in the UI and the trace. Trimmed to 2 sentences in code, not rejected. |
| Total LLM calls per request (`agent_max_steps`, default 4) | **App** | Fixed cost and latency ceiling. A new `decide` call is only made if room is left for the draft and one repair. |
| Number of rewrites (`agent_max_query_rewrites`, default 1) | **App** | Each rewrite costs a retrieval and a decide call. Diminishing returns after one. |
| Clarifying questions (`agent_max_clarifying_questions`, default 1) and never when `clarification` is already present | **App** | One round-trip at most, so the user is never stuck answering questions forever. |
| Rewritten query non-empty and different from previous queries | **App** (schema + workflow) | A repeated query would just retrieve the same chunks. Empty is checked in the schema; "different" needs history, so the workflow checks it. |
| Disallowed action | **App**: overridden to `draft_report`, recorded as an `override` step | The safe default always exists. The override is visible, never silent. |
| Malformed decision (not JSON, unknown action, rewrite without query) | **App**: falls back to `draft_report`, recorded | A broken planner should degrade to plain RAG, not fail the request. |
| Retrieval `k` and mode | **App** (`top_k`, `retrieval_mode`) | Keeps prompt size and cost predictable; the model cannot ask for 100 chunks. |
| Evidence after a rewrite | **App**: union of both retrievals, de-duplicated by chunk id, best score kept, sorted by score, capped at `2 * top_k` | A rewrite should add what the first query missed, not throw away what it found. The cap keeps the draft prompt bounded. |
| Citation allow-list | **App**: exactly the merged evidence shown in the draft prompt | Same guarantee as RAG: every citation points at a passage the model was shown. |
| Report validation | **App**: the stage-1 validator, unchanged | Same rules for RAG and agent, so the eval compares like with like. |
| Repair | **App**: exactly one attempt, with the violation list fed back; counts toward the budget | One targeted retry fixes most citation slips; more retries mostly add cost. |

The decide prompt also lists the allowed actions. That is a courtesy that reduces wasted
choices. It is not the guardrail: the workflow checks every decision again.

## 2. The state machine

```
 incident
    |
    v
 RETRIEVE(query) --merge--> evidence (union by chunk id, best score, cap 2*top_k)
    |                                   ^
    v                                   | RETRIEVE(rewritten query)
 budget for decide + draft + repair?    |
    | no --> OVERRIDE(budget) ----+     |
    | yes                         |     |
    v                             |     |
 DECIDE (model) --> app checks:   |     |
    |-- malformed / disallowed / repeated query --> OVERRIDE --+
    |-- rewrite_query (allowed) --> REWRITE_QUERY -------------|---+
    |-- ask_clarifying_question (allowed)                      |
    |      --> ASK_CLARIFYING_QUESTION --> END: needs_clarification (200)
    |-- draft_report ------------------------------------------+
                                                               v
                                                     DRAFT --> VALIDATE
                                                                  |
                               no violations --> END: ok (200) <--+
                                                                  | violations
                                                                  v
                                                REPAIR (once, with violations) --> VALIDATE
                                                    --> END: ok (200) or invalid_output (422)
```

Every box is a `TraceStep`: `retrieve`, `decide`, `rewrite_query`,
`ask_clarifying_question`, `override`, `draft`, `validate`, `repair`. A typical trace:

- easy incident: `retrieve, decide, draft, validate` (2 LLM calls)
- weak first retrieval: `retrieve, decide, rewrite_query, retrieve, decide, draft, validate` (3)
- vague incident: `retrieve, decide, ask_clarifying_question` (1), then the resubmission
  with `clarification` drafts.

**Why a bounded state machine and not an open tool loop.** In an open loop the model calls
tools until it decides to stop, so cost, latency and behaviour depend on the model. Here
the transitions are fixed and each has a budget, which buys three things:

1. **Predictable cost and latency.** The worst case is known before the request starts
   (section 4).
2. **Testable.** Every path is a short script of decisions; `tests/test_agent.py` covers
   each one with `ScriptedLLM`, no network.
3. **Cannot loop forever.** Every iteration that continues spends an LLM call, and the
   budget check stops the loop. The `for` loop is also bounded by `range(budget)` as a
   second, syntactic guarantee.

**Compared with human confirmation for write actions.** In an app where the model can
*change* things (send an email, delete a record), the standard guardrail is to pause and
let a human confirm each write. Here every action is read-only (search again, ask a
question, write a report that a human reads), so there is nothing to confirm; the risk is
cost, loops and ungrounded claims, and those are handled by budgets, overrides and the
validator. The clarifying question is the one place a human is in the loop, and it works
in the opposite direction: the model asks the human for *information*, not permission.
If this agent ever gained a write action (for example "page the database on-call"), that
action should go through human confirmation, and the budgets here would still apply.

## 3. Failure handling

| Failure | What happens | Trace |
|---|---|---|
| Decision is not JSON / fails `AgentDecision` validation | Fall back to `draft_report` | `decide` with `decision: null, error`, then `override` (`malformed decision output: ...`) |
| Model picks a disallowed action (second rewrite, asking after a clarification) | Override to `draft_report` | `override` with `requested_action` and `reason` |
| Rewritten query repeats an earlier one | Override to `draft_report` | `override` (`repeats a query already tried`) |
| Budget leaves no room for another decision | Skip the decision, draft | `override` with `requested_action: null` |
| Draft fails validation | One repair with the violation list in the prompt | `repair` (with `violations_fed_back`), second `validate` |
| Repair also fails | `status: invalid_output`, HTTP 422, full response body (same contract as RAG) | final `validate` lists violations |
| No budget for repair (only if `agent_max_steps` < 2) | `invalid_output` straight away | `validate.detail.repair = "skipped: ..."` |
| LLM provider error | `LLMCallError` propagates, HTTP 502 | none (request failed) |
| Retriever cannot be built | HTTP 503 before the agent runs | none |

## 4. Cost and latency bounds

Worst-case LLM calls per request = `agent_max_steps` (default **4**): decide, decide (after
one rewrite), draft, repair. The budget is never exceeded: a `decide` call is made only if
`llm_calls + 1 + 2 <= agent_max_steps` (2 calls reserved for draft and repair), and repair
only if a call is left. Worst-case retrievals = `1 + agent_max_query_rewrites` (default 2).
Worst-case draft prompt = `2 * top_k` chunks (default 10). Decide prompts carry only an
evidence summary (id, heading, score, first 200 characters), so they are much smaller than
the draft prompt.

Compared with RAG (1 call), the common case costs 2 calls: one small decide call plus the
same draft. A clarification round-trip costs 1 call for the question plus the full run of
the resubmitted request.

## 5. Why one clarifying round-trip

- The user came for an answer. A second question after they already answered one feels
  like stalling; at that point a report that says "insufficient evidence, missing: X" is
  more useful, and the schema supports exactly that.
- It keeps the API stateless. The server stores nothing between requests; the client
  resubmits the incident with `clarification`. `clarification_given=True` is all the
  workflow needs to know that the one question has been used.
- It makes the eval simple: the `ambiguous` cases in `data/eval/cases.jsonl` carry the one
  `clarification` a human would give, and the harness feeds it back once.

## 6. How the trace powers the demo and the eval

The response's `trace` is the same object for every mode: `steps` (name, latency, detail),
`queries`, `retrieved` (the final merged set), `violations`, `timings_ms` (`retrieval`,
`generation`, `validation`, `total`) and `llm_calls`.

- **Demo UI** (`/`): the "Steps" timeline is `trace.steps` in order, with each decide
  step's rationale and each override's reason. Citation chips link to `response.evidence`;
  chips citing an id that was not retrieved are red. The footer shows timings and LLM calls.
- **Eval**: the same fields answer the questions the eval asks. How often does the agent
  rewrite, and does the rewrite improve chunk recall (`trace.retrieved` vs labels)? How
  often does it ask on `ambiguous` vs `answerable` cases? How often are decisions
  overridden or malformed (count `override` steps)? What does the agent cost over RAG
  (`llm_calls`, `timings_ms.total`)? `AGENT_PROMPT_VERSION` in each decide step ties every
  number to the prompt that produced it.

## 7. Known limitations

- **Scores from two queries are compared directly** when merging. That is fine for one
  retriever and mode with the same scoring, but rank-fusion scores (hybrid) are not truly
  comparable across queries. A fairer merge would use reciprocal-rank fusion over the two
  result lists.
- **The decision sees only a summary**, so it can misjudge relevance when the key fact is
  past the first 200 characters of a chunk.
- **The validator checks citations exist, not that they support the claim** (same as RAG;
  see `docs/generation-and-validation.md`).
- **Only one clarifying question**, even when the answer is still vague. By design.
- **`DemoLLM` uses a fixed heuristic** (short incident with no numbers asks; everything
  else drafts; it never rewrites). It shows the plumbing and the UI, not real judgement.
  Behaviour is tested with `ScriptedLLM`.
- **No streaming**: the UI shows the steps after the request completes, not live.
- **The CLI** (`scripts/triage_cli.py`) prints the report but not the clarifying question
  for `needs_clarification`; use `--json` or the UI.

## 8. Interview questions

1. **Why is this "agentic" if the model only picks among three actions?**
   The model chooses the control flow (search again, ask, or answer) based on what it sees.
   Limiting the choices is what makes that safe to run in production: known cost, testable
   paths, no infinite loops. More actions can be added as more transitions.

2. **What is the worst-case number of LLM calls, and how do you guarantee it?**
   `agent_max_steps`, 4 by default. Code checks the budget before every call and reserves
   two calls for draft and repair, so exploration can never starve the report. The loop is
   also bounded by `range(budget)`.

3. **What happens if the model returns garbage or ignores the rules?**
   Garbage falls back to `draft_report`, so the request degrades to plain RAG. A disallowed
   action is overridden to `draft_report`. Both are recorded as `override` steps with a
   reason, so the eval can measure how often it happens.

4. **Why merge evidence instead of replacing it after a rewrite?**
   The rewrite is meant to find what the first query missed; the first results may still
   hold the right chunk. The union keeps the best score per chunk and is capped at
   `2 * top_k`, and the citation allow-list is exactly that merged set.

5. **How does this compare with human confirmation of tool calls?**
   Confirmation protects against harmful *writes*. Every action here is read-only, so the
   risks are cost, loops and made-up citations, handled by budgets, overrides and the
   validator. If a write action were added, it would need human confirmation on top.
