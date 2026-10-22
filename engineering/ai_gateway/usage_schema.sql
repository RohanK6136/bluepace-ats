-- BluePace AI usage telemetry schema (PostgreSQL).
-- Apply only after reviewing the target database and migration conventions.
-- Deliberately excludes prompts, resume text, raw provider responses, and secrets.

CREATE TABLE IF NOT EXISTS ai_usage_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id UUID NOT NULL UNIQUE,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    tenant_id TEXT,
    actor_id TEXT,
    task TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens BIGINT NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens BIGINT NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    cached_input_tokens BIGINT NOT NULL DEFAULT 0
        CHECK (cached_input_tokens >= 0 AND cached_input_tokens <= input_tokens),
    latency_ms BIGINT NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),
    status TEXT NOT NULL CHECK (status IN ('success', 'error', 'timeout', 'rate_limited')),
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    estimated_cost_usd NUMERIC(20, 8),
    pricing_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (estimated_cost_usd IS NULL OR estimated_cost_usd >= 0)
);

CREATE INDEX IF NOT EXISTS idx_ai_usage_events_occurred_at
    ON ai_usage_events (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_usage_events_task_model_time
    ON ai_usage_events (task, provider, model, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_usage_events_tenant_time
    ON ai_usage_events (tenant_id, occurred_at DESC);

-- Example reporting query: usage by model and task over the last 30 days.
-- SELECT task, provider, model, COUNT(*) AS requests,
--        SUM(input_tokens) AS input_tokens,
--        SUM(output_tokens) AS output_tokens,
--        SUM(estimated_cost_usd) AS estimated_cost_usd
-- FROM ai_usage_events
-- WHERE occurred_at >= now() - interval '30 days'
-- GROUP BY task, provider, model
-- ORDER BY estimated_cost_usd DESC NULLS LAST;
