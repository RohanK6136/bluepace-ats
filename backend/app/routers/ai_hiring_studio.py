"""Protected AI Hiring Studio endpoints with multiple AI providers."""
import hashlib
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
from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.api.deps import Platform, platform, require_api_key
from app.core.logging import api_key_id
from app.database import Base, get_db
from app.models import Application, ApplicationMatchAssessment, ApplicantMatchRubricLink, Candidate, Job, Role, User
from app.security import require_roles
from app.services.ai_providers import (
    call_ai_provider as _call_ai_provider,
    model_name as _provider_model_name,
    provider_has_server_key as _provider_has_server_key,
    provider_label as _provider_label,
    provider_name as _normalize_provider_name,
    resolve_api_key as _resolve_provider_api_key,
)

router = APIRouter(prefix="/ai-hiring", tags=["AI Hiring Studio"])
WRITE_ROLES = (Role.admin, Role.recruiter, Role.hiring_manager)
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS_URL = "https://openrouter.ai/api/v1/models"
DEFAULT_MODEL = "google/gemini-2.5-flash"
MAX_TEXT_CHARS = 50000

_SENSITIVE_RESUME_KEYS = frozenset({
    "name", "fullname", "firstname", "middlename", "lastname", "givenname", "familyname",
    "candidatename", "displayname", "email", "emailaddress", "personalemail", "phone",
    "phonenumber", "mobile", "mobilenumber", "contactnumber", "address", "homeaddress",
    "streetaddress", "postaladdress", "postcode", "zipcode", "postalcode", "dateofbirth",
    "dob", "birthdate", "age", "ageyears", "gender", "sex", "nationality", "citizenship",
    "nationalorigin", "race", "ethnicity", "religion", "disability", "maritalstatus",
    "familystatus", "photograph", "photo", "profilepicture", "headshot", "personaldetails",
    "contactdetails", "contactinformation", "personalinfo", "personalinformation",
    "currentlocation", "homelocation",
})
_RESUME_NAME_KEYS = frozenset({
    "name", "fullname", "firstname", "middlename", "lastname", "givenname", "familyname",
    "candidatename", "displayname",
})
_RESUME_PRIVATE_CONTAINERS = frozenset({
    "personaldetails", "personalinformation", "contactdetails", "contactinformation",
    "personalinfo", "candidate", "candidateprofile", "profile", "person", "personal", "contact",
})


def _resume_key_token(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).casefold())


def _redact_resume_pii(resume_data: dict[str, Any]) -> dict[str, Any]:
    """Return a model-safe copy with common identifying resume fields redacted.

    The original request object is not modified. Free-text contact lines and known
    candidate-name values are removed as well as structured personal-data fields.
    This is data minimisation, not a guarantee that arbitrary prose is anonymous.
    """
    if not isinstance(resume_data, dict):
        raise HTTPException(422, "Resume data must be a structured object.")

    candidate_names: list[str] = []

    def collect_names(value: Any, depth: int = 0) -> None:
        if not isinstance(value, dict) or depth > 4:
            return
        for key, item in value.items():
            token = _resume_key_token(key)
            if token in _RESUME_NAME_KEYS and isinstance(item, str):
                cleaned_name = item.strip()
                if len(cleaned_name) >= 2:
                    candidate_names.append(cleaned_name)
            elif token in _RESUME_PRIVATE_CONTAINERS:
                collect_names(item, depth + 1)

    collect_names(resume_data)

    private_line = re.compile(
        r"(?im)^\s*(?:full\s+name|candidate\s+name|name|email(?:\s+address)?|"
        r"phone(?:\s+number)?|mobile|contact\s+number|address|date\s+of\s+birth|"
        r"birthdate|dob|age|gender|sex|nationality|citizenship|national\s+origin|"
        r"race|ethnicity|religion|marital\s+status|current\s+location)\s*[:\-]\s*.*$"
    )
    email_pattern = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
    phone_pattern = re.compile(r"(?<!\w)(?=(?:\D*\d){10,})\+?\d[\d\s().-]{7,}\d(?!\w)")

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: clean(item)
                for key, item in value.items()
                if _resume_key_token(key) not in _SENSITIVE_RESUME_KEYS
            }
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, tuple):
            return [clean(item) for item in value]
        if not isinstance(value, str):
            return value

        text = email_pattern.sub("[REDACTED_EMAIL]", value)
        text = phone_pattern.sub("[REDACTED_PHONE]", text)
        text = private_line.sub("[REDACTED_PERSONAL_DETAIL]", text)
        for name in sorted(set(candidate_names), key=len, reverse=True):
            text = re.sub(
                r"(?<!\w)" + re.escape(name) + r"(?!\w)",
                "[REDACTED_NAME]",
                text,
                flags=re.IGNORECASE,
            )
        return text

    return clean(resume_data)



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


class AIHiringRubric(Base):
    """An organisation-scoped, versionable rubric that recruiters can reuse."""
    __tablename__ = "ai_hiring_rubrics"
    __table_args__ = (Index("uq_ai_hiring_rubrics_family_version", "family_id", "version", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rubric_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    job_title: Mapped[str] = mapped_column(String(200), default="")
    rubric_data: Mapped[dict] = mapped_column(JSON)
    family_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class AIHiringWorkspace(Base):
    """Recruiter-created JD match workspaces shared within an organization."""
    __tablename__ = "ai_hiring_workspaces"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_data: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class OpenRouterRequest(BaseModel):
    provider: str = Field(default_factory=lambda: os.getenv("AI_PROVIDER", "openrouter"), max_length=40)
    api_key: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)
    base_url: str | None = Field(default=None, max_length=512)
    account_id: str | None = Field(default=None, max_length=128)


class GenerateJDRequest(OpenRouterRequest):
    source_text: str = Field(min_length=5, max_length=MAX_TEXT_CHARS)
    mode: str = "detailed"
    overrides: dict[str, Any] = Field(default_factory=dict)


class BuildRubricRequest(OpenRouterRequest):
    job_description: str = Field(min_length=10, max_length=MAX_TEXT_CHARS)


class SavedRubricRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    job_title: str = Field(default="", max_length=200)
    rubric: dict[str, Any]


class SavedWorkspaceRequest(BaseModel):
    workspace: dict[str, Any]


class AnalyzeResumeRequest(OpenRouterRequest):
    resume_data: dict[str, Any]
    # Server loads this saved snapshot; client-supplied rubric JSON is not authoritative.
    rubric_id: str | None = None
    rubric: dict[str, Any] = Field(default_factory=dict)


def _provider_name(value: str | None = None) -> str:
    try:
        return _normalize_provider_name(value)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


def _model_name(value: str | None, provider: str = "openrouter") -> str:
    return _provider_model_name(value, _provider_name(provider))


def _api_key(value: str | None, provider: str = "openrouter") -> str:
    return _resolve_provider_api_key(value, _provider_name(provider))


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
                "HTTP-Referer": os.getenv("PUBLIC_APP_URL", "https://bluepace-ats-frontend.vercel.app"),
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
               input_data: dict[str, Any], max_tokens: int = 1800, persist_prompt_content: bool = True,
               privacy_metadata: dict[str, Any] | None = None):
    provider = _provider_name(getattr(request, "provider", "openrouter"))
    model = _model_name(request.model, provider)
    # Resume assessment runs keep metrics/status only: candidate content, prompts,
    # and model-generated evidence are returned to the caller but not retained.
    stored_input_data = input_data if persist_prompt_content else {
        "privacy_mode": "ephemeral_assessment", **(privacy_metadata or {})
    }
    stored_system_prompt = system_prompt if persist_prompt_content else "[not stored: ephemeral assessment]"
    stored_user_prompt = user_prompt if persist_prompt_content else "[not stored: ephemeral assessment]"
    run = AIHiringRun(
        request_id=str(uuid4()), organization_id=user.organization_id, user_id=user.id,
        task_type=task_type, status="running", model=model, input_data=stored_input_data,
        system_prompt=stored_system_prompt, user_prompt=stored_user_prompt, model_call_count=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    started = perf_counter()
    raw = ""
    usage = None
    calls = 0
    try:
        if provider == "openrouter":
            reply = _call_openrouter(_api_key(request.api_key, provider), model, system_prompt, user_prompt, max_tokens)
        else:
            reply = _call_ai_provider(
                provider=provider, api_key_value=_api_key(request.api_key, provider),
                model=model, system_prompt=system_prompt, user_prompt=user_prompt,
                max_tokens=max_tokens, base_url=getattr(request, "base_url", None),
                account_id=getattr(request, "account_id", None), json_mode=True,
            )
        raw, usage, calls = reply["content"], reply["usage"], reply["call_count"]
        result = _parse_json_output(raw)
        run.status = "success"
        run.model = reply["actual_model"]
        run.output_data = result if persist_prompt_content else None
        run.raw_model_output = raw[:100000] if persist_prompt_content else None
        run.token_usage = usage
        run.model_call_count = calls
        run.latency_ms = int((perf_counter() - started) * 1000)
        db.commit()
        db.refresh(run)
        return result, run
    except Exception as error:
        run.status = "failed"
        run.raw_model_output = (raw[:100000] or None) if persist_prompt_content else None
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


def _normalize_rubric_result(result: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize rubric weights before returning a rubric to recruiters."""
    items = result.get("criteria")
    if not isinstance(items, list) or not items:
        raise ValueError("The model returned no rubric criteria. Retry.")

    clean = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        try:
            weight = float(item.get("weight", 0))
        except (TypeError, ValueError):
            weight = 0.0
        if not (weight >= 0):
            weight = 0.0
        weight = max(0.0, min(100.0, weight))
        clean.append({
            **item,
            "name": str(item.get("name") or f"Criterion {index + 1}")[:160],
            "category": str(item.get("category") or "Skill")[:60],
            "required": bool(item.get("required", False)),
            "weight": round(weight, 2),
            "keywords": item.get("keywords") if isinstance(item.get("keywords"), list) else [],
        })

    if not clean:
        raise ValueError("The model returned no usable rubric criteria. Retry.")

    total = sum(row["weight"] for row in clean)
    if total <= 0:
        raise ValueError("The model returned rubric criteria with no positive weights. Retry.")

    if abs(total - 100) > 0.1:
        for row in clean:
            row["weight"] = round(row["weight"] * 100 / total, 2)
        clean[-1]["weight"] = round(100 - sum(row["weight"] for row in clean[:-1]), 2)

    result["criteria"] = clean
    result["total_weight"] = round(sum(row["weight"] for row in clean), 2)
    return result


def _mark_run_failed(db: Session, run: AIHiringRun, message: str) -> None:
    """Keep run history consistent when a model response violates its task contract."""
    run.status = "failed"
    run.error_message = message[:1000]
    db.commit()
    raise HTTPException(502, message)


def _rubric_content_hash(title: str, job_title: str, rubric_data: dict[str, Any]) -> str:
    """Hash the canonical title, job title, and normalized rubric snapshot."""
    payload = {
        "title": str(title or "").strip(),
        "job_title": str(job_title or "").strip(),
        "rubric": rubric_data,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _saved_rubric_payload(row: AIHiringRubric) -> dict[str, Any]:
    return {
        "rubric_id": row.rubric_id,
        "family_id": row.family_id or row.rubric_id,
        "version": int(row.version or 1),
        "content_hash": row.content_hash or _rubric_content_hash(row.title, row.job_title, row.rubric_data),
        "title": row.title,
        "job_title": row.job_title,
        "rubric": row.rubric_data,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "updated_by": row.user_id,
    }


def _prepare_saved_rubric(request: SavedRubricRequest) -> dict[str, Any]:
    title = request.title.strip()
    if not title:
        raise HTTPException(422, "Enter a name for this assessment rubric.")
    rubric = dict(request.rubric)
    try:
        rubric = _normalize_rubric_result(rubric)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    if len(rubric["criteria"]) > 100:
        raise HTTPException(422, "An assessment rubric cannot contain more than 100 criteria.")
    rubric["title"] = title
    return rubric


def _configuration_status(provider_value: str | None = None) -> dict[str, Any]:
    """Report safe AI configuration metadata without disclosing credentials."""
    provider = _provider_name(provider_value)
    configured = _provider_has_server_key(provider)
    return {
        "provider": provider,
        "provider_label": _provider_label(provider),
        "server_key_configured": configured,
        "requires_api_key": provider != "ollama",
        "account_id_configured": bool(os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()) if provider == "cloudflare" else None,
        "default_model": _model_name(None, provider),
        "key_source": "local endpoint (no API key required)" if provider == "ollama" else ("server environment" if configured else "not configured"),
    }


@router.get("/status")
def get_ai_configuration_status(
    provider: str | None = Query(default=None, max_length=40),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    return _configuration_status(provider)


@router.post("/test")
def test_provider_connection(request: OpenRouterRequest, user: User = Depends(require_roles(*WRITE_ROLES))):
    provider = _provider_name(request.provider)
    model = _model_name(request.model, provider)
    key = _api_key(request.api_key, provider)
    started = perf_counter()
    if provider == "openrouter":
        if not key:
            raise HTTPException(400, "Add an OpenRouter API key in settings, or configure OPENROUTER_API_KEY on the backend.")
        req = urllib.request.Request(MODELS_URL, headers={"Authorization": "Bearer " + key}, method="GET")
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
        if not available:
            raise HTTPException(
                422,
                "OpenRouter accepted the API key, but the selected model is not listed for this account. "
                "Check the model identifier and model access, then retry.",
            )

        # A models-list response only validates the key. Run a tiny completion as well so
        # the UI's connection check proves the chosen model can actually generate output.
        smoke_result = _call_openrouter(
            key,
            model,
            'You are validating the BluePace AI provider connection. Return only JSON: {"status":"ok"}.',
            'Return exactly this JSON object: {"status":"ok"}.',
            max_tokens=16,
        )
        return {
            "status": "connected", "provider": provider, "provider_label": _provider_label(provider),
            "model": model, "model_listed": True, "completion_verified": True,
            "available_model_count": len(models), "usage": smoke_result.get("usage", {}),
            "latency_ms": int((perf_counter() - started) * 1000),
            "key_source": "browser" if request.api_key else "server environment",
            "message": "OpenRouter key accepted; the selected model is listed and completed a test inference.",
        }
    _call_ai_provider(
        provider=provider, api_key_value=key, model=model,
        system_prompt="Answer briefly with the single word OK.",
        user_prompt="Reply with OK.", max_tokens=8,
        base_url=request.base_url, account_id=request.account_id, json_mode=False,
    )
    return {
        "status": "connected", "provider": provider, "provider_label": _provider_label(provider),
        "model": model, "model_listed": True, "available_model_count": None,
        "latency_ms": int((perf_counter() - started) * 1000),
        "key_source": "browser" if request.api_key else ("server environment" if _provider_has_server_key(provider) else "local endpoint"),
        "message": _provider_label(provider) + " responded successfully. Connection testing sends a short test prompt.",
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
        _mark_run_failed(db, run, "Model response did not include a job description. Retry.")
    return {"request_id": run.request_id, "model": run.model, "latency_ms": run.latency_ms,
            "token_usage": run.token_usage, "model_call_count": run.model_call_count, "result": result}


@router.post("/rubric")
def build_rubric(request: BuildRubricRequest, user: User = Depends(require_roles(*WRITE_ROLES)), db: Session = Depends(get_db)):
    jd = request.job_description.strip()
    system = (
        "Design a transparent, job-related assessment rubric. Return JSON with title, rubric_summary, minimum_years_overall number or null, "
        "education_minimum string or null, equivalent_experience_accepted boolean, criteria, and total_weight. "
        "Each criterion must have name, category, required boolean, weight number, minimum_years number or null, keywords array, description, "
        "and scoring_guide object with missing, partial, strong descriptions. Include role-relevant skills, responsibilities, certifications, "
        "languages only where job-related, must-have vs nice-to-have, and experience years. Support fractional years and freshers when allowed. "
        "Do not infer protected traits or use proxies for them. Non-negative weights must total 100 within rounding; keep the rubric explainable."
    )
    prompt = json.dumps({"task": "Build an assessment rubric for this job description.", "job_description": jd[:MAX_TEXT_CHARS]}, ensure_ascii=False)
    result, run = _run_model(request, user, db, "build_rubric", system, prompt, {"job_description": jd[:MAX_TEXT_CHARS]}, 2200)
    try:
        result = _normalize_rubric_result(result)
    except ValueError as error:
        _mark_run_failed(db, run, str(error))
    return {"request_id": run.request_id, "model": run.model, "latency_ms": run.latency_ms,
            "token_usage": run.token_usage, "model_call_count": run.model_call_count, "rubric": result}


@router.post("/analyze-resume")
def analyze_resume(request: AnalyzeResumeRequest, user: User = Depends(require_roles(*WRITE_ROLES)), db: Session = Depends(get_db)):
    if not request.rubric_id:
        raise HTTPException(422, "Select a saved rubric version before assessing resumes.")

    # The saved server-side snapshot is authoritative, never mutable browser JSON.
    rubric_row = db.scalar(
        select(AIHiringRubric).where(
            AIHiringRubric.rubric_id == request.rubric_id,
            AIHiringRubric.organization_id == user.organization_id,
        )
    )
    if rubric_row is None:
        raise HTTPException(404, "Saved assessment rubric version not found in this organisation.")
    assessment_rubric = rubric_row.rubric_data or {}
    if not isinstance(assessment_rubric.get("criteria"), list) or not assessment_rubric.get("criteria"):
        raise HTTPException(422, "The selected saved rubric has no usable criteria.")

    safe_resume_data = _redact_resume_pii(request.resume_data)
    system = (
        "You are an evidence-based resume reviewer. Compare only job-related resume evidence to the supplied rubric. Return JSON with "
        "overall_score (0-100), recommendation, summary, strengths array, concerns array, missing_requirements array, and criteria array. "
        "Each criterion result must contain name, score (0-100), weight, weighted_score, assessment, evidence (array of short excerpts or labelled fields), and gap. "
        "Do not assume absent details mean the candidate lacks the skill: mark Not evidenced. Never fabricate quotations or qualifications. "
        "Personal identifiers have been filtered from the provided resume data. Do not infer or score protected traits including age, sex, gender, "
        "race, religion, disability, nationality, family status, photograph, name, or other protected traits. "
        "This is decision support, not an automated hiring decision. Clearly identify when human review is needed."
    )
    prompt = json.dumps({
        "task": "Assess this redacted structured resume against the selected immutable saved rubric snapshot.",
        "rubric": assessment_rubric, "resume_evidence": safe_resume_data,
        "requirements": [
            "Score every criterion from 0 to 100.",
            "weighted_score = score * weight / 100; overall_score is the sum when rubric weights total 100.",
            "Use supplied resume evidence only; separate missing evidence from confirmed mismatch.",
            "Do not modify the supplied rubric or its criterion weights.",
        ],
    }, ensure_ascii=False, default=str)
    version_metadata = {
        "rubric_id": rubric_row.rubric_id,
        "rubric_family_id": rubric_row.family_id or rubric_row.rubric_id,
        "rubric_version": int(rubric_row.version or 1),
        "rubric_hash": rubric_row.content_hash or _rubric_content_hash(
            rubric_row.title, rubric_row.job_title, assessment_rubric
        ),
    }
    result, run = _run_model(
        request, user, db, "analyze_resume", system, prompt,
        {"resume_data": safe_resume_data, "rubric": assessment_rubric},
        2400, persist_prompt_content=False, privacy_metadata=version_metadata,
    )
    if not isinstance(result.get("criteria"), list) or not result.get("criteria"):
        _mark_run_failed(db, run, "The model did not return criterion-level scores. Retry.")
    result["decision_support_only"] = True
    return {
        "request_id": run.request_id, "model": run.model, "latency_ms": run.latency_ms,
        "token_usage": run.token_usage, "model_call_count": run.model_call_count,
        "rubric_id": version_metadata["rubric_id"],
        "rubric_family_id": version_metadata["rubric_family_id"],
        "rubric_version": version_metadata["rubric_version"],
        "rubric_hash": version_metadata["rubric_hash"],
        "analysis": result,
    }

@router.get("/rubrics")
def list_saved_rubrics(
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    """List saved rubrics for the signed-in organisation only."""
    rows = db.scalars(
        select(AIHiringRubric)
        .where(AIHiringRubric.organization_id == user.organization_id)
        .order_by(AIHiringRubric.updated_at.desc())
        .limit(100)
    ).all()
    return {"rubrics": [_saved_rubric_payload(row) for row in rows]}


@router.post("/rubrics")
def create_saved_rubric(
    request: SavedRubricRequest,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    rubric = _prepare_saved_rubric(request)
    now = datetime.now(timezone.utc)
    rubric_id = str(uuid4())
    job_title = request.job_title.strip()[:200]
    row = AIHiringRubric(
        rubric_id=rubric_id,
        organization_id=user.organization_id,
        user_id=user.id,
        title=request.title.strip(),
        job_title=job_title,
        rubric_data=rubric,
        family_id=rubric_id,
        version=1,
        content_hash=_rubric_content_hash(request.title.strip(), job_title, rubric),
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _saved_rubric_payload(row)


@router.get("/rubrics/{rubric_id}")
def get_saved_rubric(
    rubric_id: str,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    row = db.scalar(
        select(AIHiringRubric).where(
            AIHiringRubric.rubric_id == rubric_id,
            AIHiringRubric.organization_id == user.organization_id,
        )
    )
    if row is None:
        raise HTTPException(404, "Saved assessment rubric not found.")
    return _saved_rubric_payload(row)


@router.put("/rubrics/{rubric_id}")
def update_saved_rubric(
    rubric_id: str,
    request: SavedRubricRequest,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    """Create an immutable next version within the selected rubric family."""
    previous = db.scalar(
        select(AIHiringRubric).where(
            AIHiringRubric.rubric_id == rubric_id,
            AIHiringRubric.organization_id == user.organization_id,
        )
    )
    if previous is None:
        raise HTTPException(404, "Saved assessment rubric not found.")

    rubric = _prepare_saved_rubric(request)
    family_id = previous.family_id or previous.rubric_id
    latest_version = db.scalar(
        select(func.max(AIHiringRubric.version)).where(
            AIHiringRubric.organization_id == user.organization_id,
            AIHiringRubric.family_id == family_id,
        )
    )
    version = max(int(latest_version or 0), int(previous.version or 1)) + 1
    now = datetime.now(timezone.utc)
    job_title = request.job_title.strip()[:200]
    new_row = AIHiringRubric(
        rubric_id=str(uuid4()),
        organization_id=user.organization_id,
        user_id=user.id,
        title=request.title.strip(),
        job_title=job_title,
        rubric_data=rubric,
        family_id=family_id,
        version=version,
        content_hash=_rubric_content_hash(request.title.strip(), job_title, rubric),
        created_at=now,
        updated_at=now,
    )
    db.add(new_row)
    db.commit()
    db.refresh(new_row)
    return _saved_rubric_payload(new_row)

@router.delete("/rubrics/{rubric_id}")
def delete_saved_rubric(
    rubric_id: str,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    row = db.scalar(
        select(AIHiringRubric).where(
            AIHiringRubric.rubric_id == rubric_id,
            AIHiringRubric.organization_id == user.organization_id,
        )
    )
    if row is None:
        raise HTTPException(404, "Saved assessment rubric not found.")
    raise HTTPException(
        409,
        "Saved rubric versions are retained for assessment auditability. Create a new version instead of deleting a saved snapshot.",
    )


@router.get("/workspaces")
def list_saved_workspaces(
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(AIHiringWorkspace)
        .where(AIHiringWorkspace.organization_id == user.organization_id)
        .order_by(AIHiringWorkspace.updated_at.desc())
        .limit(100)
    ).all()
    return {"workspaces": [row.workspace_data for row in rows]}


@router.put("/workspaces/{workspace_id}")
def save_workspace_to_team(
    workspace_id: str,
    request: SavedWorkspaceRequest,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    workspace = request.workspace
    if workspace.get("id") != workspace_id:
        raise HTTPException(422, "Workspace ID does not match the request path.")
    if len(json.dumps(workspace, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 2_000_000:
        raise HTTPException(413, "Workspace is too large to sync (2 MB maximum).")
    title = str(workspace.get("title") or "Untitled workspace").strip()[:120]
    if not title:
        title = "Untitled workspace"
    workspace["title"] = title
    now = datetime.now(timezone.utc)
    row = db.get(AIHiringWorkspace, workspace_id)
    if row is not None and row.organization_id != user.organization_id:
        raise HTTPException(404, "Workspace not found in this organization.")
    if row is None:
        row = AIHiringWorkspace(
            id=workspace_id,
            organization_id=user.organization_id,
            user_id=user.id,
            workspace_data=workspace,
            updated_at=now,
        )
        db.add(row)
    else:
        row.workspace_data = workspace
        row.updated_at = now
    db.commit()
    return {"workspace": workspace, "updated_at": now.isoformat()}


@router.delete("/workspaces/{workspace_id}")
def delete_team_workspace(
    workspace_id: str,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    row = db.scalar(select(AIHiringWorkspace).where(
        AIHiringWorkspace.id == workspace_id,
        AIHiringWorkspace.organization_id == user.organization_id,
    ))
    if row is None:
        raise HTTPException(404, "Workspace not found in this organization.")
    db.delete(row)
    db.commit()
    return {"deleted": True}

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

class LinkApplicantMatchRubricRequest(BaseModel):
    rubric_id: str = Field(min_length=1, max_length=100)


class SaveApplicantMatchAssessmentRequest(BaseModel):
    application_id: int = Field(gt=0)
    job_id: int = Field(gt=0)
    request_id: str = Field(min_length=1, max_length=100)


def _applicant_match_rubric_link_payload(row: ApplicantMatchRubricLink) -> dict[str, Any]:
    return {
        "id": row.id,
        "job_id": row.job_id,
        "rubric_id": row.rubric_id,
        "rubric_hash": row.rubric_hash,
        "rubric_title": row.rubric_title,
        "rubric_items": row.rubric_items,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _verified_saved_feature_rubric(p: Platform, rubric_id: str) -> dict[str, Any]:
    row = p.store.get_rubric(rubric_id)
    if not row:
        raise HTTPException(404, "Saved Applicant Match rubric not found.")
    owner_key_id = row.get("created_by")
    current_key_id = api_key_id.get()
    if owner_key_id != current_key_id:
        raise HTTPException(404, "Saved Applicant Match rubric not found for this API key.")
    try:
        rubric_data = json.loads(row.get("rubric_json") or "")
    except (TypeError, ValueError):
        raise HTTPException(409, "The saved rubric could not be verified. Save the rubric again.") from None
    if not isinstance(rubric_data, dict):
        raise HTTPException(409, "The saved rubric could not be verified. Save the rubric again.")
    if rubric_data.get("rubric_id") != rubric_id or rubric_data.get("rubric_hash") != row.get("hash"):
        raise HTTPException(409, "The saved rubric metadata does not match its stored snapshot.")
    return row


@router.post("/jobs/{job_id}/applicant-match-rubrics", status_code=201)
def link_applicant_match_rubric(
    job_id: int,
    request: LinkApplicantMatchRubricRequest,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
    p: Platform = Depends(platform),
    _api_key_check: None = Depends(require_api_key),
):
    """Link an immutable saved rubric version to an ATS job inside the authenticated organisation."""
    job = db.scalar(select(Job).where(Job.id == job_id, Job.organization_id == user.organization_id))
    if job is None:
        raise HTTPException(404, "Job not found in this organisation.")
    saved = _verified_saved_feature_rubric(p, request.rubric_id.strip())
    row = db.scalar(select(ApplicantMatchRubricLink).where(
        ApplicantMatchRubricLink.organization_id == user.organization_id,
        ApplicantMatchRubricLink.job_id == job.id,
        ApplicantMatchRubricLink.rubric_id == saved["id"],
    ))
    if row is not None:
        if row.rubric_hash != saved["hash"]:
            raise HTTPException(409, "The saved rubric version hash changed. Review the saved rubric before relinking.")
        return _applicant_match_rubric_link_payload(row)
    linked = ApplicantMatchRubricLink(
        organization_id=user.organization_id,
        job_id=job.id,
        created_by_id=user.id,
        rubric_id=saved["id"],
        rubric_hash=saved["hash"],
        rubric_title=str(saved.get("title") or "")[:200],
        rubric_items=int(saved.get("items") or 0),
    )
    db.add(linked)
    db.commit()
    db.refresh(linked)
    return _applicant_match_rubric_link_payload(linked)


@router.get("/jobs/{job_id}/applicant-match-rubrics")
def list_applicant_match_rubric_links(
    job_id: int,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    job = db.scalar(select(Job).where(Job.id == job_id, Job.organization_id == user.organization_id))
    if job is None:
        raise HTTPException(404, "Job not found in this organisation.")
    rows = db.scalars(
        select(ApplicantMatchRubricLink).where(
            ApplicantMatchRubricLink.organization_id == user.organization_id,
            ApplicantMatchRubricLink.job_id == job.id,
        ).order_by(ApplicantMatchRubricLink.created_at.desc()).limit(50)
    ).all()
    return [_applicant_match_rubric_link_payload(row) for row in rows]


def _bounded_integer(value: Any, minimum: int = 0, maximum: int = 100) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    number = int(value)
    return number if minimum <= number <= maximum else None


def _bounded_years(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value) if 0 <= value <= 80 else None


def _safe_applicant_match_assessment(source: dict[str, Any]) -> dict[str, Any]:
    """Persist scores/statuses only; never retain resume excerpts, profile data, or generated narrative."""
    scores = source.get("scores") if isinstance(source.get("scores"), dict) else {}

    def count_score(value: Any) -> dict[str, int | None] | None:
        if not isinstance(value, dict):
            return None
        return {
            key: _bounded_integer(value.get(key), 0, 100 if key == "pct" else 100000)
            for key in ("pct", "met", "partial", "total")
        }

    experience = scores.get("experience") if isinstance(scores.get("experience"), dict) else {}
    education = scores.get("education") if isinstance(scores.get("education"), dict) else {}
    safe_groups = []
    for group in (scores.get("groups") if isinstance(scores.get("groups"), list) else []):
        if not isinstance(group, dict):
            continue
        label = str(group.get("label") or group.get("name") or "").strip()[:120]
        if not label:
            continue
        safe_groups.append({
            "label": label,
            "pct": _bounded_integer(group.get("pct")),
            "met": _bounded_integer(group.get("met"), 0, 100000),
            "partial": _bounded_integer(group.get("partial"), 0, 100000),
            "total": _bounded_integer(group.get("total"), 0, 100000),
        })
        if len(safe_groups) >= 20:
            break

    safe_evidence = []
    for item in (source.get("evidence") if isinstance(source.get("evidence"), list) else []):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()[:120]
        state = str(item.get("status") or "")
        if label and state in {"met", "partial", "unclear", "not_evidenced"}:
            safe_evidence.append({
                "label": label,
                "status": state,
                "importance": item.get("importance") if item.get("importance") in {"must", "nice"} else None,
                "group": str(item.get("group") or "")[:40],
            })
        if len(safe_evidence) >= 100:
            break

    safe_gaps = []
    for item in (source.get("gaps") if isinstance(source.get("gaps"), list) else []):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()[:120]
        state = str(item.get("status") or "")
        if label and state in {"met", "partial", "unclear", "not_evidenced"}:
            safe_gaps.append({
                "label": label,
                "status": state,
                "importance": item.get("importance") if item.get("importance") in {"must", "nice"} else None,
            })
        if len(safe_gaps) >= 100:
            break

    raw_flags = source.get("flags") if isinstance(source.get("flags"), list) else []
    flags = [
        str(flag).strip()[:120]
        for flag in raw_flags[:20]
        if isinstance(flag, str) and flag.strip()
    ]
    return {
        "status": "manual" if source.get("status") == "manual" else "complete",
        "match_score": _bounded_integer(scores.get("match")),
        "scores": {
            "required_skills": count_score(scores.get("required_skills")),
            "preferred_skills": count_score(scores.get("preferred_skills")),
            "experience": {
                "pct": _bounded_integer(experience.get("pct")),
                "relevant_years": _bounded_years(experience.get("relevant_years")),
                "total_years": _bounded_years(experience.get("total_years")),
                "required_years": _bounded_years(experience.get("required_years")),
            },
            "education": {
                "pct": _bounded_integer(education.get("pct")),
                "level": str(education.get("level") or "")[:30] or None,
                "required": str(education.get("required") or "")[:30] or None,
            },
            "groups": safe_groups,
        },
        "evidence": safe_evidence,
        "gaps": safe_gaps,
        "flags": flags,
        "decision_support_only": True,
    }


def _verified_applicant_match_result(p: Platform, request_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the immutable feature-run result from server storage; never trust scores echoed by a browser."""
    row = p.store.get_run(request_id)
    if not row or row.get("feature") != "applicant_match" or row.get("operation") != "analyze":
        raise HTTPException(404, "Applicant Match run not found. Run the assessment again before saving.")
    saved_api_key_id = row.get("api_key_id")
    current_api_key_id = api_key_id.get()
    if saved_api_key_id != current_api_key_id:
        raise HTTPException(404, "Applicant Match run not found. Run the assessment again with the configured API key.")
    if row.get("outcome") not in {"success", "degraded"}:
        raise HTTPException(409, "This Applicant Match run did not produce a savable assessment.")
    raw_result = row.get("result_json")
    if not raw_result:
        raise HTTPException(409, "This run has no retained result payload, so its score cannot be verified for ATS linking.")
    try:
        result = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
    except (TypeError, ValueError):
        raise HTTPException(409, "The recorded Applicant Match result could not be verified. Run the assessment again.") from None
    if not isinstance(result, dict) or result.get("request_id") != request_id:
        raise HTTPException(409, "The recorded Applicant Match result could not be verified. Run the assessment again.")
    rubric = result.get("rubric")
    if not isinstance(rubric, dict) or not str(rubric.get("id") or "").strip():
        raise HTTPException(409, "The recorded assessment has no saved rubric reference.")
    return result, rubric


def _applicant_match_assessment_payload(row: ApplicationMatchAssessment) -> dict[str, Any]:
    return {
        "id": row.id,
        "application_id": row.application_id,
        "job_id": row.job_id,
        "candidate_id": row.candidate_id,
        "request_id": row.request_id,
        "rubric_id": row.rubric_id,
        "rubric_hash": row.rubric_hash,
        "rubric_title": row.rubric_title,
        "status": row.status,
        "match_score": row.match_score,
        "assessment_data": row.assessment_data or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.post("/applicant-match/assessments", status_code=201)
def save_applicant_match_assessment(
    request: SaveApplicantMatchAssessmentRequest,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
    p: Platform = Depends(platform),
    _api_key_check: None = Depends(require_api_key),
):
    """Attach a verified, privacy-minimised run to an application in the authenticated organisation."""
    application = db.scalar(select(Application).where(
        Application.id == request.application_id,
        Application.organization_id == user.organization_id,
    ))
    job = db.scalar(select(Job).where(
        Job.id == request.job_id,
        Job.organization_id == user.organization_id,
    ))
    if application is None or job is None:
        raise HTTPException(404, "ATS job or application not found in this organisation.")
    if application.job_id != job.id:
        raise HTTPException(409, "The selected application does not belong to the selected ATS job.")

    previous = db.scalar(select(ApplicationMatchAssessment).where(
        ApplicationMatchAssessment.request_id == request.request_id,
    ))
    if previous is not None:
        if (
            previous.organization_id == user.organization_id
            and previous.application_id == application.id
            and previous.job_id == job.id
        ):
            return _applicant_match_assessment_payload(previous)
        raise HTTPException(409, "This Applicant Match run has already been linked to an application.")

    verified_result, rubric = _verified_applicant_match_result(p, request.request_id)
    rubric_link = db.scalar(select(ApplicantMatchRubricLink).where(
        ApplicantMatchRubricLink.organization_id == user.organization_id,
        ApplicantMatchRubricLink.job_id == job.id,
        ApplicantMatchRubricLink.rubric_id == str(rubric["id"]),
        ApplicantMatchRubricLink.rubric_hash == str(rubric.get("hash") or ""),
    ))
    if rubric_link is None:
        raise HTTPException(409, "Link this saved rubric version to the selected ATS job before saving the assessment.")
    assessment = _safe_applicant_match_assessment(verified_result)
    row = ApplicationMatchAssessment(
        organization_id=user.organization_id,
        application_id=application.id,
        job_id=job.id,
        candidate_id=application.candidate_id,
        created_by_id=user.id,
        request_id=request.request_id,
        rubric_id=str(rubric["id"])[:100],
        rubric_hash=str(rubric.get("hash") or "")[:64] or None,
        rubric_title=str(rubric.get("title") or "")[:200],
        status=assessment["status"],
        match_score=assessment["match_score"],
        assessment_data=assessment,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _applicant_match_assessment_payload(row)


@router.get("/jobs/{job_id}/application-choices")
def list_applicant_match_application_choices(
    job_id: int,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    """Return only minimal candidate display fields for tenant-owned applications."""
    job = db.scalar(select(Job).where(
        Job.id == job_id,
        Job.organization_id == user.organization_id,
    ))
    if job is None:
        raise HTTPException(404, "Job not found in this organisation.")
    rows = db.execute(
        select(
            Application.id,
            Application.candidate_id,
            Candidate.first_name,
            Candidate.last_name,
            Application.stage_id,
            Application.status,
        )
        .join(Candidate, Candidate.id == Application.candidate_id)
        .where(
            Application.organization_id == user.organization_id,
            Application.job_id == job.id,
        )
        .order_by(Application.applied_at.desc())
        .limit(100)
    ).all()
    return [
        {
            "id": row.id,
            "candidate_id": row.candidate_id,
            "candidate_name": " ".join(part for part in (row.first_name, row.last_name) if part).strip(),
            "stage_id": row.stage_id,
            "status": row.status,
        }
        for row in rows
    ]


@router.get("/applications/{application_id}/applicant-match-assessments")
def list_applicant_match_assessments(
    application_id: int,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    application = db.scalar(select(Application).where(
        Application.id == application_id,
        Application.organization_id == user.organization_id,
    ))
    if application is None:
        raise HTTPException(404, "Application not found in this organisation.")
    rows = db.scalars(
        select(ApplicationMatchAssessment).where(
            ApplicationMatchAssessment.application_id == application.id,
            ApplicationMatchAssessment.organization_id == user.organization_id,
        ).order_by(ApplicationMatchAssessment.created_at.desc()).limit(20)
    ).all()
    return [_applicant_match_assessment_payload(row) for row in rows]


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
