CREATE TABLE IF NOT EXISTS requests (
  id TEXT PRIMARY KEY, created_at TEXT NOT NULL, input_hash TEXT NOT NULL, source_type TEXT NOT NULL,
  options_json TEXT NOT NULL, overrides_json TEXT NOT NULL, status TEXT NOT NULL, tier TEXT,
  latency_ms INTEGER, pipeline_version TEXT NOT NULL, model_fingerprint TEXT,
  result_json TEXT, trace_json TEXT
);
CREATE TABLE IF NOT EXISTS llm_calls (
  id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES requests(id), step TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 1, prompt_version INTEGER NOT NULL, cache_key TEXT NOT NULL,
  cache_hit INTEGER NOT NULL, request_json TEXT NOT NULL, response_raw TEXT, parsed_json TEXT,
  finish_reason TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, latency_ms INTEGER, error TEXT
);
CREATE TABLE IF NOT EXISTS llm_cache (
  cache_key TEXT PRIMARY KEY, step TEXT NOT NULL, prompt_version INTEGER NOT NULL,
  model_fingerprint TEXT, response_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_request ON llm_calls(request_id);
