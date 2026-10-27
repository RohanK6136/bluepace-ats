-- Applicant Match: saved job rubrics. A rubric version is immutable; editing creates a new row.
-- rubric_id = 'rb_' + the first 12 hex characters of rubric_hash (SHA-256 of the canonical rubric JSON),
-- so saving identical content twice returns the same version.
CREATE TABLE IF NOT EXISTS match_rubrics (
    id           TEXT PRIMARY KEY,
    hash         TEXT NOT NULL UNIQUE,
    created_at   TEXT NOT NULL,
    title        TEXT,
    job_ref      TEXT,
    items        INTEGER NOT NULL,
    rubric_json  TEXT NOT NULL,
    created_by   TEXT  -- hashed API key id, when auth is on
);
CREATE INDEX IF NOT EXISTS idx_match_rubrics_created ON match_rubrics(created_at);
