from __future__ import annotations

from app.store.db import Store


OLD = "2000-01-01T00:00:00.000+00:00"
NEW = "2025-01-01T00:00:00.000+00:00"


def _seed_run(store: Store, run_id: str, created_at: str) -> None:
    store._exec(
        "INSERT INTO requests (id, created_at, input_hash, source_type, options_json, overrides_json, "
        "status, tier, latency_ms, pipeline_version, model_fingerprint, result_json, trace_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, created_at, "hash", "text", '{"profile":"test"}', '{"city":"sensitive"}',
         "ok", "complete", 10, "test", "fingerprint", '{"output":"sensitive"}', '{"prompt":"sensitive"}'),
    )
    store.insert_run({
        "id": run_id,
        "created_at": created_at,
        "finished_at": created_at,
        "feature": "applicant_match",
        "operation": "analyze",
        "status": "complete",
        "outcome": "success",
        "title": "A-12345678 · Engineer",
        "input_preview": "redacted resume preview",
        "input_text": "redacted resume text",
        "options_json": '{"profile":"test"}',
        "overrides_json": '{"city":"sensitive"}',
        "result_json": '{"summary":"sensitive output"}',
        "trace_json": '{"prompt":"sensitive prompt"}',
    })
    store.insert_llm_call({
        "id": "call-" + run_id,
        "request_id": run_id,
        "created_at": created_at,
        "feature": "applicant_match",
        "step": "profile",
        "attempt": 1,
        "prompt_version": 1,
        "cache_key": "cache-" + run_id,
        "cache_hit": False,
        "profile": "test",
        "provider": "test",
        "model": "fake",
        "request_json": '{"user":"sensitive resume text"}',
        "response_raw": '{"name":"sensitive output"}',
        "parsed_json": '{"name":"sensitive output"}',
        "finish_reason": "stop",
        "prompt_tokens": 2,
        "completion_tokens": 2,
        "total_tokens": 4,
        "usage_estimated": False,
        "cost_usd": 0.0,
        "latency_ms": 2,
        "error_type": None,
        "error": None,
    })
    store._exec(
        "INSERT INTO llm_cache (cache_key, step, prompt_version, model_fingerprint, response_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("cache-" + run_id, "profile", 1, "fingerprint", '{"response":"sensitive output"}', created_at),
    )


def test_retention_purges_payloads_but_keeps_metrics_and_recent_runs() -> None:
    store = Store(":memory:")
    try:
        _seed_run(store, "old-run", OLD)
        _seed_run(store, "recent-run", NEW)

        counts = store.purge_expired_payloads("2020-01-01T00:00:00.000+00:00")

        assert counts["run_payloads"] == 1
        assert counts["model_call_payloads"] == 1
        assert counts["legacy_request_payloads"] == 1
        assert counts["cache_entries"] == 1

        old_run = store.get_run("old-run")
        assert old_run is not None
        assert old_run["input_text"] is None
        assert old_run["result_json"] is None
        assert old_run["trace_json"] is None
        assert old_run["total_tokens"] == 0
        old_call = store.llm_calls_for("old-run")[0]
        assert old_call["request_json"] == "{}"
        assert old_call["response_raw"] is None
        assert old_call["parsed_json"] == "{}"
        old_legacy = store._exec("SELECT result_json, trace_json FROM requests WHERE id='old-run'")[0]
        assert old_legacy["result_json"] is None
        assert old_legacy["trace_json"] is None
        assert store.cache_get("cache-old-run") is None

        recent_run = store.get_run("recent-run")
        assert recent_run is not None
        assert recent_run["input_text"] == "redacted resume text"
        assert recent_run["result_json"] is not None
        assert store.llm_calls_for("recent-run")[0]["response_raw"] is not None
        assert store.cache_get("cache-recent-run") is not None
    finally:
        store.close()


def test_erasing_run_removes_run_legacy_rows_calls_and_cache() -> None:
    store = Store(":memory:")
    try:
        _seed_run(store, "erase-me", NEW)

        assert store.delete_run("erase-me") is True
        assert store.get_run("erase-me") is None
        assert store.llm_calls_for("erase-me") == []
        assert store._exec("SELECT id FROM requests WHERE id='erase-me'") == []
        assert store.cache_get("cache-erase-me") is None
        assert store.delete_run("erase-me") is False
    finally:
        store.close()
