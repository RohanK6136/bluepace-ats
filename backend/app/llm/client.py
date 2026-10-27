"""LLM gateway: the single entry point features use to call any model.

Responsibilities, once for every provider:
- resolve the model profile for the run (CallContext.profile_id → registry; disabled profiles fail fast)
- response cache keyed on prompt, schema, profile and sampling settings
- per-profile concurrency limit
- JSON extraction + full JSON-schema validation of every answer
- token accounting (provider usage, or an estimate flagged as such) and cost from the profile's pricing
- one audit record per attempt (SQLite + in-memory for the run trace), Prometheus metrics, structured logs
Retry policy lives in `call_with_retry`, outside the gateway, so FakeLLM gets the same behaviour in tests.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Protocol

import jsonschema

from app.config import Settings
from app.core import metrics
from app.core.errors import (
    LLMBudgetExceeded,
    LLMError,
    LLMInvalidJSON,
    LLMRateLimited,
    LLMRefusal,
    LLMStepFailed,
    LLMTruncated,
    LLMUnavailable,
)
from app.core.hashing import canonical_json, sha256_hex
from app.core.ids import new_call_id
from app.core.logging import log_event
from app.llm.providers import make_provider
from app.llm.providers.base import Provider, parse_json_tolerant, strip_think
from app.llm.registry import ModelRegistry
from app.llm.types import (
    CallContext,
    LLMResult,
    ModelInfo,
    ModelProfile,
    ProviderRequest,
    ProviderResponse,
    Usage,
)

__all__ = ["CallContext", "ChatLLM", "LLMGateway", "LLMResult", "call_with_retry", "estimate_tokens",
           "validate_schema"]


class ChatLLM(Protocol):
    async def chat_json(self, step: str, prompt_version: int, system: str, user: str, schema: dict,
                        max_tokens: int, *, ctx: CallContext | None = None, attempt: int = 1) -> LLMResult: ...

    def stream_json(self, step: str, prompt_version: int, system: str, user: str, schema: dict,
                    max_tokens: int, *, ctx: CallContext | None = None) -> AsyncIterator[str]: ...

    def context_tokens(self, ctx: CallContext | None) -> int: ...

    def describe(self, profile_id: str | None) -> ModelInfo: ...


def validate_schema(data: dict[str, Any], schema: dict[str, Any]) -> None:
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as e:
        raise LLMInvalidJSON(f"schema violation: {e.message}") from None


def estimate_tokens(chars_per_token: float, *texts: str) -> int:
    return math.ceil(sum(len(t) for t in texts) / chars_per_token)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class LLMGateway:
    def __init__(self, registry: ModelRegistry, settings: Settings, store: Any = None,
                 providers: dict[str, Provider] | None = None):
        self.registry = registry
        self.settings = settings
        self.store = store
        self._providers: dict[str, Provider] = dict(providers or {})
        self._sems: dict[str, asyncio.Semaphore] = {}

    async def aclose(self) -> None:
        for provider in self._providers.values():
            await provider.aclose()

    # ------------------------------------------------------------------ plumbing
    def provider(self, profile: ModelProfile) -> Provider:
        if profile.id not in self._providers:
            self._providers[profile.id] = make_provider(profile, self.registry.json_instruction)
        return self._providers[profile.id]

    def _sem(self, profile: ModelProfile) -> asyncio.Semaphore:
        if profile.id not in self._sems:
            self._sems[profile.id] = asyncio.Semaphore(max(1, profile.concurrency))
        return self._sems[profile.id]

    def describe(self, profile_id: str | None) -> ModelInfo:
        p = self.registry.get(profile_id)
        return ModelInfo(profile=p.id, provider=p.provider, model=p.model, label=p.label,
                         fingerprint=p.fingerprint_or_unpinned)

    def context_tokens(self, ctx: CallContext | None) -> int:
        return self.registry.get(ctx.profile_id if ctx else None).context_tokens

    def cache_key(self, profile: ModelProfile, step: str, prompt_version: int, schema: dict, system: str,
                  user: str) -> str:
        return sha256_hex(canonical_json({
            "step": step, "prompt_version": prompt_version, "schema": schema, "system": system, "user": user,
            "profile": profile.id, "provider": profile.provider, "model": profile.model,
            "fingerprint": profile.fingerprint_or_unpinned, "temperature": profile.temperature,
            "top_p": profile.top_p, "seed": profile.seed, "structured": profile.structured_output,
            "extra_body": profile.extra_body, "effort": profile.effort,
        }))

    def _finalize(self, profile: ModelProfile, req: ProviderRequest, resp: ProviderResponse) -> dict[str, Any]:
        if resp.finish_reason == "length":
            raise LLMTruncated(f"hit max_tokens={max(req.max_tokens, profile.max_tokens_floor)}")
        if resp.finish_reason == "refusal":
            raise LLMRefusal(f"{profile.id} declined the request")
        parsed = parse_json_tolerant(strip_think(resp.text))
        validate_schema(parsed, req.schema)
        return parsed

    def _usage(self, req: ProviderRequest, resp: ProviderResponse | None, raw: str) -> Usage:
        if resp is not None and resp.usage is not None:
            return resp.usage
        return Usage.estimate(self.settings.CHARS_PER_TOKEN, req.system + req.user, raw)

    # ------------------------------------------------------------------ calls
    async def chat_json(self, step: str, prompt_version: int, system: str, user: str, schema: dict,
                        max_tokens: int, *, ctx: CallContext | None = None, attempt: int = 1) -> LLMResult:
        ctx = ctx or CallContext(request_id="-")
        profile = self.registry.require_enabled(ctx.profile_id)
        req = ProviderRequest(step, system, user, schema, max_tokens)
        key = self.cache_key(profile, step, prompt_version, schema, system, user)
        call_id = new_call_id()

        cached = self._cache_get(ctx, key)
        if cached is not None:
            self._record(ctx, profile, req, prompt_version, attempt, key, call_id, cached[1], cached[0], "cache",
                         Usage(), 0, cache_hit=True, error=None)
            return LLMResult(cached[0], cached[1], "cache", 0, 0, 0, True, call_id)

        t0 = time.perf_counter()
        resp: ProviderResponse | None = None
        try:
            async with self._sem(profile):
                resp = await self.provider(profile).complete(req)
            parsed = self._finalize(profile, req, resp)
        except LLMError as e:
            raw = resp.text if resp else ""
            self._record(ctx, profile, req, prompt_version, attempt, key, call_id, raw, None,
                         resp.finish_reason if resp else "", self._usage(req, resp, raw) if resp else Usage(),
                         int((time.perf_counter() - t0) * 1000), cache_hit=False, error=e)
            raise
        latency = int((time.perf_counter() - t0) * 1000)
        usage = self._usage(req, resp, resp.text)
        self._cache_put(ctx, profile, key, step, prompt_version, parsed)
        rec = self._record(ctx, profile, req, prompt_version, attempt, key, call_id, resp.text, parsed,
                           resp.finish_reason, usage, latency, cache_hit=False, error=None)
        return LLMResult(parsed, resp.text, resp.finish_reason, usage.prompt_tokens, usage.completion_tokens,
                         latency, False, call_id, rec["cost_usd"], usage.estimated)

    async def stream_json(self, step: str, prompt_version: int, system: str, user: str, schema: dict,
                          max_tokens: int, *, ctx: CallContext | None = None) -> AsyncIterator[str]:
        """Yield text deltas; the joined text is validated at the end (raises on failure).

        A cache hit yields the cached JSON in one piece.
        """
        ctx = ctx or CallContext(request_id="-")
        profile = self.registry.require_enabled(ctx.profile_id)
        req = ProviderRequest(step, system, user, schema, max_tokens)
        key = self.cache_key(profile, step, prompt_version, schema, system, user)
        call_id = new_call_id()

        cached = self._cache_get(ctx, key)
        if cached is not None:
            self._record(ctx, profile, req, prompt_version, 1, key, call_id, cached[1], cached[0], "cache",
                         Usage(), 0, cache_hit=True, error=None)
            yield cached[1]
            return

        t0 = time.perf_counter()
        parts: list[str] = []
        resp: ProviderResponse | None = None
        try:
            async with self._sem(profile):
                async for event in self.provider(profile).stream(req):
                    if isinstance(event, ProviderResponse):
                        resp = event
                    else:
                        parts.append(event)
                        yield event
            if resp is None:
                raise LLMUnavailable("stream ended without a final response")
            parsed = self._finalize(profile, req, resp)
        except LLMError as e:
            raw = "".join(parts)
            usage = self._usage(req, resp, raw) if (parts or resp) else Usage()
            self._record(ctx, profile, req, prompt_version, 1, key, call_id, raw, None,
                         resp.finish_reason if resp else "", usage, int((time.perf_counter() - t0) * 1000),
                         cache_hit=False, error=e)
            raise
        usage = self._usage(req, resp, resp.text)
        self._cache_put(ctx, profile, key, step, prompt_version, parsed)
        self._record(ctx, profile, req, prompt_version, 1, key, call_id, resp.text, parsed, resp.finish_reason,
                     usage, int((time.perf_counter() - t0) * 1000), cache_hit=False, error=None)

    # ------------------------------------------------------------------ health
    async def list_models(self, profile_id: str | None = None) -> list[str]:
        return await self.provider(self.registry.require_enabled(profile_id)).list_models()

    async def probe(self, profile_id: str | None = None) -> str | None:
        profile = self.registry.get(profile_id)
        reason = self.registry.disabled_reason(profile)
        if reason:
            return reason
        return await self.provider(profile).probe(self.settings.READYZ_PROBE_TIMEOUT_S)

    # ------------------------------------------------------------------ cache + audit
    def _cache_get(self, ctx: CallContext, key: str) -> tuple[dict[str, Any], str] | None:
        if not (ctx.use_cache and self.store is not None):
            return None
        cached = self.store.cache_get(key)
        return (json.loads(cached), cached) if cached is not None else None

    def _cache_put(self, ctx: CallContext, profile: ModelProfile, key: str, step: str, prompt_version: int,
                   parsed: dict[str, Any]) -> None:
        if ctx.use_cache and self.store is not None:
            self.store.cache_put(key, step, prompt_version, f"{profile.id}|{profile.fingerprint_or_unpinned}",
                                 canonical_json(parsed))

    def _record(self, ctx: CallContext, profile: ModelProfile, req: ProviderRequest, prompt_version: int,
                attempt: int, key: str, call_id: str, raw: str, parsed: dict[str, Any] | None, finish: str,
                usage: Usage, latency_ms: int, *, cache_hit: bool, error: Exception | None) -> dict[str, Any]:
        cost = 0.0 if cache_hit else profile.pricing.cost(usage.prompt_tokens, usage.completion_tokens)
        rec = {
            "id": call_id, "request_id": ctx.request_id, "created_at": _now(), "feature": ctx.feature,
            "step": req.step, "attempt": attempt, "prompt_version": prompt_version, "cache_key": key,
            "cache_hit": cache_hit, "profile": profile.id, "provider": profile.provider, "model": profile.model,
            "request_json": canonical_json({"system": req.system, "user": req.user, "schema": req.schema,
                                            "max_tokens": max(req.max_tokens, profile.max_tokens_floor)}),
            "response_raw": raw, "parsed_json": canonical_json(parsed) if parsed is not None else None,
            "finish_reason": finish, "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens, "total_tokens": usage.total_tokens,
            "usage_estimated": usage.estimated, "cost_usd": cost, "latency_ms": latency_ms,
            "error_type": type(error).__name__ if error else None,
            "error": f"{type(error).__name__}: {error}" if error else None,
        }
        ctx.records.append(rec)
        if self.store is not None:
            self.store.insert_llm_call(rec)

        outcome = "cache_hit" if cache_hit else (type(error).__name__ if error else "ok")
        metrics.LLM_CALLS.labels(profile.id, profile.model, req.step, outcome).inc()
        if not cache_hit:
            metrics.LLM_TOKENS.labels(profile.id, profile.model, "prompt").inc(usage.prompt_tokens)
            metrics.LLM_TOKENS.labels(profile.id, profile.model, "completion").inc(usage.completion_tokens)
            metrics.LLM_COST.labels(profile.id, profile.model).inc(cost)
            metrics.LLM_LATENCY.labels(profile.id, req.step).observe(latency_ms / 1000)
        log_event("llm_call", run_id=ctx.request_id, feature=ctx.feature, step=req.step, attempt=attempt,
                  profile=profile.id, model=profile.model, cache_hit=cache_hit, duration_ms=latency_ms,
                  prompt_tokens=usage.prompt_tokens, completion_tokens=usage.completion_tokens,
                  usage_estimated=usage.estimated, cost_usd=cost, error=rec["error"])
        return rec


async def call_with_retry(llm: ChatLLM, ctx: CallContext, settings: Settings, step: str, prompt_version: int,
                          system: str, user: str, schema: dict, max_tokens: int) -> LLMResult:
    """Token guard + retry policy. LLMUnavailable/LLMConfigError propagate; other failures → LLMStepFailed."""
    context = llm.context_tokens(ctx)
    est = estimate_tokens(settings.CHARS_PER_TOKEN, system, user)
    if est + max_tokens > context:
        raise LLMBudgetExceeded(f"{step}: ~{est}+{max_tokens} tokens exceeds the model's {context}-token context")
    attempts = 1 + settings.MAX_REPAIR_RETRIES
    last: Exception | None = None
    mt = max_tokens
    for attempt in range(1, attempts + 1):
        try:
            return await llm.chat_json(step, prompt_version, system, user, schema, mt, ctx=ctx, attempt=attempt)
        except LLMUnavailable:
            raise
        except LLMError as e:
            last = e
            if not e.retryable:
                break
            if isinstance(e, LLMTruncated):
                mt = min(math.ceil(mt * 1.5), context - est)
            if isinstance(e, LLMRateLimited):
                await asyncio.sleep(min(2 ** attempt, 8))
        if attempt < attempts:
            ctx.repairs += 1
    raise LLMStepFailed(step, last or RuntimeError("unknown"))
