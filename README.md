# Triagent

**Evidence-grounded incident triage.** Paste an error report or a short log excerpt. Triagent searches a corpus of synthetic runbooks
and past incident reports, and returns a **structured triage report**: severity (SEV1–4), likely causes,
and next steps. **Every claim cites a retrieved passage**, and when the corpus doesn't cover the
problem, the report **says so** instead of guessing.

It's built in three stages, and each one can be measured against the others:

| Stage | What it adds | Read |
|---|---|---|
| 1. Basic RAG | Chunking, local embeddings, vector / BM25 / hybrid retrieval, a report checked against a schema, and a **citation allow-list** enforced in code | [docs/retrieval.md](docs/retrieval.md), [docs/generation-and-validation.md](docs/generation-and-validation.md) |
| 2. Agentic workflow | The model chooses to *draft*, *rewrite the query and retry once*, or *ask one clarifying question*. The app enforces every limit. Each step shows in the UI | [docs/agent.md](docs/agent.md) |
| 3. Evaluation | 32 labeled cases; the same model compared with no retrieval, with RAG, and as an agent; LLM-as-judge for claim support; bootstrap CIs | [docs/evaluation.md](docs/evaluation.md), [data/eval/README.md](data/eval/README.md) |
| 4. QLoRA (optional) | Dataset and hardware requirements for fine-tuning a small severity classifier, written up before any decision to build it | [finetune/README.md](finetune/README.md) |

## Architecture

```
                 INGESTION (python -m scripts.ingest, idempotent)
 data/corpus/*.md ─► front-matter ─► chunk per "## " section ─► embed (bge-small, local) ─► store
                                     id = DOC-ID#sN                (only changed chunks)     │
                                                                                            ▼
                                                     ┌─────────────────────────────────────────┐
                                                     │ memory store (numpy + BM25, default)    │
                                                     │   or Postgres + pgvector + tsvector     │
                                                     └───────────────────┬─────────────────────┘
 POST /triage  ──────────────────────────────────────────────────────────┼───────────────────────
  mode=no_retrieval:   incident ─────────────────────────────► LLM ─► validate
  mode=rag:            incident ─► retrieve top-k + pinned ─► LLM ─► validate
  mode=agent:          incident ─► retrieve ─► DECIDE ─┬─ draft ──► LLM ─► validate ─► repair ×1
                                      ▲                ├─ rewrite query (×1) ─► retrieve ─► merge ─┘
                                      └────────────────┴─ ask clarifying question (×1) ─► 200 needs_clarification

  validate (deterministic code): schema parse · cited ids ⊆ retrieved ids · every cause/step cited ·
                                 severity/abstention consistency     → 422 with violations if any fail
  pinned: the severity policy is added to every request's evidence, never left to ranking
  every response carries a trace: steps, retrieved ids + scores, queries, timings, LLM call count
```

**Who decides what.** The model chooses among allowed actions and writes the report. Code owns
everything else: the step budget (≤ 4 LLM calls), one query rewrite, one clarifying question, how
evidence is merged, the citation allow-list, and one repair attempt. It's the same idea as asking a
human to confirm write actions in a tool-calling app: **the model proposes and deterministic code decides.**

## Quickstart

Requires Python 3.11+. Docker is optional: the default store is in-memory.

**PowerShell (Windows)**
```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env      # then set GEMINI_API_KEY, or set LLM_PROVIDER=fake to try it offline
python -m scripts.ingest    # downloads the ~130 MB embedding model once, then builds .cache/index.json
uvicorn app.main:app --reload
```

**bash (macOS/Linux)**
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python -m scripts.ingest
uvicorn app.main:app --reload
```

Open http://localhost:8000. Click **Load demo incident**, pick a mode, and submit. Click a citation chip to see the
passage, and read the **Steps** timeline to see what the agent chose. The API docs are at `/docs`.

From the terminal:
```bash
python -m scripts.triage_cli data/demo_incident.txt --mode agent
```

**Optional: Postgres + pgvector**
```bash
docker compose up -d
STORE_BACKEND=postgres python -m scripts.ingest --backend postgres
```

## Tests

```bash
pytest -q                      # fast tests: fakes only, no network, no key
pytest -q -m slow              # real embedding model (and live Gemini if GEMINI_API_KEY is set)
pytest -q -m postgres          # needs docker compose up -d
ruff check .
```

## Results

### Retrieval (measured, no LLM involved)

`python -m eval.retrieval_eval --k 5` scored 25 cases. The 7 abstention cases have no target document, so they're skipped. Full report:
[eval/results/retrieval-latest.md](eval/results/retrieval-latest.md).

| Metric @5 | vector | keyword (BM25) | hybrid (RRF) |
|---|---|---|---|
| Doc recall | 52% [44–59] | 61% [55–67] | 59% [55–64] |
| Chunk recall | 53% [41–65] | 66% [56–75] | 61% [52–70] |
| Primary-doc hit | 88% [72–100] | 100% | 100% |
| MRR (chunk) | 71% [56–86] | 80% [68–91] | 78% [65–90] |

The 95% bootstrap confidence intervals overlap, and with n=25 a gap under about 10 points isn't meaningful.
The consistent pattern is that **pure vector search misses the most important document in 3 of 25 cases,
and keyword or hybrid search never does.** Incident text is full of exact tokens (`too many clients`,
`max_connections`, `EAI_AGAIN`) that embeddings blur. The demo incident is one of the misses:
near-miss documents about a table-lock outage and payment timeouts push the connection-exhaustion runbook out of
the vector top 5. See [docs/retrieval.md](docs/retrieval.md). `RETRIEVAL_MODE` still defaults to
`vector` so that "basic RAG" stays a true baseline. Hybrid is the obvious next experiment for the full evaluation.

### End-to-end (no_retrieval vs RAG vs agent)

*Pending a run with a real model.* This needs `GEMINI_API_KEY`, and a full run is about 200–300 LLM calls:
```bash
python -m eval.run_eval --modes no_retrieval rag agent --delay 7
```
It writes `eval/results/<run_id>.md` and `eval/results/latest.md`. Paste the comparison table here
using the template in [docs/evaluation.md §8](docs/evaluation.md). It covers severity accuracy, claim support (judge),
correct and false abstention, citation validity, clarification behavior, and p50/p95 latency.
[eval/results/example-smoke.md](eval/results/example-smoke.md) shows the report format from an offline
run with a fake LLM. **Its numbers are meaningless.**

## Repository layout

```
app/
  config.py  schemas.py      settings (every app-enforced limit) and shared data contracts
  ingest/                    front-matter loader, heading chunker, idempotent ingest pipeline
  embeddings/                fastembed bge-small (query prefix applied once) and a hashing embedder for tests
  store/                     memory store (numpy + BM25) and Postgres store (pgvector + tsvector)
  retrieval/                 vector / keyword / hybrid (reciprocal-rank fusion) retriever
  llm/                       Gemini client (JSON schema output, retries) and fake LLMs, prompts
  triage/                    validator, RAG and no-retrieval pipelines, service entry point
  agent/                     bounded decision loop, AgentDecision schema, agent prompts
  static/                    demo UI (plain HTML/JS, no build step)
  main.py                    FastAPI: POST /triage, GET /health, UI at /
data/corpus/                 26 synthetic runbooks, incidents and policies
data/eval/cases.jsonl        32 labeled cases (answerable / insufficient_evidence / ambiguous)
eval/                        run_eval, retrieval_eval, metrics, judge, report
finetune/README.md           stage 4 requirements (not implemented yet)
docs/                        design notes per subsystem: decisions, trade-offs, FAQ
```

## Known limitations

- The corpus and the eval set are synthetic and written by the same author, so eval scores are optimistic
  ([docs/evaluation.md §6](docs/evaluation.md)).
- With 32 cases, every percentage carries a wide interval, and a single case is about 3 points.
- The citation allow-list proves the model cited something it was *shown*. It does not prove the passage
  *supports* the claim. That's measured by the LLM judge, which should be spot-checked by a human.
- The Postgres store has integration tests (`-m postgres`) that haven't yet been run against a live database.
