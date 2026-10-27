-- Feature-agnostic run tracking + richer LLM call records (tokens, cost, model) for observability.

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  finished_at TEXT,
  feature TEXT NOT NULL,
  operation TEXT NOT NULL,
  status TEXT NOT NULL,              -- 'running' while in flight, then the feature's own status
  outcome TEXT,                      -- success | degraded | rejected | error (feature-neutral, for dashboards)
  title TEXT,                        -- short display label (e.g. the JD title)
  profile TEXT,
  provider TEXT,
  model TEXT,
  source_type TEXT,
  input_hash TEXT,
  input_chars INTEGER,
  input_preview TEXT,
  input_text TEXT,
  options_json TEXT,
  overrides_json TEXT,
  llm_calls INTEGER NOT NULL DEFAULT 0,
  cache_hits INTEGER NOT NULL DEFAULT 0,
  repairs INTEGER NOT NULL DEFAULT 0,
  prompt_tokens INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  usage_estimated INTEGER NOT NULL DEFAULT 0,
  cost_usd REAL NOT NULL DEFAULT 0,
  latency_ms INTEGER,
  llm_ms INTEGER,
  error TEXT,
  pipeline_version TEXT,
  app_version TEXT,
  http_request_id TEXT,
  client_ip TEXT,
  api_key_id TEXT,
  result_json TEXT,
  trace_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at);
CREATE INDEX IF NOT EXISTS idx_runs_feature_created ON runs(feature, created_at);
CREATE INDEX IF NOT EXISTS idx_runs_outcome ON runs(outcome);

ALTER TABLE llm_calls ADD COLUMN created_at TEXT;
ALTER TABLE llm_calls ADD COLUMN feature TEXT;
ALTER TABLE llm_calls ADD COLUMN profile TEXT;
ALTER TABLE llm_calls ADD COLUMN provider TEXT;
ALTER TABLE llm_calls ADD COLUMN model TEXT;
ALTER TABLE llm_calls ADD COLUMN total_tokens INTEGER;
ALTER TABLE llm_calls ADD COLUMN usage_estimated INTEGER NOT NULL DEFAULT 0;
ALTER TABLE llm_calls ADD COLUMN cost_usd REAL NOT NULL DEFAULT 0;
ALTER TABLE llm_calls ADD COLUMN error_type TEXT;
CREATE INDEX IF NOT EXISTS idx_llm_calls_created ON llm_calls(created_at);

-- Carry over runs recorded before this migration (JD Standardizer only existed then).
INSERT OR IGNORE INTO runs (id, created_at, finished_at, feature, operation, status, outcome, source_type,
                            input_hash, options_json, overrides_json, latency_ms, pipeline_version,
                            result_json, trace_json, llm_calls, prompt_tokens, completion_tokens, total_tokens)
SELECT r.id, r.created_at, r.created_at, 'jd_standardizer',
       CASE WHEN r.pipeline_version LIKE '%+generate' THEN 'generate' ELSE 'standardize' END,
       r.status,
       CASE WHEN r.status IN ('ok', 'needs_review', 'needs_input') THEN 'success'
            WHEN r.status = 'llm_unavailable' THEN 'degraded'
            WHEN r.status IN ('needs_text', 'needs_split') THEN 'rejected'
            WHEN r.status = 'running' THEN 'error' ELSE 'error' END,
       r.source_type, r.input_hash, r.options_json, r.overrides_json, r.latency_ms, r.pipeline_version,
       r.result_json, r.trace_json,
       (SELECT COUNT(*) FROM llm_calls c WHERE c.request_id = r.id),
       (SELECT COALESCE(SUM(prompt_tokens), 0) FROM llm_calls c WHERE c.request_id = r.id),
       (SELECT COALESCE(SUM(completion_tokens), 0) FROM llm_calls c WHERE c.request_id = r.id),
       (SELECT COALESCE(SUM(COALESCE(prompt_tokens, 0) + COALESCE(completion_tokens, 0)), 0)
          FROM llm_calls c WHERE c.request_id = r.id)
FROM requests r;
