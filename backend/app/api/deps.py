"""Request-scoped dependencies: the platform services, the JD feature's deps, and API-key auth."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Header, HTTPException, Request

from app.config import Settings
from app.core.logging import api_key_id
from app.features.jd_standardizer.pipeline.runner import PipelineDeps
from app.llm.client import ChatLLM
from app.llm.registry import ModelRegistry


@dataclass
class Platform:
    settings: Settings
    store: Any  # app.store.db.Store
    llm: ChatLLM
    registry: ModelRegistry | None  # None when a test LLM is injected
    jd: PipelineDeps


def platform(request: Request) -> Platform:
    configured = getattr(request.app.state, "platform", None)
    if configured is None:
        raise HTTPException(
            status_code=503,
            detail="AI feature platform is unavailable. Check backend startup logs and model configuration.",
        )
    return configured


def pipeline_deps(p: Platform = Depends(platform)) -> PipelineDeps:
    return p.jd


def require_api_key(x_api_key: str | None = Header(default=None), p: Platform = Depends(platform)) -> None:
    keys = p.settings.api_keys
    if not keys:
        return
    if not x_api_key or not any(secrets.compare_digest(x_api_key, k) for k in keys):
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")
    # recorded on every run so usage can be attributed per key without storing the key itself
    api_key_id.set(hashlib.sha256(x_api_key.encode()).hexdigest()[:10])


def ensure_profile(p: Platform, profile_id: str | None) -> None:
    """422 for an unknown or disabled model profile, before any work starts."""
    if p.registry is None or profile_id is None:
        return
    if profile_id not in p.registry.ids():
        raise HTTPException(status_code=422, detail=f"unknown model profile {profile_id!r}; see GET /v1/models")
    reason = p.registry.disabled_reason(p.registry.get(profile_id))
    if reason:
        raise HTTPException(status_code=422, detail=f"model profile {profile_id!r} is disabled: {reason}")
