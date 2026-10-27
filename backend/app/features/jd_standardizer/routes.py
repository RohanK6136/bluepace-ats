"""HTTP API of the JD Standardizer feature (/v1/jd/...)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api.deps import Platform, ensure_profile, platform, require_api_key
from app.core.errors import IngestError
from app.core.ids import new_request_id
from app.core.ingest import ALLOWED_EXTS
from app.features.jd_standardizer.pipeline.generate import GenerateResult, generate_events
from app.features.jd_standardizer.pipeline.models import Options, Overrides, Result
from app.features.jd_standardizer.pipeline.runner import PipelineInput, run_pipeline

router = APIRouter(prefix="/v1/jd", tags=["JD Standardizer"], dependencies=[Depends(require_api_key)])
UPLOAD_HELP = f"one of {sorted(ALLOWED_EXTS)}"
GENERATE_DOC = ("Fast mode: rules parse the text, then one streamed model call writes only what is missing (title, "
                "short description, about the role, responsibilities, qualifications, preferred skills). With "
                "stream=true the response is NDJSON events: start (instant rule-based preview), delta (model "
                "text), final (GenerateResult). Choose the model with options.profile (see GET /v1/models).")


class JDRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., description="Pasted job description, partial JD, or short brief")
    options: Options = Field(default_factory=Options)
    overrides: Overrides = Field(default_factory=Overrides)


# ------------------------------------------------------------------ helpers
def _check_text(p: Platform, text: str) -> None:
    if len(text) > p.settings.MAX_INPUT_CHARS:
        raise HTTPException(status_code=400, detail=f"text exceeds MAX_INPUT_CHARS ({p.settings.MAX_INPUT_CHARS})")


def _parse_json_form(raw: str | None, model: type[Options] | type[Overrides]) -> Any:
    if not raw:
        return model()
    try:
        return model.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as e:
        raise HTTPException(status_code=422, detail=f"invalid {model.__name__.lower()}: {e}") from None


async def _read_upload(file: UploadFile, p: Platform) -> PipelineInput:
    name = file.filename or "upload.txt"
    if not any(name.casefold().endswith(ext) for ext in ALLOWED_EXTS):
        raise HTTPException(status_code=400, detail=f"unsupported file type; allowed: {sorted(ALLOWED_EXTS)}")
    limit = int(p.settings.MAX_UPLOAD_MB * 1024 * 1024)
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=400, detail=f"upload exceeds MAX_UPLOAD_MB ({p.settings.MAX_UPLOAD_MB})")
    return PipelineInput(filename=name, data=data)


def _event_line(ev: dict[str, Any]) -> bytes:
    if "result" in ev:
        ev = {**ev, "result": ev["result"].model_dump(mode="json")}
    return (json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8")


async def _standardize(inp: PipelineInput, options: Options, overrides: Overrides, p: Platform) -> Result:
    ensure_profile(p, options.profile)
    rid = new_request_id()
    try:
        return await asyncio.wait_for(run_pipeline(inp, options, overrides, p.jd, request_id=rid),
                                      timeout=p.settings.REQUEST_TIMEOUT_S)
    except IngestError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except TimeoutError:
        raise HTTPException(status_code=504, detail=f"run {rid} exceeded REQUEST_TIMEOUT_S") from None


async def _generate(inp: PipelineInput, options: Options, overrides: Overrides, p: Platform, stream: bool) -> Any:
    ensure_profile(p, options.profile)
    events = generate_events(inp, options, overrides, p.jd)
    try:
        first = await anext(events)  # ingest errors surface here, before any bytes are sent
    except IngestError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    if not stream:
        final = first
        async for ev in events:
            final = ev
        return final["result"]

    async def ndjson() -> AsyncIterator[bytes]:
        try:
            yield _event_line(first)
            async for ev in events:
                yield _event_line(ev)
        finally:
            await events.aclose()  # client disconnect → stop the model call, record the run as cancelled

    return StreamingResponse(ndjson(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ fast mode
@router.post("/generate", response_model=GenerateResult, description=GENERATE_DOC)
async def generate_jd(body: JDRequest, stream: bool = False, p: Platform = Depends(platform)) -> Any:
    _check_text(p, body.text)
    return await _generate(PipelineInput(text=body.text), body.options, body.overrides, p, stream)


@router.post("/generate/upload", response_model=GenerateResult, description=GENERATE_DOC)
async def generate_jd_upload(
    file: UploadFile = File(..., description=UPLOAD_HELP),
    options: str | None = Form(default=None, description="Options as a JSON string"),
    overrides: str | None = Form(default=None, description="Overrides as a JSON string"),
    stream: bool = False,
    p: Platform = Depends(platform),
) -> Any:
    return await _generate(await _read_upload(file, p), _parse_json_form(options, Options),
                           _parse_json_form(overrides, Overrides), p, stream)


# ------------------------------------------------------------------ strict mode
@router.post("/standardize", response_model=Result,
             description="Strict mode: the 12-step specification pipeline (several small model calls).")
async def standardize(body: JDRequest, p: Platform = Depends(platform)) -> Result:
    _check_text(p, body.text)
    return await _standardize(PipelineInput(text=body.text), body.options, body.overrides, p)


@router.post("/standardize/upload", response_model=Result)
async def standardize_upload(
    file: UploadFile = File(..., description=UPLOAD_HELP),
    options: str | None = Form(default=None, description="Options as a JSON string"),
    overrides: str | None = Form(default=None, description="Overrides as a JSON string"),
    p: Platform = Depends(platform),
) -> Result:
    return await _standardize(await _read_upload(file, p), _parse_json_form(options, Options),
                              _parse_json_form(overrides, Overrides), p)


# ------------------------------------------------------------------ stored results (kept for API compatibility)
def _jd_run(p: Platform, run_id: str) -> dict[str, Any]:
    row = p.store.get_run(run_id)
    if not row or row["feature"] != "jd_standardizer":
        raise HTTPException(status_code=404, detail="not found")
    return row


@router.get("/{run_id}", summary="Stored JD result (same as /v1/runs/{id} → result)")
async def get_result(run_id: str, p: Platform = Depends(platform)) -> dict[str, Any]:
    row = _jd_run(p, run_id)
    if not row.get("result_json"):
        raise HTTPException(status_code=404, detail="no stored result (STORE_PAYLOADS may be off)")
    return json.loads(row["result_json"])


@router.get("/{run_id}/trace", summary="Pipeline trace plus every model call (prompts and raw output)")
async def get_trace(run_id: str, p: Platform = Depends(platform)) -> dict[str, Any]:
    row = _jd_run(p, run_id)
    trace = json.loads(row["trace_json"]) if row.get("trace_json") else {}
    return {**trace, "llm_calls": p.store.llm_calls_for(run_id)}
