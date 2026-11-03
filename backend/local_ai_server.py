"""Standalone, loopback-only AI API for JD Standardizer and Applicant Match.

Run with: python -m uvicorn local_ai_server:app --host 127.0.0.1 --port 8000
The ATS web app can point its JD & Applicant Match panel at this API. All model
inference then stays on the user's computer (for example, Ollama at 127.0.0.1:11434).
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.api.deps import Platform, platform, require_api_key
from app.config import get_settings
from app.core.ids import new_request_id
from app.features.applicant_match.routes import router as applicant_match_router
from app.features.jd_standardizer.pipeline.policy import load_policy
from app.features.jd_standardizer.pipeline.runner import PipelineDeps
from app.features.jd_standardizer.routes import router as jd_router
from app.llm.client import CallContext, LLMGateway
from app.llm.registry import ModelRegistry
from app.store.db import Store


class AssistantRequest(BaseModel):
    message: str = Field(min_length=1, max_length=15000)


LOCAL_FRONTEND_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://bluepace-ats-frontend.vercel.app",
    "https://bluepace-ats-frontend.onrender.com",
    "https://bluepace-ats-live.vercel.app",
    "https://kind-smoke-0db2ba703.3.azurestaticapps.net",
)


def allowed_origins() -> list[str]:
    configured = os.getenv("LOCAL_AI_ALLOWED_ORIGINS", "")
    return list(dict.fromkeys([
        *LOCAL_FRONTEND_ORIGINS,
        *(origin.strip() for origin in configured.split(",") if origin.strip()),
    ]))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    store = Store(settings.DB_PATH)
    llm: LLMGateway | None = None
    try:
        models_path = Path(settings.MODELS_FILE)
        if not models_path.is_file():
            raise RuntimeError(f"Model configuration was not found: {models_path}")
        registry = ModelRegistry.from_file(models_path, settings.LLM_PROFILE or None)
        llm = LLMGateway(registry, settings, store=store)
        jd_deps = PipelineDeps(llm=llm, store=store, settings=settings, policy=load_policy())
        app.state.platform = Platform(
            settings=settings,
            store=store,
            llm=llm,
            registry=registry,
            jd=jd_deps,
        )
        print(
            "[local-ai] ready; default_profile="
            + registry.default_id
            + "; model="
            + registry.get(registry.default_id).model,
            flush=True,
        )
        yield
    finally:
        app.state.platform = None
        if llm is not None:
            await llm.aclose()
        store.close()


app = FastAPI(
    title="BluePace Local AI API",
    version="1.0.0",
    description="Local-only JD Standardizer and Applicant Match inference API.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/healthz", tags=["Local AI"])
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "bluepace-local-ai", "inference": "local"}


@app.get("/v1/models", tags=["Local AI"], dependencies=[Depends(require_api_key)])
async def list_models(p: Platform = Depends(platform)) -> list[dict]:
    if p.registry is None:
        raise HTTPException(status_code=503, detail="Local AI model registry is unavailable.")
    # This companion starts exactly one local model profile. Do not expose
    # other locally configured endpoints (for example LM Studio on port 1235)
    # as selectable when this process only starts Ollama.
    return [
        profile.model_dump(mode="json")
        for profile in p.registry.statuses()
        if profile.id == p.registry.default_id
    ]


@app.get(
    "/v1/models/{profile_id}/health",
    tags=["Local AI"],
    dependencies=[Depends(require_api_key)],
)
async def model_health(profile_id: str, p: Platform = Depends(platform)) -> dict[str, object]:
    if p.registry is None or profile_id != p.registry.default_id:
        raise HTTPException(status_code=404, detail=f"Unknown local model profile: {profile_id}")
    problem = await p.llm.probe(profile_id)
    return {"profile": profile_id, "ok": problem is None, "detail": problem}


@app.post("/v1/assistant", tags=["Local AI"], dependencies=[Depends(require_api_key)])
async def jd_match_assistant(body: AssistantRequest, p: Platform = Depends(platform)) -> dict[str, object]:
    """Answer JD & Applicant Match workflow questions through the configured local model."""
    profile_id = p.registry.default_id if p.registry is not None else None
    ctx = CallContext(
        request_id=new_request_id(),
        profile_id=profile_id,
        feature="jd_applicant_match_assistant",
    )
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    result = await p.llm.chat_json(
        step="jd_match_assistant",
        prompt_version=1,
        system=(
            "You are the BluePace JD & Applicant Match workflow assistant. "
            "Give concise, practical recruiter guidance about job description standardization, "
            "requirements, rubrics and evidence-based applicant review. Never make hiring or rejection "
            "decisions. Never invent missing job facts; flag them for recruiter confirmation."
        ),
        user=body.message,
        schema=schema,
        max_tokens=700,
        ctx=ctx,
    )
    info = p.llm.describe(profile_id)
    return {"answer": result.parsed.get("answer", ""), "model": info.model, "local": bool(p.registry and p.registry.get(profile_id).local)}


app.include_router(jd_router)
app.include_router(applicant_match_router)
