"""FakeLLM for tests and offline demos: canned JSON per (fixture, step) plus failure injection.

It implements the same interface as LLMGateway and writes the same audit records (with estimated tokens),
so runs, traces and metrics behave as they do against a real model.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.errors import LLMInvalidJSON, LLMRateLimited, LLMRefusal, LLMTimeout, LLMTruncated, LLMUnavailable
from app.core.hashing import canonical_json
from app.core.ids import new_call_id
from app.llm.client import validate_schema
from app.llm.types import CallContext, LLMResult, ModelInfo, Usage

FAILURES = {
    "timeout": LLMTimeout,
    "truncated": LLMTruncated,
    "invalid_json": LLMInvalidJSON,
    "unavailable": LLMUnavailable,
    "rate_limited": LLMRateLimited,
    "refusal": LLMRefusal,
}
CHARS_PER_TOKEN = 3.2

# A response spec is: dict (returned) | list (one per call, last repeats) | failure name | callable.
ResponseSpec = dict[str, Any] | list[Any] | str | Callable[[str, str, dict], Any]


class FakeLLM:
    profile_id = "fake"
    model = "fake-model"

    def __init__(self, responses: dict[str, ResponseSpec] | None = None,
                 fixture_dir: Path | None = None, fixture: str | None = None, context: int = 8192):
        self.responses = dict(responses or {})
        self.fixture_dir = fixture_dir
        self.fixture = fixture
        self.calls: list[dict[str, Any]] = []
        self._context = context
        self._n: dict[str, int] = defaultdict(int)
        self.store: Any = None  # set by the app factory so audit rows land in SQLite like the real gateway

    def describe(self, profile_id: str | None) -> ModelInfo:
        return ModelInfo(profile=profile_id or self.profile_id, provider="fake", model=self.model,
                         label="Fake model (tests)", fingerprint="fake")

    def context_tokens(self, ctx: CallContext | None) -> int:
        return self._context

    def _spec(self, step: str) -> ResponseSpec:
        if step in self.responses:
            return self.responses[step]
        if self.fixture_dir and self.fixture:
            path = self.fixture_dir / f"{self.fixture}.{step}.json"
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        raise LookupError(f"FakeLLM: no canned response for step {step!r} (fixture={self.fixture})")

    def _record(self, ctx: CallContext, step: str, attempt: int, prompt_version: int, system: str, user: str,
                raw: str, parsed: dict[str, Any] | None, error: str | None) -> str:
        usage = Usage.estimate(CHARS_PER_TOKEN, system + user, raw)
        call_id = new_call_id()
        rec = {
            "id": call_id, "request_id": ctx.request_id, "created_at": datetime.now(UTC).isoformat(),
            "feature": ctx.feature, "step": step, "attempt": attempt, "prompt_version": prompt_version,
            "cache_key": "fake", "cache_hit": False, "profile": ctx.profile_id or self.profile_id,
            "provider": "fake", "model": self.model,
            "request_json": canonical_json({"system": system, "user": user}), "response_raw": raw,
            "parsed_json": canonical_json(parsed) if parsed is not None else None,
            "finish_reason": "error" if error else "stop", "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens, "total_tokens": usage.total_tokens,
            "usage_estimated": True, "cost_usd": 0.0, "latency_ms": 0, "error_type": error, "error": error,
        }
        ctx.records.append(rec)
        if self.store is not None:
            self.store.insert_llm_call(rec)
        return call_id

    async def chat_json(self, step: str, prompt_version: int, system: str, user: str, schema: dict,
                        max_tokens: int, *, ctx: CallContext | None = None, attempt: int = 1) -> LLMResult:
        ctx = ctx or CallContext(request_id="-")
        idx = self._n[step]
        self._n[step] += 1
        self.calls.append({"step": step, "system": system, "user": user, "max_tokens": max_tokens})
        spec = self._spec(step)
        if isinstance(spec, list):
            spec = spec[min(idx, len(spec) - 1)]
        if callable(spec):
            spec = spec(system, user, schema)
        if isinstance(spec, str):
            self._record(ctx, step, attempt, prompt_version, system, user, "", None, spec)
            raise FAILURES[spec](f"injected {spec}")
        raw = json.dumps(spec)
        try:
            validate_schema(spec, schema)
        except LLMInvalidJSON as e:
            self._record(ctx, step, attempt, prompt_version, system, user, raw, None, f"LLMInvalidJSON: {e}")
            raise
        call_id = self._record(ctx, step, attempt, prompt_version, system, user, raw, spec, None)
        usage = Usage.estimate(CHARS_PER_TOKEN, system + user, raw)
        return LLMResult(spec, raw, "stop", usage.prompt_tokens, usage.completion_tokens, 0, False, call_id,
                         0.0, True)

    async def stream_json(self, step: str, prompt_version: int, system: str, user: str, schema: dict,
                          max_tokens: int, *, ctx: CallContext | None = None) -> AsyncIterator[str]:
        res = await self.chat_json(step, prompt_version, system, user, schema, max_tokens, ctx=ctx)
        for i in range(0, len(res.raw), 40):  # small chunks, like a real stream
            yield res.raw[i:i + 40]

    async def probe(self, profile_id: str | None = None) -> str | None:
        return None

    async def aclose(self) -> None:
        return None
