-- Schema for the FCA Handbook Q&A project. Safe to run more than once.
CREATE EXTENSION IF NOT EXISTS vector;

-- One row per ingestion run.
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id      BIGSERIAL PRIMARY KEY,
    taken_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source           TEXT NOT NULL,              -- 'api' or 'file'
    sourcebook       TEXT NOT NULL,              -- e.g. CONC
    provisions_seen  INTEGER NOT NULL DEFAULT 0,
    added            INTEGER NOT NULL DEFAULT 0,
    changed          INTEGER NOT NULL DEFAULT 0,
    removed          INTEGER NOT NULL DEFAULT 0,
    raw_path         TEXT                        -- where the untouched payload was saved
);

-- One row per provision (rule or guidance paragraph). Always the latest version.
CREATE TABLE IF NOT EXISTS provisions (
    provision_id           TEXT PRIMARY KEY,     -- e.g. 'CONC 5.2A.4R'
    sourcebook             TEXT NOT NULL,
    chapter                TEXT,
    section                TEXT,
    provision_type         TEXT,                 -- R = rule, G = guidance, ...
    title                  TEXT,
    body                   TEXT NOT NULL,
    url                    TEXT,
    content_hash           TEXT NOT NULL,        -- sha256 of the normalised content
    is_current             BOOLEAN NOT NULL DEFAULT TRUE,
    first_seen_snapshot    BIGINT REFERENCES snapshots (snapshot_id),
    last_changed_snapshot  BIGINT REFERENCES snapshots (snapshot_id),
    embedding              vector(384),          -- must match the embedding model's size
    search_tsv             tsvector GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(title, '') || ' ' || body)
    ) STORED
);

CREATE INDEX IF NOT EXISTS provisions_tsv_idx ON provisions USING gin (search_tsv);
CREATE INDEX IF NOT EXISTS provisions_embedding_idx
    ON provisions USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS provisions_sourcebook_idx ON provisions (sourcebook) WHERE is_current;

-- History: what changed between snapshots. The API only serves the current
-- Handbook, so this table is the only record of earlier wording.
CREATE TABLE IF NOT EXISTS provision_changes (
    change_id     BIGSERIAL PRIMARY KEY,
    snapshot_id   BIGINT NOT NULL REFERENCES snapshots (snapshot_id),
    provision_id  TEXT NOT NULL,
    change_type   TEXT NOT NULL CHECK (change_type IN ('added', 'changed', 'removed')),
    old_hash      TEXT,
    new_hash      TEXT,
    old_body      TEXT
);
CREATE INDEX IF NOT EXISTS provision_changes_snapshot_idx ON provision_changes (snapshot_id);

-- Every question asked, for monitoring cost, latency and refusals.
CREATE TABLE IF NOT EXISTS qa_log (
    qa_id              BIGSERIAL PRIMARY KEY,
    asked_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    question           TEXT NOT NULL,
    mode               TEXT NOT NULL,
    retrieved_ids      TEXT[] NOT NULL,
    cited_ids          TEXT[] NOT NULL,
    refused            BOOLEAN NOT NULL,
    refusal_reason     TEXT,
    latency_ms         INTEGER,
    prompt_tokens      INTEGER,
    completion_tokens  INTEGER
);
