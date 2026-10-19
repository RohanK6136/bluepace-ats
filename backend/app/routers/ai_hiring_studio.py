"""Protected AI Hiring Studio endpoints using OpenRouter."""
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base, get_db
from app.models import Role, User
from app.security import require_roles

router = APIRouter(prefix="/ai-hiring", tags=["AI Hiring Studio"])
WRITE_ROLES = (Role.admin, Role.recruiter, Role.hiring_manager)
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS_URL = "https://openrouter.ai/api/v1/models"
DEFAULT_MODEL = "openai/gpt-4o-mini"
MAX_TEXT_CHARS = 50000


class AIHiringRun(Base):
    __tablename__ = "ai_hiring_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    task_type: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    model: Mapped[str] = mapped_column(String(200))
    input_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text)
    user_prompt: Mapped[str] = mapped_column(Text)
    output_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_model_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_call_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class OpenRouterRequest(BaseModel):
    api_key: str | None = None
    model: str | None = None


class GenerateJDRequest(OpenRouterRequest):
    source_text: str = Field(min_length=5, max_length=MAX_TEXT_CHARS)
    mode: str = "detailed"
    overrides: dict[str, Any] = Field(default_factory=dict)


class BuildRubricRequest(OpenRouterRequest):
    job_description: str = Field(min_length=10, max_length=MAX_TEXT_CHARS)


class AnalyzeResumeRequest(OpenRouterRequest):
    resume_data: dict[str, Any]
    rubric: dict[str, Any]


def _model_name(value: str | None) -> str:
    name = (value or os.getenv("OPENROUTER_MODEL") or DEFAULT_MODEL).strip()
    if not name or len(name) > 200:
        raise HTTPException(422, "Enter a valid OpenRouter model identifier.")
    return name


def _api_key(value: str | None) -> str:
    return (value or os.getenv("OPENROUTER_API_KEY") or "").strip()


def _provider_error(body: str, code: int) -> str:
    try:
        parsed = json.loads(body)
        message = parsed.get("error", {}).get("message") or parsed.get("message") or ""
    except (ValueError, AttributeError):
        message = ""
    if code == 401:
        return "OpenRouter rejected the API key. Check the key in AI Hiring Studio settings."
    if code == 402:
        return "OpenRouter reports insufficient credits or account balance."
    if code == 403:
        return "OpenRouter denied access to this model. Check model permissions."
    if code == 429:
        return "OpenRouter rate limit reached. Wait briefly or select another model."
    return str(message)[:350] if message else f"OpenRouter request failed with HTTP {code}."


def _call_openrouter(key: str, model: str, system_prompt: str, user_prompt: str, max_tokens: int = 1800):
    if not key:
        raise HTTPException(400, "Add an OpenRouter API key in settings, or configure OPENROUTER_API_KEY on the backend.")
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    count = 0
    for structured in (True, False):
        if not structured:
            payload.pop("response_format", None)
        req = urllib.request.Request(
            CHAT_URL,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
                "HTTP-Referer": os.getenv("PUBLIC_APP_URL", "https://bluepace-frontend-production.up.railway.app"),
                "X-Title": "BluePace ATS AI Hiring Studio",
            },
            method="POST",
        )
        count += 1
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                data = json.loads(response.read().decode("utf-8"))
            choices = data.get("choices") or []
            if not choices:
                raise HTTPException(502, "OpenRouter returned no model response.")
            message = choices[0].get("message") or {}
            content = message.get("content")
            if isinstance(content, list):
                content = "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
            if not isinstance(content, str) or not content.strip():
                raise HTTPException(502, "The selected model returned an empty response.")
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            return {
                "content": content,
                "usage": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens", "cost")},
                "actual_model": str(data.get("model") or model)[:200],
                "call_count": count,
            }
        except urllib.error.HTTPError as error:
            body = error.read(2048).decode("utf-8", errors="replace")
            if structured and error.code == 400 and "response_format" in body.lower():
                continue
            raise HTTPException(502, _provider_error(body, error.code)) from None
        except (urllib.error.URLError, TimeoutError):
            raise HTTPException(504, "OpenRouter is unreachable or timed out. Retry or choose a faster model.") from None
    raise HTTPException(502, "OpenRouter could not return a structured response for this model.")


def _parse_json_output(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fence = chr(96) * 3
    if text.startswith(fence):
        lines = text.splitlines()
        if lines and lines[0].strip().lower() in (fence + "json", fence):
            lines = lines[1:]
        if lines and lines[-1].strip() == fence:
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        result = json.loads(text)
    except ValueError:
        match = re.search(r"\{[\s\S]*\}", text)
        try:
            result = json.loads(match.group(0)) if match else None
        except ValueError:
            result = None
    if not isinstance(result, dict):
        raise HTTPException(502, "The model returned invalid JSON. Retry or choose a model that supports JSON output.")
    return result


def _run_model(request, user: User, db: Session, task_type: str, system_prompt: str, user_prompt: str,
               input_data: dict[str, Any], max_tokens: int = 1800):
    model = _model_name(request.model)
    run = AIHiringRun(
        request_id=str(uuid4()), organization_id=user.organization_id, user_id=user.id,
        task_type=task_type, status="running", model=model, input_data=input_data,
        system_prompt=system_prompt, user_prompt=user_prompt, model_call_count=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    started = perf_counter()
    raw = ""
    usage = None
    calls = 0
    try:
        reply = _call_openrouter(_api_key(request.api_key), model, system_prompt, user_prompt, max_tokens)
        raw, usage, calls = reply["content"], reply["usage"], reply["call_count"]
        result = _parse_json_output(raw)
        run.status = "success"
        run.model = reply["actual_model"]
        run.output_data = result
        run.raw_model_output = raw[:100000]
        run.token_usage = usage
        run.model_call_count = calls
        run.latency_ms = int((perf_counter() - started) * 1000)
        db.commit()
        db.refresh(run)
        return result, run
    except Exception as error:
        run.status = "failed"
        run.raw_model_output = raw[:100000] or None
        run.token_usage = usage
        run.model_call_count = calls
        run.latency_ms = int((perf_counter() - started) * 1000)
        run.error_message = (error.detail if isinstance(error, HTTPException) else str(error))[:1000]
        db.commit()
        if isinstance(error, HTTPException):
            raise
        raise HTTPException(502, "AI request failed. See run history for details.") from None


def _summary(run: AIHiringRun):
    return {
        "request_id": run.request_id, "task_type": run.task_type, "status": run.status,
        "model": run.model, "latency_ms": run.latency_ms, "token_usage": run.token_usage,
        "model_call_count": run.model_call_count, "error_message": run.error_message,
        "created_at": run.created_at.isoformat() if run.created_at else None, "user_id": run.user_id,
    }


def _detail(run: AIHiringRun):
    return {
        **_summary(run), "input_data": run.input_data, "system_prompt": run.system_prompt,
        "user_prompt": run.user_prompt, "output_data": run.output_data, "raw_model_output": run.raw_model_output,
    }


@router.post("/test")
def test_openrouter(request: OpenRouterRequest, user: User = Depends(require_roles(*WRITE_ROLES))):
    key = _api_key(request.api_key)
    if not key:
        raise HTTPException(400, "Add an OpenRouter API key in settings, or configure OPENROUTER_API_KEY on the backend.")
    model = _model_name(request.model)
    req = urllib.request.Request(MODELS_URL, headers={"Authorization": "Bearer " + key}, method="GET")
    started = perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read(2048).decode("utf-8", errors="replace")
        raise HTTPException(502, _provider_error(body, error.code)) from None
    except (urllib.error.URLError, TimeoutError):
        raise HTTPException(504, "OpenRouter connection timed out or is unreachable.") from None
    models = data.get("data") or []
    available = any(item.get("id") == model for item in models if isinstance(item, dict))
    return {
        "status": "connected", "model": model, "model_listed": available,
        "available_model_count": len(models), "latency_ms": int((perf_counter() - started) * 1000),
        "key_source": "browser" if request.api_key else "server environment",
        "message": "OpenRouter API key accepted." + ("" if available else " Check the selected model identifier."),
    }


@router.post("/generate-jd")
def generate_jd(request: GenerateJDRequest, user: User = Depends(require_roles(*WRITE_ROLES)), db: Session = Depends(get_db)):
    source = request.source_text.strip()
    if len(source) < 5:
        raise HTTPException(422, "Paste recruiter notes or upload a job description first.")
    mode = "concise" if request.mode.strip().lower() == "concise" else "detailed"
    system = (
        "You are BluePace ATS's recruiting-content assistant. Return only a JSON object with job_description (string), "
        "details (object: job_title, employment_type, work_mode, location, minimum_experience_years number or null, fresher_allowed boolean), "
        "missing_fields (array of {field, suggested_value, reason}), and notes (array of strings). "
        "Preserve supported facts. Do not invent salary, location, benefits, or company policy. If information is absent, keep the factual detail null and offer a clearly labelled editable suggestion. "
        "Do not add discriminatory or protected-trait requirements. Respect recruiter-approved field overrides. Use clear headings and inclusive job-related language. "
        "Years of experience may be fractional; only mark fresher_allowed true when supported by source or override."
    )
    prompt = json.dumps({
        "task": "Create a polished job description from recruiter notes or an existing JD.",
        "style": mode, "source_text": source[:MAX_TEXT_CHARS], "recruiter_approved_field_overrides": request.overrides,
        "requirements": [
            "Separate essential and desirable criteria where supported.",
            "Concise mode should be compact; detailed mode should be complete and well structured.",
            "Missing field suggestions must include a reason and remain editable, not be stated as facts.",
            "The generated JD is a draft for human review, not automatic publication.",
        ],
    }, ensure_ascii=False)
    result, run = _run_model(request, user, db, "generate_jd", system, prompt,
                             {"source_text": source[:MAX_TEXT_CHARS], "mode": mode, "overrides": request.overrides})
    if not str(result.get("job_description") or "").strip():
        raise HTTPException(502, "Model response did not include a job description. Retry.")
    return {"request_id": run.request_id, "model": run.model, "latency_ms": run.latency_ms,
            "token_usage": run.token_usage, "model_call_count": run.model_call_count, "result": result}


@router.post("/rubric")
def build_rubric(request: BuildRubricRequest, user: User = Depends(require_roles(*WRITE_ROLES)), db: Session = Depends(get_db)):
    jd = request.job_description.strip()
    system = (
        "Design a transparent, job-related assessment rubric. Return JSON with title, rubric_summary, criteria, total_weight. "
        "Each criterion must have name, category, required boolean, weight number, minimum_years number or null, keywords array, description, "
        "and scoring_guide object with missing, partial, strong descriptions. Include role-relevant skills, responsibilities, certifications, "
        "languages only where job-related, must-have vs nice-to-have, and experience years. Support fractional years and freshers when allowed. "
        "Do not infer protected traits or use proxies for them. Non-negative weights must total 100 within rounding; keep the rubric explainable."
    )
    prompt = json.dumps({"task": "Build an assessment rubric for this job description.", "job_description": jd[:MAX_TEXT_CHARS]}, ensure_ascii=False)
    result, run = _run_model(request, user, db, "build_rubric", system, prompt, {"job_description": jd[:MAX_TEXT_CHARS]}, 2200)
    items = result.get("criteria")
    if not isinstance(items, list) or not items:
        raise HTTPException(502, "The model returned no rubric criteria. Retry.")
    clean = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        try:
            weight = max(0.0, min(100.0, float(item.get("weight", 0))))
        except (TypeError, ValueError):
            weight = 0.0
        clean.append({**item, "name": str(item.get("name") or f"Criterion {index + 1}")[:160],
                      "category": str(item.get("category") or "Skill")[:60],
                      "required": bool(item.get("required", False)), "weight": round(weight, 2),
                      "keywords": item.get("keywords") if isinstance(item.get("keywords"), list) else []})
    total = sum(row["weight"] for row in clean)
    if total > 0 and abs(total - 100) > 0.1:
        for row in clean:
            row["weight"] = round(row["weight"] * 100 / total, 2)
        clean[-1]["weight"] = round(100 - sum(row["weight"] for row in clean[:-1]), 2)
    result["criteria"] = clean
    result["total_weight"] = round(sum(row["weight"] for row in clean), 2)
    return {"request_id": run.request_id, "model": run.model, "latency_ms": run.latency_ms,
            "token_usage": run.token_usage, "model_call_count": run.model_call_count, "rubric": result}


@router.post("/analyze-resume")
def analyze_resume(request: AnalyzeResumeRequest, user: User = Depends(require_roles(*WRITE_ROLES)), db: Session = Depends(get_db)):
    if not isinstance(request.rubric.get("criteria"), list) or not request.rubric.get("criteria"):
        raise HTTPException(422, "Build or select an assessment rubric first.")
    system = (
        "You are an evidence-based resume reviewer. Compare only job-related resume evidence to the supplied rubric. Return JSON with "
        "overall_score (0-100), recommendation, summary, strengths array, concerns array, missing_requirements array, and criteria array. "
        "Each criterion result must contain name, score (0-100), weight, weighted_score, assessment, evidence (array of short excerpts or labelled fields), and gap. "
        "Do not assume absent details mean the candidate lacks the skill: mark Not evidenced. Never fabricate quotations or qualifications. "
        "Do not score age, sex, gender, race, religion, disability, nationality, family status, photograph, name, or other protected traits. "
        "This is decision support, not an automated hiring decision. Clearly identify when human review is needed."
    )
    prompt = json.dumps({
        "task": "Assess this structured resume against every rubric criterion.",
        "rubric": request.rubric, "resume_evidence": request.resume_data,
        "requirements": [
            "Score every criterion from 0 to 100.",
            "weighted_score = score * weight / 100; overall_score is the sum when rubric weights total 100.",
            "Use supplied resume evidence only; separate missing evidence from confirmed mismatch.",
        ],
    }, ensure_ascii=False, default=str)
    result, run = _run_model(request, user, db, "analyze_resume", system, prompt,
                             {"resume_data": request.resume_data, "rubric": request.rubric}, 2400)
    if not isinstance(result.get("criteria"), list):
        raise HTTPException(502, "The model did not return criterion-level scores. Retry.")
    result["decision_support_only"] = True
    return {"request_id": run.request_id, "model": run.model, "latency_ms": run.latency_ms,
            "token_usage": run.token_usage, "model_call_count": run.model_call_count, "analysis": result}


@router.get("/history")
def list_history(limit: int = Query(default=30, ge=1, le=100),
                 user: User = Depends(require_roles(*WRITE_ROLES)), db: Session = Depends(get_db)):
    runs = db.scalars(select(AIHiringRun).where(AIHiringRun.organization_id == user.organization_id)
                      .order_by(AIHiringRun.created_at.desc()).limit(limit)).all()
    return {"runs": [_summary(run) for run in runs]}


@router.get("/history/{request_id}")
def get_history_detail(request_id: str, user: User = Depends(require_roles(*WRITE_ROLES)),
                       db: Session = Depends(get_db)):
    run = db.scalar(select(AIHiringRun).where(AIHiringRun.request_id == request_id,
                                              AIHiringRun.organization_id == user.organization_id))
    if run is None:
        raise HTTPException(404, "AI run not found.")
    return _detail(run)
