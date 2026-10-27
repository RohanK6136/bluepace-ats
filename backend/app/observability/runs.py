"""Run tracking shared by every feature: one row per feature invocation with its input, output, model,
token usage, cost, latency and outcome, plus metrics and a structured log line.

Usage inside a feature:

    rec = RunRecorder(store, settings, feature="jd_standardizer", operation="generate", ctx=ctx, model=info, ...)
    rec.start(source_type="text", input_text=text)
    ...
    rec.finish(status="ok", outcome="success", title="Java Developer", result=result, trace=trace)
    # or rec.fail(exc) from an except block
"""

from __future__ import annotations

import json
import time
from typing import Any, Literal

from pydantic import BaseModel

from app.config import Settings
from app.core import metrics
from app.core.hashing import canonical_json, sha256_hex
from app.core.logging import api_key_id, client_ip, http_request_id, log_event
from app.llm.types import CallContext, ModelInfo
from app.store.db import now_iso

Outcome = Literal["success", "degraded", "rejected", "error"]
PREVIEW_CHARS = 240


class RunRecorder:
    def __init__(self, store: Any, settings: Settings, *, feature: str, operation: str, ctx: CallContext,
                 model: ModelInfo, options: BaseModel | None = None, overrides: BaseModel | None = None,
                 pipeline_version: str | None = None):
        self.store = store
        self.settings = settings
        self.feature = feature
        self.operation = operation
        self.ctx = ctx
        self.model = model
        self.options = options
        self.overrides = overrides
        self.pipeline_version = pipeline_version
        self._t0 = time.perf_counter()
        self._started = False
        self._finished = False

    @property
    def run_id(self) -> str:
        return self.ctx.request_id

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._t0) * 1000)

    def start(self, *, source_type: str, input_text: str) -> None:
        self._started = True
        log_event("run_started", run_id=self.run_id, feature=self.feature, operation=self.operation,
                  profile=self.model.profile, model=self.model.model, source_type=source_type,
                  input_chars=len(input_text))
        if self.store is None:
            return
        keep = self.settings.STORE_PAYLOADS
        self.store.insert_run({
            "id": self.run_id, "created_at": now_iso(), "feature": self.feature, "operation": self.operation,
            "status": "running", "profile": self.model.profile, "provider": self.model.provider,
            "model": self.model.model, "source_type": source_type, "input_hash": sha256_hex(input_text),
            "input_chars": len(input_text),
            "input_preview": " ".join(input_text.split())[:PREVIEW_CHARS] if keep else None,
            "input_text": input_text if keep else None,
            "options_json": self.options.model_dump_json() if self.options else None,
            "overrides_json": self.overrides.model_dump_json(exclude_none=True) if self.overrides else None,
            "pipeline_version": self.pipeline_version, "app_version": self.settings.APP_VERSION,
            "http_request_id": http_request_id.get(), "client_ip": client_ip.get(), "api_key_id": api_key_id.get(),
        })

    def _usage_fields(self) -> dict[str, Any]:
        recs = self.ctx.records
        return {
            "llm_calls": len(recs), "cache_hits": self.ctx.cache_hits, "repairs": self.ctx.repairs,
            "prompt_tokens": self.ctx.prompt_tokens, "completion_tokens": self.ctx.completion_tokens,
            "total_tokens": self.ctx.prompt_tokens + self.ctx.completion_tokens,
            "usage_estimated": int(any(r.get("usage_estimated") for r in recs)), "cost_usd": self.ctx.cost_usd,
        }

    def finish(self, *, status: str, outcome: Outcome, title: str | None = None,
               result: BaseModel | dict[str, Any] | None = None, trace: dict[str, Any] | None = None,
               llm_ms: int | None = None, error: str | None = None) -> None:
        if self._finished:
            return
        self._finished = True
        latency = self.elapsed_ms()
        usage = self._usage_fields()
        metrics.RUNS.labels(self.feature, self.operation, outcome).inc()
        metrics.RUN_LATENCY.labels(self.feature, self.operation).observe(latency / 1000)
        log_event("run_finished", run_id=self.run_id, feature=self.feature, operation=self.operation,
                  status=status, outcome=outcome, duration_ms=latency, llm_ms=llm_ms, profile=self.model.profile,
                  model=self.model.model, **{k: usage[k] for k in ("llm_calls", "prompt_tokens",
                                                                    "completion_tokens", "cost_usd")},
                  error=error)
        if self.store is None or not self._started:
            return
        keep = self.settings.STORE_PAYLOADS
        if isinstance(result, BaseModel):
            result_json = result.model_dump_json(exclude={"trace"})
        else:
            result_json = canonical_json(result) if result is not None else None
        self.store.update_run(self.run_id, {
            "finished_at": now_iso(), "status": status, "outcome": outcome, "title": title, "latency_ms": latency,
            "llm_ms": llm_ms, "error": error, **usage,
            "result_json": result_json if keep else None,
            "trace_json": json.dumps(trace, default=str) if (trace is not None and keep) else None,
        })

    def fail(self, exc: BaseException) -> None:
        self.finish(status="error", outcome="error", error=f"{type(exc).__name__}: {exc}",
                    trace={"llm_calls": self.ctx.records})
