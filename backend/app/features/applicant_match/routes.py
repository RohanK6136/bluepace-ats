"""HTTP API of Applicant Match (/v1/match/...). Decision support only: no endpoint shortlists, rejects or emails.

Errors use {"detail": {"code": "E_…", "message": "…"}}.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import Field, model_validator

from app.api.deps import Platform, ensure_profile, platform, require_api_key
from app.core.errors import IngestError, LLMError, LLMUnavailable
from app.core.ingest import ALLOWED_EXTS
from app.core.logging import api_key_id
from app.features.applicant_match.models import (
    Card,
    MatchOptions,
    Model,
    Rubric,
    RubricDraft,
    RubricSummary,
)
from app.features.applicant_match.rubric import JobError, freeze, job_from_result, job_from_text
from app.features.applicant_match.service import MatchDeps, NotAResume, ResumeInput, analyze, draft_rubric
from app.store.db import now_iso

router = APIRouter(prefix="/v1/match", tags=["Applicant Match"], dependencies=[Depends(require_api_key)])
RESUME_EXTS = {".pdf", ".docx", ".txt", ".md"} & ALLOWED_EXTS


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _deps(p: Platform) -> MatchDeps:
    return MatchDeps(llm=p.llm, store=p.store, settings=p.settings, jd_policy=p.jd.policy)


class RubricRequest(Model):
    """Exactly one of jd_run_id, jd_text, job (→ a draft rubric) or rubric (→ save an immutable version)."""

    jd_run_id: str | None = Field(default=None, description="A JD Standardizer run id (see GET /v1/match/jobs)")
    jd_text: str | None = Field(default=None, description="Raw job description text")
    job: dict[str, Any] | None = Field(default=None, description="A standardized job (JD Standardizer result JSON)")
    rubric: Rubric | None = Field(default=None, description="An edited draft to save")
    options: MatchOptions = Field(default_factory=MatchOptions)

    @model_validator(mode="after")
    def _one_source(self) -> RubricRequest:
        given = [k for k in ("jd_run_id", "jd_text", "job", "rubric") if getattr(self, k) not in (None, "")]
        if len(given) != 1:
            raise ValueError("send exactly one of jd_run_id, jd_text, job or rubric")
        return self


class JobChoice(Model):
    run_id: str
    title: str | None
    created_at: str
    operation: str


def _llm_http_error(e: LLMError) -> HTTPException:
    if isinstance(e, LLMUnavailable):
        return _err(503, "E_LLM_UNAVAILABLE", f"the model is unavailable: {e}")
    return _err(502, "E_LLM_FAILED", f"the model's answer was unusable after a retry: {e}")


# ------------------------------------------------------------------ jobs and rubrics
@router.get("/jobs", response_model=list[JobChoice], summary="JD Standardizer results that can be used as jobs")
async def list_jobs(limit: int = 30, p: Platform = Depends(platform)) -> list[JobChoice]:
    rows = p.store.list_runs(feature="jd_standardizer", outcome="success", limit=limit)
    return [JobChoice(run_id=r["id"], title=r.get("title"), created_at=r["created_at"], operation=r["operation"])
            for r in rows]


@router.post("/rubrics", response_model=RubricDraft | Rubric,
             description="Body {jd_run_id} | {jd_text} | {job} → a draft rubric for review (one model call). "
                         "Body {rubric} (the reviewed draft) → saves an immutable version and returns it with "
                         "rubric_id and rubric_hash. Identical content always gets the same id.")
async def rubrics(body: RubricRequest, p: Platform = Depends(platform)) -> RubricDraft | Rubric:
    if body.rubric is not None:
        try:
            frozen = freeze(body.rubric, now_iso())
        except JobError as e:
            raise _err(422, "E_RUBRIC_INVALID", str(e)) from None
        p.store.insert_rubric(frozen.rubric_id, frozen.rubric_hash, frozen.created_at, frozen.title,
                              frozen.job_ref, len(frozen.items), frozen.model_dump_json(), api_key_id.get())
        stored = p.store.get_rubric(frozen.rubric_id)
        return Rubric.model_validate_json(stored["rubric_json"]) if stored else frozen

    ensure_profile(p, body.options.profile)
    try:
        if body.jd_run_id:
            row = p.store.get_run(body.jd_run_id)
            if not row or row["feature"] != "jd_standardizer" or not row.get("result_json"):
                raise _err(404, "E_JOB_NOT_FOUND", f"no stored JD Standardizer result {body.jd_run_id!r}")
            job = job_from_result(json.loads(row["result_json"]), body.jd_run_id)
        elif body.job is not None:
            job = job_from_result(body.job, str(body.job.get("request_id") or "job"))
        else:
            text = body.jd_text or ""
            if len(text) > p.settings.MAX_INPUT_CHARS:
                raise _err(400, "E_INPUT_TOO_LARGE", f"text exceeds {p.settings.MAX_INPUT_CHARS} characters")
            job = job_from_text(text, p.jd.policy, p.settings)
    except JobError as e:
        raise _err(422, "E_JOB_INVALID", str(e)) from None
    try:
        return await asyncio.wait_for(draft_rubric(job, body.options, _deps(p)), timeout=p.settings.REQUEST_TIMEOUT_S)
    except LLMError as e:
        raise _llm_http_error(e) from None
    except TimeoutError:
        raise _err(504, "E_TIMEOUT", "rubric compile exceeded REQUEST_TIMEOUT_S") from None


@router.get("/rubrics", response_model=list[RubricSummary], summary="Saved rubric versions, newest first")
async def list_rubrics(limit: int = 50, p: Platform = Depends(platform)) -> list[RubricSummary]:
    current_key_id = api_key_id.get()
    rows = p.store.list_rubrics(limit)
    return [
        RubricSummary(rubric_id=r["id"], rubric_hash=r["hash"], title=r["title"], job_ref=r["job_ref"],
                      items=r["items"], created_at=r["created_at"])
        for r in rows
        if r.get("created_by") == current_key_id
    ]


def _load_rubric(p: Platform, rubric_id: str) -> Rubric:
    row = p.store.get_rubric(rubric_id)
    if not row or row.get("created_by") != api_key_id.get():
        raise _err(404, "E_RUBRIC_NOT_FOUND", f"no saved rubric {rubric_id!r}")
    return Rubric.model_validate_json(row["rubric_json"])


@router.get("/rubrics/{rubric_id}", response_model=Rubric, summary="A saved rubric version")
async def get_rubric(rubric_id: str, p: Platform = Depends(platform)) -> Rubric:
    return _load_rubric(p, rubric_id)


# ------------------------------------------------------------------ analyze
@router.post("/analyze", response_model=Card,
             description="Analyse one resume against a saved rubric. Multipart: rubric_id, and file (.pdf/.docx/"
                         ".txt/.md) or text; optional as_of (YYYY-MM-DD, the end date of current roles; default "
                         "today), refresh (bypass the model cache) and profile (model profile id). Returns the "
                         "applicant card. Personal details are redacted before any model call; the original file "
                         "and text are not stored.")
async def analyze_resume(
    rubric_id: str = Form(...),
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    as_of: str | None = Form(default=None),
    refresh: bool = Form(default=False),
    profile: str | None = Form(default=None),
    p: Platform = Depends(platform),
) -> Card:
    rubric = _load_rubric(p, rubric_id)
    ensure_profile(p, profile or None)
    try:
        when = date.fromisoformat(as_of) if as_of else date.today()
    except ValueError:
        raise _err(422, "E_BAD_AS_OF", "as_of must be YYYY-MM-DD") from None
    if file is not None and file.filename:
        name = file.filename
        if not any(name.casefold().endswith(ext) for ext in RESUME_EXTS):
            raise _err(400, "E_UNSUPPORTED_FILE", f"unsupported file type; allowed: {sorted(RESUME_EXTS)}")
        limit = int(p.settings.MAX_UPLOAD_MB * 1024 * 1024)
        data = await file.read(limit + 1)
        if len(data) > limit:
            raise _err(400, "E_INPUT_TOO_LARGE", f"upload exceeds {p.settings.MAX_UPLOAD_MB} MB")
        inp = ResumeInput(filename=name, data=data)
    elif text and text.strip():
        if len(text) > p.settings.MAX_INPUT_CHARS:
            raise _err(400, "E_INPUT_TOO_LARGE", f"text exceeds {p.settings.MAX_INPUT_CHARS} characters")
        inp = ResumeInput(text=text)
    else:
        raise _err(422, "E_NO_RESUME", "send a resume file or text")
    options = MatchOptions(profile=profile or None, use_cache=not refresh)
    try:
        return await asyncio.wait_for(analyze(rubric, inp, options, when, _deps(p)),
                                      timeout=p.settings.REQUEST_TIMEOUT_S)
    except IngestError as e:
        raise _err(400, "E_UNREADABLE_FILE", str(e)) from None
    except NotAResume as e:
        raise _err(422, "E_NOT_A_RESUME", str(e)) from None
    except TimeoutError:
        raise _err(504, "E_TIMEOUT", "analysis exceeded REQUEST_TIMEOUT_S") from None
