# Retrieval: ingestion, embeddings, search

This is the "R" in RAG. A user pastes an incident report; we return the 5 corpus chunks
most likely to help, each with a stable ID the LLM must cite.

```
data/corpus/**/*.md ─► loader ─► chunker ─► embedder ─► store (memory | postgres)
                                                          │
incident text ─► SearchRetriever.retrieve(mode) ──────────┘──► list[Evidence]
                   vector │ keyword (BM25) │ hybrid (RRF)
```

| Piece | File |
|---|---|
| Front-matter loader | `app/ingest/loader.py` |
| Section chunker | `app/ingest/chunker.py` |
| Incremental ingestion | `app/ingest/pipeline.py`, `scripts/ingest.py` |
| Embedders | `app/embeddings/fastembed_embedder.py`, `app/embeddings/hashing.py` |
| Tokenizer (identifier-preserving) | `app/retrieval/tokenizer.py` |
| Stores | `app/store/memory.py` (+ `bm25.py`), `app/store/postgres.py` |
| Retriever + RRF | `app/retrieval/search.py`, `app/retrieval/factory.py` |

```bash
python -m scripts.ingest                      # fastembed + memory index at .cache/index.json
python -m scripts.ingest --embedder hashing   # no download (tests/offline)
python -m scripts.ingest --backend postgres   # needs docker compose up -d
python -m scripts.ingest --rebuild            # drop and re-embed everything
```

## 1. Chunking: one chunk per `## ` section

Chunk ID = `f"{doc_id}#s{n}"`, where `n` is the 1-based index of the `## ` heading. Text
before the first heading is dropped. Each chunk's embedded text is

```
RB-DB-001 · PostgreSQL connection exhaustion · Mitigation
- Fastest: scale the deployment back ...
```

* **Why sections?** Runbooks are already written as self-contained sections (Symptoms,
  Diagnosis, Mitigation). A section is what a human would cite, so it is what we cite.
  Section IDs are also *stable*: editing a sentence inside a section does not renumber
  anything, while fixed-size windows shift every ID downstream of an edit. The eval set
  hard-codes expected chunk IDs, so stability matters.
* **Why the title prefix?** "Mitigation: scale back the deployment" on its own is vague.
  With "PostgreSQL connection exhaustion" in front, the vector knows what it is about.
* **Trade-off:** a long section becomes one big chunk. bge-small reads at most 512 tokens,
  so the vector of a very long section ignores its tail (BM25 still sees all of it). The
  chunker logs a warning above ~400 tokens (words × 1.3) instead of sub-splitting, because
  sub-chunks (`#s2a`) would break the citation-ID rule shared with the LLM layer and the
  eval set. The fix is editorial: split the section in the Markdown.

## 2. Embeddings: BGE is asymmetric

`BAAI/bge-small-en-v1.5` (384 dims, ~130 MB, CPU via ONNX/fastembed). BGE was trained with
an instruction on **queries only**:

```
"Represent this sentence for searching relevant passages: " + query
```

Passages get no prefix. We checked the installed fastembed (0.9.1): for this model,
`TextEmbedding.query_embed` is a plain passthrough to `embed()`, so fastembed does **not**
add the prefix. We add it ourselves and call `embed()` for both sides, so a future
fastembed that adds it inside `query_embed` cannot silently double it. A slow test asserts
`embed_query(q) == embed_passages([PREFIX + q])`.

Honest measurement: on this tiny corpus the prefix barely changes anything (same top-7
order with and without it; scores move by at most ~0.02). It is cheap insurance that matters more
as the corpus grows and queries get shorter.

`HashingEmbedder` is a deterministic feature-hashing bag of words (hashlib, not `hash()`,
which is salted per process). It exists so unit tests run in milliseconds with no
download. It is a lexical matcher, never use it to judge quality.

## 3. Normalisation and cosine

Every vector is L2-normalised (fastembed already does it; we do it again because the
stores rely on it). For unit vectors `cos(a, b) = a · b`, so in memory the whole search is
one matrix-vector product: `(n_chunks × 384) @ (384,)`. In Postgres, pgvector's `<=>` is
cosine **distance** (0 = identical direction); we report `score = 1 - distance`, so both
backends return cosine similarity.

## 4. Why no ANN index

ANN indexes (HNSW, IVFFlat) trade exactness for speed when there are millions of vectors.
At ~100 chunks, exact search is sub-millisecond and returns the *true* nearest neighbours,
so an ANN index would only add a recall knob to tune and a source of nondeterminism.
`migrations/001_init.sql` notes when to add `USING hnsw (embedding vector_cosine_ops)`:
tens of thousands of chunks.

## 5. BM25 vs vectors

Embeddings are fuzzy on exact tokens; logs are full of exact tokens (`EAI_AGAIN`, `53300`,
`max_connections`, `pool.acquire`, `v2.31.0`). An embedding model sees `EAI_AGAIN` as a
few subword pieces with little meaning. BM25 sees a term that occurs in one chunk out of
eleven, which gives it a huge IDF weight.

BM25 (k1 = 1.5, b = 0.75):

```
score(q, d) = Σ_t  idf(t) · tf·(k1+1) / (tf + k1·(1 − b + b·|d|/avgdl))
idf(t)      = ln(1 + (N − n_t + 0.5) / (n_t + 0.5))
```

* `tf` saturates (the 5th "timeout" adds little), `b` normalises for chunk length, and
  rare terms dominate through `idf`.
* The tokenizer lowercases and keeps identifiers whole (`\w+([.\-/:]\w+)*`), also
  emitting the parts of dotted compounds (`pool.acquire` → `pool.acquire`, `pool`,
  `acquire`). `_` is not a split point: `max_connections` is one name.
* Query terms are OR-ed. A pasted log contains timestamps and pod names that no runbook
  mentions; requiring every term would match nothing. Postgres does the same with
  `websearch_to_tsquery('english', '"tok1" or "tok2" ...')` ranked by `ts_rank_cd`.

Vectors win on paraphrase ("DB refusing new connections" ≈ "too many clients"); BM25 wins
on exact identifiers. Hybrid gets both.

## 6. Hybrid: Reciprocal Rank Fusion

```
rrf(d) = Σ_rankings  1 / (K + rank(d)),   K = 60, rank is 1-based
```

We take the top 20 from vector and top 20 from keyword, fuse, return the top k. Ties are
broken by `chunk_id` so results are deterministic.

**Why ranks, not scores?** Cosine scores sit around 0.6–0.9; BM25 scores are unbounded and
corpus-dependent (0–20 here). Adding them is meaningless and normalising them is fragile.
Ranks are always comparable. K = 60 flattens the curve so that being #1 in one list is not
worth much more than #3, which rewards chunks both methods agree on.

**Worked example (the real demo query):**

| chunk | vector rank | keyword rank | RRF |
|---|---|---|---|
| INC-2025-014#s1 | 1 | 3 | 1/61 + 1/63 = 0.03227 |
| RB-DB-001#s1 | 3 | 1 | 1/63 + 1/61 = 0.03227 (tie → by id) |
| INC-2025-014#s2 | 2 | 2 | 1/62 + 1/62 = 0.03226 |
| RB-DB-001#s2 | 5 | 4 | 1/65 + 1/64 = 0.03101 |
| RB-DB-001#s3 | 6 | 5 | 1/66 + 1/65 = 0.03054 |
| INC-2025-014#s3 | 4 | 8 | 1/64 + 1/68 = 0.03033 |

Note how RB-DB-001#s3 (Mitigation), only 6th by vector, enters the hybrid top 5 because
keyword search also likes it, pushing out INC-2025-014#s3, which keyword ranked 8th.

## 7. Idempotent, incremental ingestion

Each chunk stores `content_hash = sha256(content)` of the exact embedded text. Ingest
loads and chunks everything (cheap), asks the store for `chunk_id → hash`, embeds only
new or changed chunks (the expensive step), then deletes chunks and documents that
disappeared. Output looks like:

```
docs=4 chunks=11 embedded=0 unchanged=11 deleted=0
```

Tests prove: a second run embeds 0; editing one sentence re-embeds exactly 1; deleting a
file and a section removes 3 chunks. Because the title is part of the hashed content,
renaming a document re-embeds all its chunks, which is correct (their inputs changed).
CRLF is normalised to LF on load so a Windows checkout does not trigger re-embeds.

## 8. Memory vs Postgres

| | `MemoryStore` | `PostgresStore` |
|---|---|---|
| Vectors | numpy matrix, exact dot product | `VECTOR(384)`, `<=>` exact scan |
| Keyword | hand-written BM25 | `tsv` generated column + GIN, `ts_rank_cd` |
| Persistence | `.cache/index.json` (atomic write-then-rename) | tables in `migrations/001_init.sql` |
| Embedder check | file records embedder name + dim; mismatch is refused | column dim is checked; name is not recorded |
| Needs | nothing | `docker compose up -d` |

Both implement the same `VectorStore` protocol (`app/store/base.py`), and the retriever
does not know which one it has. The memory store refuses an index built by a different
embedder, because vectors from different models live in unrelated spaces and the failure
would otherwise be silent (just bad rankings). Postgres caveat: switching embedders there
needs `--rebuild`, because the schema has no column for the embedder name.

Keyword scores differ between the backends (BM25 vs ts_rank_cd, and Postgres's English
stemmer splits `EAI_AGAIN` into `eai` + `again` and may drop parts as stopwords), so keyword rankings can differ slightly.

## 9. Measured demo rankings

Query: `data/demo_incident.txt` (checkout-api 500s after scale-out; `pool.acquire timed
out after 5000ms`; `too many clients already`; `max_connections=200`). Corpus: 4 docs,
11 chunks. Model: bge-small-en-v1.5 via fastembed 0.9.1. Measured 2026-11-09.

| # | vector (cosine) | keyword (BM25) | hybrid (RRF) |
|---|---|---|---|
| 1 | INC-2025-014#s1 0.851 | RB-DB-001#s1 20.13 | INC-2025-014#s1 0.0323 |
| 2 | INC-2025-014#s2 0.818 | INC-2025-014#s2 17.18 | RB-DB-001#s1 0.0323 |
| 3 | RB-DB-001#s1 0.755 | INC-2025-014#s1 11.57 | INC-2025-014#s2 0.0323 |
| 4 | INC-2025-014#s3 0.752 | RB-DB-001#s2 8.70 | RB-DB-001#s2 0.0310 |
| 5 | RB-DB-001#s2 0.717 | RB-DB-001#s3 7.06 | RB-DB-001#s3 0.0305 |

The distractor RB-NET-002 (whose symptom line literally says "time out after 5000ms")
first appears at vector rank 7 (0.694) and keyword rank 6. All three modes put both the
right runbook and the matching past incident in the top 5; the slow test
(`tests/test_retrieval_demo.py`) asserts exactly that at document level.

Observations worth saying out loud:
* Vector search prefers the past incident: the incident's narrative ("HPA scale-out",
  "checkout-api", "500s") reads like the user's report. Keyword search prefers the
  runbook, which contains the exact error strings.
* Cosine scores are compressed (0.63–0.85 across *every* chunk, relevant or not). That is
  normal for BGE; absolute cosine is a poor relevance threshold, ranks are what matter.
* On this tiny corpus even vector search finds `EAI_AGAIN` → RB-NET-002#s1, because only
  one chunk is about DNS. The BM25 advantage on exact tokens grows with corpus size.

## 10. Interview questions

**Why chunk by section rather than by fixed token windows?** Sections are the natural
unit a human cites, and their IDs stay stable under edits, which the citation validator
and eval set depend on. The cost is uneven chunk sizes; we warn on long sections.

**Why do you need both BM25 and embeddings?** They fail differently. Embeddings capture
paraphrase but blur exact identifiers like `EAI_AGAIN` or `53300`; BM25 nails identifiers
but misses synonyms. Incident text has both kinds of signal.

**Why RRF instead of a weighted sum of scores?** Cosine and BM25 scores are on different,
unbounded-vs-bounded scales that shift with the corpus. RRF uses only ranks, needs no
tuning beyond K = 60, and is robust. Downside: it discards how *confident* each method was.

**Why no HNSW index?** ~100 vectors: exact search is sub-millisecond and exact. ANN adds
approximation error and tuning knobs for zero benefit until tens of thousands of chunks.

**How do you avoid re-embedding the whole corpus on every run?** A sha256 of each chunk's
embedded text is stored; ingest only embeds chunks whose hash changed and deletes chunks
whose IDs disappeared. A second run on an unchanged corpus embeds nothing.

**What breaks if you change the embedding model?** Old vectors are in a different space,
so similarities become garbage silently. The memory index records the embedder and
refuses to load under another one; `--rebuild` re-embeds.
