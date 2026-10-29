"""Platform API: health, readiness, metrics, feature catalogue, model profiles, run history and usage."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.deps import Platform, platform, require_api_key
from app.core import metrics
from app.features.registry import FEATURES, FeatureInfo
from app.llm.types import ProfileStatus

router = APIRouter()
api = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])

WINDOWS = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}


# ------------------------------------------------------------------ health
class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    environment: str


class ReadyResponse(BaseModel):
    ready: bool
    database: bool
    schema_version: str | None
    default_profile: str | None
    model_ready: bool
    warnings: list[str] = Field(default_factory=list)


@router.get("/healthz", response_model=HealthResponse, tags=["Operations"], summary="Liveness")
async def healthz(p: Platform = Depends(platform)) -> HealthResponse:
    s = p.settings
    return HealthResponse(status="ok", app=s.APP_NAME, version=s.APP_VERSION, environment=s.ENVIRONMENT)


@router.get("/readyz", response_model=ReadyResponse, tags=["Operations"],
            summary="Readiness: database + a real 1-token request to the default model")
async def readyz(p: Platform = Depends(platform)) -> ReadyResponse:
    warnings: list[str] = []
    try:
        schema = p.store.schema_version()
        db_ok = True
    except Exception as e:  # noqa: BLE001 - report, don't crash the probe
        schema, db_ok = None, False
        warnings.append(f"database: {e}")
    default = p.registry.default_id if p.registry else None
    problem = await p.llm.probe(default) if hasattr(p.llm, "probe") else None  # type: ignore[attr-defined]
    if problem:
        warnings.append(f"model {default}: {problem}")
    return ReadyResponse(ready=db_ok and problem is None, database=db_ok, schema_version=schema,
                         default_profile=default, model_ready=problem is None, warnings=warnings)


@router.get("/metrics", tags=["Operations"], summary="Prometheus metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    body, content_type = metrics.render()
    return Response(body, media_type=content_type)


# ------------------------------------------------------------------ catalogue
@api.get("/features", response_model=list[FeatureInfo], tags=["Platform"])
async def list_features() -> list[FeatureInfo]:
    return FEATURES


@api.get("/models", response_model=list[ProfileStatus], tags=["Platform"],
         summary="Configured model profiles (no secrets) and whether each is usable")
async def list_models(p: Platform = Depends(platform)) -> list[ProfileStatus]:
    if p.registry is None:
        info = p.llm.describe(None)
        return [ProfileStatus(id=info.profile or "fake", label=info.label or "Test model", provider="openai_compatible",
                              model=info.model or "", local=True, description="injected test model", enabled=True,
                              is_default=True, pricing={}, context_tokens=p.llm.context_tokens(None))]
    return p.registry.statuses()


class ModelHealth(BaseModel):
    profile: str
    ok: bool
    detail: str | None = None


@api.get("/models/{profile_id}/health", response_model=ModelHealth, tags=["Platform"],
         summary="Live check of one profile (local: 1-token request; Anthropic: credentials + model id)")
async def model_health(profile_id: str, p: Platform = Depends(platform)) -> ModelHealth:
    if p.registry is not None and profile_id not in p.registry.ids():
        raise HTTPException(status_code=404, detail="unknown profile")
    problem = await p.llm.probe(profile_id)  # type: ignore[attr-defined]
    return ModelHealth(profile=profile_id, ok=problem is None, detail=problem)


# ------------------------------------------------------------------ runs
class RunSummary(BaseModel):
    id: str
    created_at: str
    finished_at: str | None = None
    feature: str
    operation: str
    status: str
    outcome: str | None = None
    title: str | None = None
    profile: str | None = None
    provider: str | None = None
    model: str | None = None
    source_type: str | None = None
    input_chars: int | None = None
    input_preview: str | None = None
    llm_calls: int = 0
    cache_hits: int = 0
    repairs: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    usage_estimated: bool = False
    cost_usd: float = 0.0
    latency_ms: int | None = None
    llm_ms: int | None = None
    error: str | None = None
    app_version: str | None = None
    pipeline_version: str | None = None
    http_request_id: str | None = None
    api_key_id: str | None = None


class LLMCallView(BaseModel):
    id: str
    created_at: str | None
    step: str
    attempt: int
    profile: str | None
    provider: str | None
    model: str | None
    cache_hit: bool
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    usage_estimated: bool
    cost_usd: float
    latency_ms: int | None
    error: str | None
    prompt_version: int | None
    request: dict[str, Any] | None = Field(description="system prompt, user prompt, JSON schema, max_tokens")
    response_raw: str | None
    parsed: dict[str, Any] | None


class RunDetail(RunSummary):
    input_text: str | None = None
    options: dict[str, Any] | None = None
    overrides: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    trace: dict[str, Any] | None = None
    calls: list[LLMCallView] = Field(default_factory=list)


class RunPage(BaseModel):
    items: list[RunSummary]
    next_before: str | None = Field(description="pass as ?before= to fetch the next (older) page")


def _since(window: str) -> str | None:
    return None if window == "all" else (datetime.now(UTC) - WINDOWS[window]).isoformat(timespec="milliseconds")


def _loads(value: str | None) -> Any:
    return json.loads(value) if value else None


@api.get("/runs", response_model=RunPage, tags=["Observability"], summary="Run history, newest first")
async def list_runs(
    feature: str | None = None, outcome: Literal["success", "degraded", "rejected", "error"] | None = None,
    profile: str | None = None, status: str | None = None, q: str | None = Query(None, max_length=200),
    window: Literal["1h", "24h", "7d", "30d", "all"] = "all", before: str | None = None,
    limit: int = Query(50, ge=1, le=200), p: Platform = Depends(platform),
) -> RunPage:
    rows = p.store.list_runs(feature=feature, outcome=outcome, profile=profile, status=status, query=q,
                             since=_since(window), before=before, limit=limit)
    items = [RunSummary(**{**r, "usage_estimated": bool(r.get("usage_estimated"))}) for r in rows]
    return RunPage(items=items, next_before=items[-1].created_at if len(items) == limit else None)


@api.get("/runs/{run_id}", response_model=RunDetail, tags=["Observability"],
         summary="One run: input, output, trace and every model call with prompts, raw output, tokens and cost")
async def get_run(run_id: str, p: Platform = Depends(platform)) -> RunDetail:
    row = p.store.get_run(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="run not found")
    calls = [LLMCallView(id=c["id"], created_at=c.get("created_at"), step=c["step"], attempt=c["attempt"],
                         profile=c.get("profile"), provider=c.get("provider"), model=c.get("model"),
                         cache_hit=bool(c["cache_hit"]), finish_reason=c.get("finish_reason"),
                         prompt_tokens=c.get("prompt_tokens"), completion_tokens=c.get("completion_tokens"),
                         total_tokens=c.get("total_tokens"), usage_estimated=bool(c.get("usage_estimated")),
                         cost_usd=c.get("cost_usd") or 0.0, latency_ms=c.get("latency_ms"), error=c.get("error"),
                         prompt_version=c.get("prompt_version"), request=_loads(c.get("request_json")),
                         response_raw=c.get("response_raw"), parsed=_loads(c.get("parsed_json")))
             for c in p.store.llm_calls_for(run_id)]
    base = {k: v for k, v in row.items() if k in RunSummary.model_fields}
    return RunDetail(**{**base, "usage_estimated": bool(row.get("usage_estimated"))},
                     input_text=row.get("input_text"), options=_loads(row.get("options_json")),
                     overrides=_loads(row.get("overrides_json")), result=_loads(row.get("result_json")),
                     trace=_loads(row.get("trace_json")), calls=calls)


@api.delete("/runs/{run_id}", status_code=204, tags=["Observability"],
            summary="Erase a run and its stored prompts, outputs and cache records")
async def erase_run(run_id: str, p: Platform = Depends(platform)) -> Response:
    # Deletion must never be anonymously callable, even when normal development auth is disabled.
    if not p.settings.api_keys:
        raise HTTPException(status_code=503, detail="Run erasure requires API_KEYS to be configured.")
    if not p.store.get_run(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    if not p.store.delete_run(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    return Response(status_code=204)


@api.get("/metrics/summary", tags=["Observability"],
         summary="Usage totals for a time window: runs by outcome, tokens, cost, latency percentiles, per model")
async def metrics_summary(window: Literal["1h", "24h", "7d", "30d", "all"] = "24h", feature: str | None = None,
                          p: Platform = Depends(platform)) -> dict[str, Any]:
    since = _since(window)
    return {"window": window, "since": since, "feature": feature, **p.store.run_summary(since=since, feature=feature)}
