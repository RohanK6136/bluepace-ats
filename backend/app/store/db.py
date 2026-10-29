"""SQLite persistence: runs, LLM calls, response cache. The only module that touches the database.

Schema changes are numbered SQL files in ./migrations, applied once each and recorded in schema_migrations.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_LLM_CALL_COLS = (
    "id", "request_id", "created_at", "feature", "step", "attempt", "prompt_version", "cache_key", "cache_hit",
    "profile", "provider", "model", "request_json", "response_raw", "parsed_json", "finish_reason",
    "prompt_tokens", "completion_tokens", "total_tokens", "usage_estimated", "cost_usd", "latency_ms",
    "error_type", "error",
)
_RUN_COLS = (
    "id", "created_at", "finished_at", "feature", "operation", "status", "outcome", "title", "profile", "provider",
    "model", "source_type", "input_hash", "input_chars", "input_preview", "input_text", "options_json",
    "overrides_json", "llm_calls", "cache_hits", "repairs", "prompt_tokens", "completion_tokens", "total_tokens",
    "usage_estimated", "cost_usd", "latency_ms", "llm_ms", "error", "pipeline_version", "app_version",
    "http_request_id", "client_ip", "api_key_id", "result_json", "trace_json",
)
_RUN_SUMMARY_COLS = tuple(c for c in _RUN_COLS if c not in ("input_text", "result_json", "trace_json"))
_BOOL_COLS = {"cache_hit", "usage_estimated"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        if path != ":memory:":
            with self._lock:
                self._conn.execute("PRAGMA journal_mode=WAL")  # readers don't block the writer
        self.migrate()

    def close(self) -> None:
        self._conn.close()

    def _exec(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
            self._conn.commit()
            return rows

    # ------------------------------------------------------------------ migrations
    def migrate(self) -> list[str]:
        applied: list[str] = []
        with self._lock:
            self._conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, "
                               "applied_at TEXT NOT NULL)")
            done = {r[0] for r in self._conn.execute("SELECT version FROM schema_migrations")}
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if path.stem in done:
                    continue
                self._conn.executescript(path.read_text(encoding="utf-8"))
                self._conn.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                                   (path.stem, now_iso()))
                applied.append(path.stem)
            self._conn.commit()
        return applied

    def schema_version(self) -> str | None:
        rows = self._exec("SELECT MAX(version) AS v FROM schema_migrations")
        return rows[0]["v"] if rows else None

    # ------------------------------------------------------------------ applicant match rubrics
    def insert_rubric(self, rubric_id: str, rubric_hash: str, created_at: str, title: str | None,
                      job_ref: str | None, items: int, rubric_json: str, created_by: str | None) -> None:
        self._exec("INSERT OR IGNORE INTO match_rubrics (id, hash, created_at, title, job_ref, items, rubric_json, "
                   "created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (rubric_id, rubric_hash, created_at, title, job_ref, items, rubric_json, created_by))

    def get_rubric(self, rubric_id: str) -> dict[str, Any] | None:
        rows = self._exec("SELECT * FROM match_rubrics WHERE id=?", (rubric_id,))
        return dict(rows[0]) if rows else None

    def list_rubrics(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._exec("SELECT id, hash, created_at, title, job_ref, items, created_by FROM match_rubrics "
                          "ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ runs
    def insert_run(self, run: dict[str, Any]) -> None:
        cols = [c for c in _RUN_COLS if c in run]
        self._exec(f"INSERT OR REPLACE INTO runs ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                   [run[c] for c in cols])

    def update_run(self, run_id: str, fields: dict[str, Any]) -> None:
        cols = [c for c in _RUN_COLS if c in fields and c != "id"]
        if cols:
            self._exec(f"UPDATE runs SET {', '.join(f'{c}=?' for c in cols)} WHERE id=?",
                       [fields[c] for c in cols] + [run_id])

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        rows = self._exec("SELECT * FROM runs WHERE id=?", (run_id,))
        return dict(rows[0]) if rows else None

    def delete_run(self, run_id: str) -> bool:
        """Erase a run and associated stored model payloads, legacy rows and response-cache entries."""
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE")
                cache_keys = [row["cache_key"] for row in cursor.execute(
                    "SELECT DISTINCT cache_key FROM llm_calls WHERE request_id=?", (run_id,)
                ).fetchall()]
                cursor.execute("DELETE FROM llm_calls WHERE request_id=?", (run_id,))
                cursor.execute("DELETE FROM requests WHERE id=?", (run_id,))
                cursor.execute("DELETE FROM runs WHERE id=?", (run_id,))
                deleted = cursor.rowcount > 0
                for cache_key in cache_keys:
                    cursor.execute("DELETE FROM llm_cache WHERE cache_key=?", (cache_key,))
                self._conn.commit()
                return deleted
            except Exception:
                self._conn.rollback()
                raise

    def purge_expired_payloads(self, cutoff: str) -> dict[str, int]:
        """Redact payload-bearing columns older than cutoff while preserving aggregate run/cost metrics.

        cutoff must be an ISO-8601 UTC timestamp. This intentionally keeps operational counters,
        model identifiers, hashes, and status fields while removing stored text, prompts and outputs.
        """
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute(
                    "UPDATE runs SET input_preview=NULL, input_text=NULL, options_json=NULL, "
                    "overrides_json=NULL, result_json=NULL, trace_json=NULL, error=NULL "
                    "WHERE created_at < ? AND (input_preview IS NOT NULL OR input_text IS NOT NULL "
                    "OR options_json IS NOT NULL OR overrides_json IS NOT NULL OR result_json IS NOT NULL "
                    "OR trace_json IS NOT NULL OR error IS NOT NULL)",
                    (cutoff,),
                )
                run_payloads = max(0, cursor.rowcount)
                cursor.execute(
                    "UPDATE llm_calls SET request_json='{}', response_raw=NULL, parsed_json='{}', error=NULL "
                    "WHERE (created_at < ? OR (created_at IS NULL AND request_id IN "
                    "(SELECT id FROM requests WHERE created_at < ?))) "
                    "AND (request_json <> '{}' OR response_raw IS NOT NULL "
                    "OR COALESCE(parsed_json, '') <> '{}' OR error IS NOT NULL)",
                    (cutoff, cutoff),
                )
                call_payloads = max(0, cursor.rowcount)
                cursor.execute(
                    "UPDATE requests SET options_json='{}', overrides_json='{}', result_json=NULL, trace_json=NULL "
                    "WHERE created_at < ? AND (options_json <> '{}' OR overrides_json <> '{}' "
                    "OR result_json IS NOT NULL OR trace_json IS NOT NULL)",
                    (cutoff,),
                )
                legacy_payloads = max(0, cursor.rowcount)
                cursor.execute("DELETE FROM llm_cache WHERE created_at < ?", (cutoff,))
                cache_entries = max(0, cursor.rowcount)
                self._conn.commit()
                return {
                    "run_payloads": run_payloads,
                    "model_call_payloads": call_payloads,
                    "legacy_request_payloads": legacy_payloads,
                    "cache_entries": cache_entries,
                }
            except Exception:
                self._conn.rollback()
                raise

    def list_runs(self, *, feature: str | None = None, outcome: str | None = None, profile: str | None = None,
                  status: str | None = None, query: str | None = None, since: str | None = None,
                  before: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        where, params = self._run_filters(feature=feature, outcome=outcome, profile=profile, status=status,
                                          query=query, since=since)
        if before:
            where.append("created_at < ?")
            params.append(before)
        sql = (f"SELECT {', '.join(_RUN_SUMMARY_COLS)} FROM runs"
               + (f" WHERE {' AND '.join(where)}" if where else "")
               + " ORDER BY created_at DESC LIMIT ?")
        return [dict(r) for r in self._exec(sql, [*params, max(1, min(limit, 500))])]

    @staticmethod
    def _run_filters(**f: Any) -> tuple[list[str], list[Any]]:
        where: list[str] = []
        params: list[Any] = []
        for col in ("feature", "outcome", "profile", "status"):
            if f.get(col):
                where.append(f"{col} = ?")
                params.append(f[col])
        if f.get("since"):
            where.append("created_at >= ?")
            params.append(f["since"])
        if f.get("query"):
            where.append("(title LIKE ? OR input_preview LIKE ? OR id LIKE ?)")
            like = f"%{f['query']}%"
            params += [like, like, like]
        return where, params

    def run_summary(self, *, since: str | None = None, feature: str | None = None) -> dict[str, Any]:
        where, params = self._run_filters(since=since, feature=feature)
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        totals = dict(self._exec(
            "SELECT COUNT(*) AS runs, "
            "SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) AS success, "
            "SUM(CASE WHEN outcome='degraded' THEN 1 ELSE 0 END) AS degraded, "
            "SUM(CASE WHEN outcome='rejected' THEN 1 ELSE 0 END) AS rejected, "
            "SUM(CASE WHEN outcome='error' THEN 1 ELSE 0 END) AS error, "
            "COALESCE(SUM(llm_calls),0) AS llm_calls, COALESCE(SUM(cache_hits),0) AS cache_hits, "
            "COALESCE(SUM(prompt_tokens),0) AS prompt_tokens, COALESCE(SUM(completion_tokens),0) AS completion_tokens, "
            "COALESCE(SUM(total_tokens),0) AS total_tokens, COALESCE(SUM(cost_usd),0) AS cost_usd, "
            "AVG(latency_ms) AS avg_latency_ms FROM runs" + clause, params)[0])
        latencies = [r["latency_ms"] for r in self._exec(
            "SELECT latency_ms FROM runs" + clause + (" AND" if clause else " WHERE")
            + " latency_ms IS NOT NULL ORDER BY latency_ms", params)]
        totals["p50_latency_ms"] = _percentile(latencies, 0.50)
        totals["p95_latency_ms"] = _percentile(latencies, 0.95)
        by_model = [dict(r) for r in self._exec(
            "SELECT profile, model, COUNT(*) AS runs, COALESCE(SUM(total_tokens),0) AS total_tokens, "
            "COALESCE(SUM(cost_usd),0) AS cost_usd, AVG(latency_ms) AS avg_latency_ms FROM runs" + clause
            + " GROUP BY profile, model ORDER BY runs DESC", params)]
        by_feature = [dict(r) for r in self._exec(
            "SELECT feature, operation, COUNT(*) AS runs, COALESCE(SUM(total_tokens),0) AS total_tokens, "
            "COALESCE(SUM(cost_usd),0) AS cost_usd FROM runs" + clause
            + " GROUP BY feature, operation ORDER BY runs DESC", params)]
        return {"totals": totals, "by_model": by_model, "by_feature": by_feature}

    # ------------------------------------------------------------------ llm calls
    def insert_llm_call(self, rec: dict[str, Any]) -> None:
        values = [int(bool(rec.get(c))) if c in _BOOL_COLS else rec.get(c) for c in _LLM_CALL_COLS]
        self._exec(f"INSERT OR REPLACE INTO llm_calls ({', '.join(_LLM_CALL_COLS)}) "
                   f"VALUES ({', '.join('?' * len(_LLM_CALL_COLS))})", values)

    def llm_calls_for(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._exec("SELECT * FROM llm_calls WHERE request_id=? ORDER BY rowid", (run_id,))
        return [{k: (bool(v) if k in _BOOL_COLS else v) for k, v in dict(r).items()} for r in rows]

    # ------------------------------------------------------------------ cache
    def cache_get(self, key: str) -> str | None:
        rows = self._exec("SELECT response_json FROM llm_cache WHERE cache_key=?", (key,))
        return rows[0]["response_json"] if rows else None

    def cache_put(self, key: str, step: str, prompt_version: int, fingerprint: str, response_json: str) -> None:
        self._exec("INSERT OR REPLACE INTO llm_cache (cache_key, step, prompt_version, model_fingerprint, "
                   "response_json, created_at) VALUES (?,?,?,?,?,?)",
                   (key, step, prompt_version, fingerprint, response_json, now_iso()))

    def cache_count(self) -> int:
        return self._exec("SELECT COUNT(*) AS n FROM llm_cache")[0]["n"]


def _percentile(sorted_values: list[int], q: float) -> int | None:
    if not sorted_values:
        return None
    idx = min(len(sorted_values) - 1, max(0, round(q * (len(sorted_values) - 1))))
    return int(sorted_values[idx])
