CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    doc_id    TEXT PRIMARY KEY,
    doc_type  TEXT NOT NULL CHECK (doc_type IN ('runbook', 'incident', 'policy')),
    title     TEXT NOT NULL,
    metadata  JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id      TEXT PRIMARY KEY,                -- e.g. 'RB-DB-001#s2'
    doc_id        TEXT NOT NULL REFERENCES documents ON DELETE CASCADE,
    ordinal       INT  NOT NULL,                   -- 1-based '##' section number
    heading       TEXT NOT NULL,
    content       TEXT NOT NULL,                   -- text that was embedded (title-prefixed)
    embedding     VECTOR(384) NOT NULL,            -- bge-small-en-v1.5, L2-normalised
    content_hash  TEXT NOT NULL,                   -- skip re-embedding unchanged chunks
    tsv           TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);

CREATE INDEX IF NOT EXISTS chunks_doc_id_idx ON chunks (doc_id);
-- Keyword side of hybrid retrieval: exact error strings like 'EAI_AGAIN', '53300'.
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING GIN (tsv);

-- No HNSW/IVFFlat index on purpose: with ~100 chunks an exact scan is sub-millisecond
-- and returns the true nearest neighbours. Add `USING hnsw (embedding vector_cosine_ops)`
-- once the corpus reaches tens of thousands of chunks.
