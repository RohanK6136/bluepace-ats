import base64
import csv
import hashlib
import hmac
import io
import os
import asyncio
import re
import socket
import subprocess
import ipaddress
import json
import traceback
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from html.parser import HTMLParser
from contextlib import asynccontextmanager
from time import perf_counter
from datetime import date, datetime, time, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, status, Request
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from pydantic import BaseModel
from celery.result import AsyncResult

APP_ENV = os.getenv("APP_ENV", "development")
from sqlalchemy import String, cast, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from celery_app import celery_app
from app.database import SessionLocal, get_db, initialize_database
from app.models import (
    Application,
    AuditLog,
    Candidate,
    CandidateTag,
    CandidateComment,
    CandidateFollower,
    CandidateJobMatch,
    CandidateDocument,
    Email,
    Interview,
    InterviewParticipant,
    InterviewAvailability,
    Job,
    Organization,
    Role,
    Scorecard,
    Note,
    TalentPool,
    TalentPoolMembership,
    Offer,
    AuthSession,
    Stage,
    User,
    ResumeProcessingJob,
)
from app.schemas import (
    ApplicationCreate,
    ApplicationRead,
    ApplicationStageUpdate,
    BulkApplicationUpdate,
    CandidateMatchRead,
    CandidateCreate,
    CandidateRead,
    CandidateTagRead,
    CandidateTagUpdate,
    CandidateCommentCreate,
    CandidateCommentRead,
    CandidateFollowerRead,
    CandidateCollaborationRead,
    CandidateCollaborationUpdate,
    CandidateUpdate,
    JobCreate,
    JobRead,
    JobUpdate,
    MatchFeedbackUpdate,
    ScorecardCreate,
    ScorecardRead,
    EmailTemplateUpdate,
    EmailTemplateTestRequest,
    NoteCreate,
    NoteRead,
    TalentPoolCreate,
    TalentPoolRead,
    TalentPoolCandidateRequest,
    OfferCreate,
    OfferUpdate,
    OfferRead,
    InterviewCreate,
    InterviewStatusUpdate,
    InterviewRead,
    InterviewAvailabilityCreate,
    InterviewAvailabilityRead,
    CandidateComparisonRead,
    CareerAssistantRequest,
    OrganizationRegistration,
    TokenRead,
    UserCreate,
    UserRead,
)
from app.security import JWT_SECRET, create_access_token, create_candidate_portal_token, decode_candidate_portal_token, get_current_user, password_hash, require_roles, refresh_access_token
from app.services.document_limits import MAX_DOCUMENT_SIZE_BYTES, SUPPORTED_DOCUMENT_EXTENSIONS
from app.services.private_storage import private_storage
from app.services.public_media import PublicMediaError, public_media_service
from app.services.extractor import DocumentExtractionError, extractor_service
from app.services.email_notifications import deliver_outbox_email
from app.services.llm_validator import llm_validator
from app.services.matching import MATCH_WEIGHTS, matching_service
from app.services.reranker import reranker_service
from app.services.match_explanation import build_match_explanation
from app.routers.merge_center import router as merge_center_router
from app.routers.offer_management import router as offer_management_router
from app.routers.next_features import router as next_features_router, run_scorecard_automations, run_stage_automations, stage_email_automation_enabled, scorecards_complete, _interview_ics
from app.services.workflow import (
    PIPELINE_STAGES,
    TERMINAL_STAGES,
    ensure_job_stages,
    queue_application_email,
    record_audit,
    serialize_application,
)


_resume_dispatcher_in_flight: set[int] = set()


def _enqueue_resume_ingest(job_id: int):
    """Submit resume processing through the configured Celery task."""
    from app.services.queue_tasks import process_resume_ingest_job
    return process_resume_ingest_job.delay(job_id)


async def _run_resume_job_background(job_id: int) -> None:
    print(f"[resume-dispatcher] starting job_id={job_id}", flush=True)
    try:
        from app.services.queue_tasks import process_resume_ingest_job
        result = await asyncio.to_thread(process_resume_ingest_job.run, job_id)
        print(f"[resume-dispatcher] finished job_id={job_id} result={result}", flush=True)
    except Exception as error:
        print(f"[resume-dispatcher] failed job_id={job_id}: {error}", flush=True)
        traceback.print_exc()
    finally:
        _resume_dispatcher_in_flight.discard(job_id)


async def resume_queue_dispatcher_loop() -> None:
    """DB-backed resume dispatcher used when no external Celery worker is attached."""
    concurrency = max(1, min(int(os.getenv("RESUME_DISPATCHER_CONCURRENCY", "2")), 8))
    while True:
        try:
            available = concurrency - len(_resume_dispatcher_in_flight)
            if available > 0:
                with SessionLocal() as db:
                    job_ids = list(db.scalars(
                        select(ResumeProcessingJob.id)
                        .where(ResumeProcessingJob.status == "queued")
                        .order_by(ResumeProcessingJob.id.asc())
                        .limit(min(available, 8))
                    ).all())
                for job_id in job_ids:
                    if job_id in _resume_dispatcher_in_flight:
                        continue
                    _resume_dispatcher_in_flight.add(job_id)
                    print(f"[resume-dispatcher] claimed job_id={job_id}", flush=True)
                    asyncio.create_task(_run_resume_job_background(job_id))
        except asyncio.CancelledError:
            raise
        except Exception:
            traceback.print_exc()
        await asyncio.sleep(0.25)


async def interview_reminder_loop():
    while True:
        try:
            now = datetime.now(timezone.utc)
            with SessionLocal() as db:
                interviews = db.scalars(
                    select(Interview)
                    .where(Interview.status == "scheduled", Interview.starts_at >= now)
                    .order_by(Interview.starts_at.asc())
                    .limit(500)
                ).all()
                due = []
                for interview in interviews:
                    starts_at = interview.starts_at if interview.starts_at.tzinfo is not None else interview.starts_at.replace(tzinfo=timezone.utc)
                    delta_seconds = (starts_at - now).total_seconds()
                    if not interview.reminder_24_sent and 23 * 3600 <= delta_seconds <= 24 * 3600:
                        due.append((interview, "24h"))
                    if not interview.reminder_1h_sent and 30 * 60 <= delta_seconds <= 60 * 60:
                        due.append((interview, "1h"))

                for interview, reminder_kind in due:
                    application = db.scalar(
                        select(Application)
                        .where(Application.id == interview.application_id)
                        .options(selectinload(Application.job), selectinload(Application.candidate))
                    )
                    if application is None:
                        continue
                    subject, body = _interview_reminder_email(application, interview, reminder_kind, db)
                    email_id = queue_application_email(db, application, subject, body)
                    if reminder_kind == "24h":
                        interview.reminder_24_sent = True
                    else:
                        interview.reminder_1h_sent = True
                    db.commit()
                    await asyncio.to_thread(deliver_outbox_email, email_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            traceback.print_exc()
        await asyncio.sleep(60)


async def _delayed_resume_dispatcher_start():
    await asyncio.sleep(2)
    if os.getenv("ENABLE_DB_RESUME_DISPATCHER", "true").strip().lower() == "true":
        await resume_queue_dispatcher_loop()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    ensure_bootstrap_account()

    reminder_task = None if APP_ENV == "test" else asyncio.create_task(interview_reminder_loop())
    resume_dispatcher_task = None
    if APP_ENV != "test":
        resume_dispatcher_task = asyncio.create_task(_delayed_resume_dispatcher_start())

    try:
        yield
    finally:
        for task in (reminder_task, resume_dispatcher_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


app = FastAPI(title="BluePace Tech ATS API", version="0.4.0", lifespan=lifespan)
app.include_router(merge_center_router)
app.include_router(offer_management_router)
app.include_router(next_features_router)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "bluepace-ats"}

@app.get("/readyz")
def readyz(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ready"}


@app.middleware("http")
async def security_headers_middleware(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if os.getenv("APP_ENV", "development") not in {"development", "test"}:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.middleware("http")
async def add_process_time_header(request, call_next):
    started = perf_counter()
    response = await call_next(request)
    elapsed_ms = (perf_counter() - started) * 1000
    response.headers["X-Process-Time-ms"] = f"{elapsed_ms:.2f}"
    return response

LOCAL_FRONTEND_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
DEPLOYED_FRONTEND_ORIGIN = "https://bluepace-ats-frontend.onrender.com"
DEPLOYED_BACKEND_ORIGIN = os.getenv("BACKEND_PUBLIC_ORIGIN", "https://bluepace-ats-9.onrender.com")
MAX_RESUME_SIZE_BYTES = MAX_DOCUMENT_SIZE_BYTES

def ensure_bootstrap_account() -> None:
    email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    password_hash_value = os.getenv("BOOTSTRAP_ADMIN_PASSWORD_HASH", "").strip()
    full_name = os.getenv("BOOTSTRAP_ADMIN_NAME", "Blupace Tech Recruiting").strip() or "Blupace Tech Recruiting"
    organization_name = os.getenv("BOOTSTRAP_ORGANIZATION_NAME", "Blupace Tech").strip() or "Blupace Tech"
    if not email or not (password or password_hash_value):
        return

    with SessionLocal() as db:
        organization = db.scalar(
            select(Organization).where(Organization.name == organization_name).order_by(Organization.id.asc()).limit(1)
        )
        if organization is None:
            organization = Organization(name=organization_name)
            db.add(organization)
            db.flush()

        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                organization_id=organization.id,
                email=email,
                full_name=full_name,
                password_hash=password_hash_value or password_hash.hash(password),
                role=Role.admin,
                is_active=True,
            )
            db.add(user)
        else:
            user_changed = (
                user.organization_id != organization.id
                or user.full_name != full_name
                or user.role != Role.admin
                or not user.is_active
                or (password_hash_value and user.password_hash != password_hash_value)
            )
            if user_changed:
                user.organization_id = organization.id
                user.full_name = full_name
                user.role = Role.admin
                user.is_active = True
                if password_hash_value:
                    user.password_hash = password_hash_value

        db.commit()


def _public_organization(db: Session) -> Organization:
    configured_id = os.getenv("PUBLIC_ORGANIZATION_ID", "").strip()
    if configured_id:
        try:
            organization_id = int(configured_id)
        except ValueError:
            raise HTTPException(status_code=503, detail="PUBLIC_ORGANIZATION_ID must be an integer")
        organization = db.get(Organization, organization_id)
        if organization is None:
            raise HTTPException(status_code=503, detail="Configured public organization was not found")
        return organization

    configured_name = os.getenv("BOOTSTRAP_ORGANIZATION_NAME", "Blupace Tech").strip()
    if configured_name:
        named_organization = db.scalar(
            select(Organization).where(Organization.name == configured_name).order_by(Organization.id.asc()).limit(1)
        )
        if named_organization is not None:
            return named_organization

    organizations = db.scalars(select(Organization).order_by(Organization.id.asc()).limit(2)).all()
    if len(organizations) == 1:
        return organizations[0]
    if not organizations:
        raise HTTPException(status_code=503, detail="Create an organization before enabling the public portal")
    raise HTTPException(
        status_code=503,
        detail="Multiple organizations exist. Set PUBLIC_ORGANIZATION_ID for the public portal.",
    )


def _split_candidate_name(name: str | None) -> tuple[str, str]:
    cleaned = " ".join((name or "").split()).strip()
    parts = cleaned.split(" ", 1)
    if not parts or not parts[0]:
        return "Applicant", "Candidate"
    return parts[0], parts[1] if len(parts) > 1 and parts[1] else "Candidate"


def _infer_work_mode(text: str | None) -> str:
    content = str(text or "")
    if re.search(r"\b(remote|work from home|wfh|fully remote)\b", content, re.IGNORECASE):
        return "remote"
    if re.search(r"\b(hybrid|flexible work|hybrid work)\b", content, re.IGNORECASE):
        return "hybrid"
    return "onsite"


def _public_admin_id(db: Session, organization_id: int) -> int:
    admin_id = db.scalar(
        select(User.id)
        .where(
            User.organization_id == organization_id,
            User.role == Role.admin,
            User.is_active.is_(True),
        )
        .order_by(User.id.asc())
        .limit(1)
    )
    if admin_id is None:
        raise HTTPException(status_code=503, detail="No active administrator is configured for this portal")
    return admin_id


def get_allowed_origins(configured_origins: str | None = None) -> list[str]:
    configured = configured_origins if configured_origins is not None else os.getenv("ALLOWED_ORIGINS", "")
    origins = [*LOCAL_FRONTEND_ORIGINS, DEPLOYED_FRONTEND_ORIGIN]
    origins.extend(origin.strip() for origin in configured.split(",") if origin.strip())
    return list(dict.fromkeys(origins))


async def _read_resume_upload(file: UploadFile) -> tuple[str, bytes]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX resumes are supported.")

    content = await file.read(MAX_RESUME_SIZE_BYTES + 1)
    if len(content) > MAX_RESUME_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Resume must be 5 MB or smaller.")
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded resume is empty.")
    return suffix, content


class _JobPageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title_parts = []
        self.visible_parts = []
        self.meta = {}
        self.jsonld_blocks = []
        self._capture_title = False
        self._capture_script = False
        self._script_type = ""
        self._script_parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs_map = dict(attrs)
        if tag == "title":
            self._capture_title = True
        elif tag == "meta":
            key = attrs_map.get("name") or attrs_map.get("property")
            value = attrs_map.get("content")
            if key and value:
                self.meta[key.casefold()] = value.strip()
        elif tag == "script":
            self._capture_script = True
            self._script_type = (attrs_map.get("type") or "").casefold()
            self._script_parts = []
        elif tag in {"style", "noscript"}:
            self._skip_depth += 1
        elif self._skip_depth == 0 and tag in {"br", "p", "div", "li", "section", "article", "h1", "h2", "h3", "h4", "h5"}:
            self.visible_parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._capture_title = False
        elif tag == "script":
            if self._capture_script and "ld+json" in self._script_type:
                self.jsonld_blocks.append("".join(self._script_parts))
            self._capture_script = False
            self._script_type = ""
            self._script_parts = []
        elif tag in {"style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._capture_title:
            self.title_parts.append(data)
        if self._capture_script:
            self._script_parts.append(data)
        if self._skip_depth == 0 and not self._capture_script and data.strip():
            self.visible_parts.append(data.strip())

    def visible_text(self):
        return re.sub(r"\s+", " ", " ".join(self.visible_parts)).strip()

    def title(self):
        return re.sub(r"\s+", " ", " ".join(self.title_parts)).strip()


def _clean_job_link(value: str) -> tuple[str | None, str]:
    cleaned = (value or "").strip()
    markdown = re.match(r"^\s*\[([^\]]+)\]\((https?://[^)\s]+)\)\s*$", cleaned)
    if markdown:
        return markdown.group(2), markdown.group(1).strip()
    return cleaned or None, ""


def _validate_public_job_url(raw_url: str) -> str:
    parsed = urllib.parse.urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Enter a valid public HTTP/HTTPS job URL.")
    if parsed.port not in {None, 80, 443}:
        raise HTTPException(status_code=400, detail="Only standard HTTP/HTTPS job URLs are supported.")

    try:
        addresses = {
            info[4][0]
            for info in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        }
    except socket.gaierror as error:
        raise HTTPException(status_code=422, detail=f"Could not resolve the job URL host: {parsed.hostname}") from error

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise HTTPException(status_code=400, detail="The job URL must point to a public internet host.")
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))


def _jsonld_jobposting(blocks: list[str]) -> dict:
    for block in blocks:
        try:
            payload = json.loads(unescape(block))
        except Exception:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
                return candidate
            if isinstance(candidate, dict) and isinstance(candidate.get("@graph"), list):
                for node in candidate["@graph"]:
                    if isinstance(node, dict) and node.get("@type") == "JobPosting":
                        return node
    return {}


def _html_to_plain_text(value) -> str:
    if not value:
        return ""
    parser = HTMLParser()
    try:
        parser.feed(str(value))
        parser.close()
        return re.sub(r"\s+", " ", " ".join(parser.visible_parts)).strip() if hasattr(parser, "visible_parts") else re.sub(r"<[^>]+>", " ", unescape(str(value)))
    except Exception:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(str(value)))).strip()


def _fetch_job_page(raw_url: str) -> tuple[str, str, dict]:
    url = _validate_public_job_url(raw_url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 BluePace-ATS Job Importer/1.0",
            "Accept": "text/html,application/xhtml+xml",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            content_type = (response.headers.get("Content-Type") or "").casefold()
            payload = response.read(3_000_000)
            final_url = response.geturl()
    except (urllib.error.URLError, TimeoutError) as error:
        raise HTTPException(status_code=422, detail=f"Could not fetch the job page: {error}") from error

    if "html" not in content_type:
        raise HTTPException(status_code=422, detail="The supplied URL did not return an HTML job page.")

    final_url = _validate_public_job_url(final_url)
    parser = _JobPageParser()
    try:
        parser.feed(payload.decode("utf-8", errors="replace"))
        parser.close()
    except Exception as error:
        raise HTTPException(status_code=422, detail="The job page could not be parsed.") from error

    posting = _jsonld_jobposting(parser.jsonld_blocks)
    description = _html_to_plain_text(posting.get("description")) if posting else ""
    if not description:
        description = parser.visible_text()
    description = re.sub(r"\s+", " ", description).strip()
    if len(description) < 40:
        raise HTTPException(
            status_code=422,
            detail="Could not extract a usable job description from that page. Use the PDF/DOCX upload instead.",
        )

    title = str(posting.get("title") or parser.title() or "").strip()
    if " | " in title:
        title = title.split(" | ", 1)[0].strip()
    location = None
    if posting:
        job_location = posting.get("jobLocation")
        if isinstance(job_location, dict):
            address = job_location.get("address") if isinstance(job_location.get("address"), dict) else {}
            location = address.get("addressLocality") or address.get("addressRegion") or job_location.get("name")
        elif isinstance(job_location, list) and job_location:
            first = job_location[0] if isinstance(job_location[0], dict) else {}
            address = first.get("address") if isinstance(first.get("address"), dict) else {}
            location = address.get("addressLocality") or address.get("addressRegion") or first.get("name")
    if not location:
        location = parser.meta.get("location")

    return final_url, title, {
        "description": description,
        "location": location,
        "employment_type": posting.get("employmentType") if posting else None,
        "source_url": final_url,
        "source": "Job URL import",
    }


@app.post("/resume-processing/job-description", response_class=JSONResponse)
async def resume_lab_job_description(
    file: UploadFile | None = File(default=None),
    job_url: str | None = Form(default=None),
):
    """Load a job description from PDF/DOCX or a public job URL."""
    cleaned_url = (job_url or "").strip()
    if file is None and not cleaned_url:
        raise HTTPException(status_code=400, detail="Provide a JD PDF/DOCX file or a public job URL.")

    if file is not None and cleaned_url:
        raise HTTPException(status_code=400, detail="Provide either a JD file or a public job URL, not both.")

    if file is not None:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".pdf", ".docx"}:
            raise HTTPException(status_code=400, detail="JD upload must be a PDF or DOCX file.")
        content = await file.read(MAX_DOCUMENT_SIZE_BYTES + 1)
        if len(content) > MAX_DOCUMENT_SIZE_BYTES:
            raise HTTPException(status_code=413, detail="JD file must be 5 MB or smaller.")
        if not content:
            raise HTTPException(status_code=400, detail="The uploaded JD file is empty.")
        try:
            extracted = extractor_service.extract_to_json(content, f"job-description{suffix}")
        except DocumentExtractionError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        description = str(extracted.get("raw_text") or "").strip()
        if len(description) < 40:
            raise HTTPException(status_code=422, detail="Could not extract a usable job description from that file.")
        return {
            "status": "success",
            "source": "file",
            "filename": file.filename,
            "title": "",
            "description": description,
        }

    final_url, title, payload = _fetch_job_page(cleaned_url)
    return {
        "status": "success",
        "source": "url",
        "source_url": final_url,
        "title": title,
        "description": payload["description"],
        "location": payload.get("location"),
        "employment_type": payload.get("employment_type"),
    }


allowed_origins = get_allowed_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"^https://[a-z0-9-]+\.onrender\.com$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Process-Time-ms"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)

class ValidationRequest(BaseModel):
    resume_json: dict
    job_description: str


class ResumeLabSyncRequest(BaseModel):
    resume_json: dict
    job_id: int | None = None
    job_fit: dict | None = None


def _get_org_record(db: Session, model, record_id: int, organization_id: int):
    record = db.scalar(
        select(model).where(model.id == record_id, model.organization_id == organization_id)
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return record


def _audit_candidate(candidate: Candidate) -> dict:
    return {
        "first_name": candidate.first_name,
        "last_name": candidate.last_name,
        "email": candidate.email,
        "phone": candidate.phone,
        "linkedin_url": candidate.linkedin_url,
        "source": candidate.source,
        "resume_storage_key": candidate.resume_storage_key,
    }


def _audit_job(job: Job) -> dict:
    return {
        "title": job.title,
        "description": job.description,
        "department": job.department,
        "location": job.location,
        "employment_type": job.employment_type,
        "work_mode": job.work_mode,
        "status": job.status,
        "required_skills": job.required_skills,
        "minimum_experience_years": job.minimum_experience_years,
        "fresher_allowed": job.fresher_allowed,
    }


def _application_query(
    organization_id: int,
    *,
    job_id: int | None = None,
    stage_name: str | None = None,
    source: str | None = None,
    skill: str | None = None,
    search: str | None = None,
    applied_after: date | None = None,
    applied_before: date | None = None,
):
    statement = (
        select(Application)
        .options(
            selectinload(Application.job),
            selectinload(Application.candidate),
            selectinload(Application.stage),
        )
        .join(Application.job)
        .join(Application.candidate)
        .outerjoin(Application.stage)
        .where(Application.organization_id == organization_id)
    )
    if job_id is not None:
        statement = statement.where(Application.job_id == job_id)
    if stage_name:
        statement = statement.where(Stage.name == stage_name)
    if source:
        statement = statement.where(Candidate.source.ilike(source))
    if skill:
        statement = statement.where(cast(Candidate.resume_data, String).ilike(f"%{skill}%"))
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            Candidate.first_name.ilike(pattern)
            | Candidate.last_name.ilike(pattern)
            | Candidate.email.ilike(pattern)
            | Job.title.ilike(pattern)
        )
    if applied_after:
        statement = statement.where(
            Application.applied_at >= datetime.combine(applied_after, time.min, tzinfo=timezone.utc)
        )
    if applied_before:
        statement = statement.where(
            Application.applied_at <= datetime.combine(applied_before, time.max, tzinfo=timezone.utc)
        )
    return statement.order_by(Application.applied_at.desc())


def _safe_csv_value(value):
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def _format_interview_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return moment.strftime("%d %B %Y, %I:%M %p %z")


REMINDER_EMAIL_TEMPLATES = {
    "24h": {
        "subject": "Interview reminder — {{job_title}}",
        "body": "Hello {{candidate_name}},\n\nThis is a reminder that your interview for {{job_title}} is scheduled for {{interview_date}} at {{interview_time}}.\nDuration: {{interview_duration}} minutes\nInterview mode: {{interview_mode}}\nMeeting link: {{meeting_link}}\nInterview location: {{interview_location}}\n\nTrack your application: {{candidate_portal_url}}\n\nRegards,\nBlupace Tech Talent Team",
    },
    "1h": {
        "subject": "Interview starts soon — {{job_title}}",
        "body": "Hello {{candidate_name}},\n\nYour interview for {{job_title}} starts in about one hour at {{interview_time}} on {{interview_date}}.\nDuration: {{interview_duration}} minutes\nInterview mode: {{interview_mode}}\nMeeting link: {{meeting_link}}\nInterview location: {{interview_location}}\n\nTrack your application: {{candidate_portal_url}}\n\nRegards,\nBlupace Tech Talent Team",
    },
}


def _render_email_template(template: dict, values: dict[str, str]) -> tuple[str, str]:
    subject = str(template.get("subject") or "")
    body = str(template.get("body") or "")
    for key, value in values.items():
        placeholder = "{{" + key + "}}"
        subject = subject.replace(placeholder, value)
        body = body.replace(placeholder, value)
    return subject, body


def _interview_reminder_email(application: Application, interview: Interview, reminder_kind: str, db: Session) -> tuple[str, str]:
    organization = db.get(Organization, application.organization_id)
    custom = organization.email_templates if organization and organization.email_templates else {}
    key = "Interview Reminder 24h" if reminder_kind == "24h" else "Interview Reminder 1h"
    template = custom.get(key) or REMINDER_EMAIL_TEMPLATES[reminder_kind]
    portal_url = f"{DEPLOYED_FRONTEND_ORIGIN}?portal={urllib.parse.quote(create_candidate_portal_token(application.id))}"
    values = {
        "candidate_name": application.candidate.first_name or "Candidate",
        "job_title": application.job.title,
        "interview_date": interview.starts_at.strftime("%d %B %Y"),
        "interview_time": interview.starts_at.strftime("%I:%M %p %Z"),
        "interview_duration": str(interview.duration_minutes),
        "interview_mode": "Online" if interview.mode == "online" else "Offline / On-site",
        "meeting_link": interview.meeting_url or "",
        "interview_location": interview.location or "",
        "interview_calendar_url": f"{DEPLOYED_BACKEND_ORIGIN}/public/application/{urllib.parse.quote(create_candidate_portal_token(application.id))}/interviews/{interview.id}.ics",
        "candidate_portal_url": portal_url,
        "company_name": "Blupace Tech",
    }
    return _render_email_template(template, values)


DEFAULT_EMAIL_TEMPLATES = {
    "Applied": {
        "subject": "Application received — {{job_title}}",
        "body": "Hello {{candidate_name}},\n\nYour application for {{job_title}} has been received by Blupace Tech. We will review your profile and share the next update by email.\n\nTrack your application: {{candidate_portal_url}}\n\nRegards,\nBlupace Tech Talent Team",
    },
    "Screening": {
        "subject": "Application update — {{job_title}}",
        "body": "Hello {{candidate_name}},\n\nYour application for {{job_title}} has moved to our screening stage. We will contact you with the next update.\n\nTrack your application: {{candidate_portal_url}}\n\nRegards,\nBlupace Tech Talent Team",
    },
    "Interview": {
        "subject": "Interview invitation — {{job_title}}",
        "body": "Hello {{candidate_name}},\n\nThank you for your application for {{job_title}} with Blupace Tech. We would like to invite you to the next stage of the selection process.\n\nInterview date and time: {{interview_date}} {{interview_time}}\nDuration: {{interview_duration}} minutes\nInterview mode: {{interview_mode}}\nMeeting link: {{meeting_link}}\nInterview location: {{interview_location}}\n\nTrack your application: {{candidate_portal_url}}\n\nRegards,\nBlupace Tech Talent Team",
    },
    "Offer": {
        "subject": "Position offer — {{job_title}}",
        "body": "Hello {{candidate_name}},\n\nWe are pleased to inform you that Blupace Tech would like to offer you the position of {{job_title}}. Our Talent Team will share the formal offer and joining details with you.\n\nTrack your application: {{candidate_portal_url}}\n\nRegards,\nBlupace Tech Talent Team",
    },
    "Hired": {
        "subject": "Selected for {{job_title}}",
        "body": "Hello {{candidate_name}},\n\nCongratulations. You have been selected for the position of {{job_title}} at Blupace Tech. Our Talent Team will contact you with the next steps and joining formalities.\n\nTrack your application: {{candidate_portal_url}}\n\nRegards,\nBlupace Tech Talent Team",
    },
    "Rejected": {
        "subject": "Application update — {{job_title}}",
        "body": "Hello {{candidate_name}},\n\nThank you for taking the time to apply for {{job_title}} at Blupace Tech. After reviewing your application, we will not be progressing with your application for this position at this time. We appreciate your interest and wish you success in your career.\n\nTrack your application: {{candidate_portal_url}}\n\nRegards,\nBlupace Tech Talent Team",
    },
}


def _stage_email(
    application: Application,
    stage_name: str,
    *,
    db: Session | None = None,
    interview_starts_at: datetime | None = None,
    interview_duration_minutes: int = 60,
    interview_mode: str = "online",
    interview_location: str | None = None,
    interview_meeting_url: str | None = None,
    interview_id: int | None = None,
) -> tuple[str, str]:
    candidate = application.candidate
    job_title = application.job.title
    first_name = candidate.first_name or "Candidate"
    portal_url = f"{DEPLOYED_FRONTEND_ORIGIN}?portal={urllib.parse.quote(create_candidate_portal_token(application.id))}"

    template = DEFAULT_EMAIL_TEMPLATES.get(stage_name)
    if db is not None:
        organization = db.get(Organization, application.organization_id)
        custom_templates = organization.email_templates if organization and organization.email_templates else {}
        template = custom_templates.get(stage_name) or template
    values = {
        "candidate_name": first_name,
        "job_title": job_title,
        "interview_date": interview_starts_at.strftime("%d %B %Y") if interview_starts_at else "",
        "interview_time": interview_starts_at.strftime("%I:%M %p %Z") if interview_starts_at else "",
        "interview_duration": str(interview_duration_minutes),
        "interview_mode": "Online" if interview_mode == "online" else "Offline / On-site",
        "meeting_link": interview_meeting_url or "",
        "interview_location": interview_location or "",
        "interview_calendar_url": (
            f"{DEPLOYED_BACKEND_ORIGIN}/public/application/{urllib.parse.quote(create_candidate_portal_token(application.id))}/interviews/{interview_id}.ics"
            if interview_id else ""
        ),
        "candidate_portal_url": portal_url,
        "company_name": "Blupace Tech",
    }
    return _render_email_template(template, values)

def _serialize_candidate_match(match: CandidateJobMatch, job: Job | None = None) -> dict:
    profile = match.candidate.resume_data or {}
    candidate_skill_lookup = {
        str(skill).casefold().strip()
        for skill in (profile.get("skills") or [])
        if str(skill).strip()
    }
    matched_skills = [str(skill).strip() for skill in (match.matched_skills or []) if str(skill).strip()]
    matched_set = {str(skill).casefold().strip() for skill in matched_skills}
    analysis = (job.jd_analysis if job is not None else {}) or {}
    required_skills = [str(skill) for skill in analysis.get("required_skills", []) if str(skill).strip()]
    preferred_skills = [str(skill) for skill in analysis.get("preferred_skills", []) if str(skill).strip()]
    matched_required = [
        skill for skill in required_skills
        if skill.casefold().strip() in candidate_skill_lookup or skill.casefold().strip() in matched_set
    ]
    matched_preferred = [
        skill for skill in preferred_skills
        if skill.casefold().strip() in candidate_skill_lookup or skill.casefold().strip() in matched_set
    ]
    breakdown = match.score_breakdown or {}
    experience = (profile.get("experience") or [])
    projects = profile.get("university_projects") or profile.get("projects") or []
    compact_evidence = []
    for item in experience[:3]:
        if isinstance(item, dict):
            title = " · ".join(str(item.get(key)).strip() for key in ("title", "company") if item.get(key))
            details = str(item.get("description") or "").strip()
            if title or details:
                compact_evidence.append({"type": "experience", "title": title or "Experience", "details": details})
    for item in projects[:3]:
        text_value = str(item).strip()
        if text_value:
            compact_evidence.append({"type": "project", "title": text_value, "details": ""})
    experience_years = matching_service._estimate_experience_years(experience)
    match_explanation = build_match_explanation(
        candidate_name=f"{match.candidate.first_name} {match.candidate.last_name}".strip(),
        job_title=job.title if job is not None else "selected role",
        match_score=match.model_score,
        matched_required=matched_required,
        matched_preferred=matched_preferred,
        skill_gaps=match.skill_gaps or [],
        experience_years=experience_years,
        required_experience_years=analysis.get("minimum_experience_years"),
        evidence=compact_evidence,
    )
    return {
        "id": match.id,
        "job_id": match.job_id,
        "candidate_id": match.candidate_id,
        "candidate_name": f"{match.candidate.first_name} {match.candidate.last_name}".strip(),
        "candidate_email": match.candidate.email,
        "model_score": match.model_score,
        "effective_score": match.recruiter_override if match.recruiter_override is not None else match.model_score,
        "recruiter_override": match.recruiter_override,
        "recruiter_note": match.recruiter_note,
        "score_breakdown": breakdown,
        "score_weights": MATCH_WEIGHTS,
        "matched_skills": matched_skills,
        "matched_required_skills": matched_required,
        "matched_preferred_skills": matched_preferred,
        "skill_gaps": match.skill_gaps or [],
        "experience_years": experience_years,
        "required_experience_years": analysis.get("minimum_experience_years"),
        "project_evidence": {"coverage": breakdown.get("project_evidence", 0)},
        "match_evidence": matching_service.score_candidate(job, match.candidate).get("match_evidence", {}),
        "match_explanation": match_explanation,
        "explanations": match.explanations or [],
        "semantic_mode": match.semantic_mode,
        "decision_support_only": True,
        "cv_summary": match.candidate.cv_summary or matching_service._fallback_candidate_summary(match.candidate),
        "rerank_score": breakdown.get("rerank_score"),
        "rerank_mode": breakdown.get("rerank_mode"),
        "model_score_before_rerank": breakdown.get("model_score_before_rerank"),
    }


@app.get("/public/jobs")
def public_jobs(
    search: str | None = None,
    department: str | None = None,
    location: str | None = None,
    work_mode: str | None = Query(default=None, pattern="^(remote|hybrid|onsite)$"),
    db: Session = Depends(get_db),
):
    organization = _public_organization(db)
    statement = select(Job).where(Job.organization_id == organization.id, Job.status == "open")
    if department:
        statement = statement.where(Job.department.ilike("%" + department.strip() + "%"))
    if location:
        statement = statement.where(Job.location.ilike("%" + location.strip() + "%"))
    if work_mode:
        statement = statement.where(Job.work_mode == work_mode)
    jobs = db.scalars(statement.order_by(Job.created_at.desc()).limit(100)).all()
    if search:
        needle = search.casefold().strip()
        jobs = [job for job in jobs if needle in " ".join([job.title, job.description, job.department or "", job.location or "", " ".join(job.required_skills or [])]).casefold()]
    return [
        {
            "id": job.id,
            "title": job.title,
            "description": job.description,
            "department": job.department,
            "location": job.location,
            "employment_type": job.employment_type,
            "work_mode": job.work_mode,
            "required_skills": job.required_skills or [],
            "minimum_experience_years": job.minimum_experience_years,
            "fresher_allowed": job.fresher_allowed,
            "source_url": (job.jd_analysis or {}).get("source_url"),
        }
        for job in jobs
    ]


@app.post("/public/career-assistant", response_class=JSONResponse)
def public_career_assistant(
    request: CareerAssistantRequest,
    db: Session = Depends(get_db),
):
    """Translate natural-language career intent into strict filters + ranked jobs."""
    query = " ".join(request.query.strip().split())
    organization = _public_organization(db)
    jobs = list(
        db.scalars(
            select(Job)
            .where(Job.organization_id == organization.id, Job.status == "open")
            .order_by(Job.created_at.desc())
            .limit(200)
        ).all()
    )

    lower = query.casefold()
    experience_match = re.search(r"\b(\d{1,2})\s*(?:-|to)\s*(\d{1,2})\+?\s*(?:years?|yrs?)\b", lower)
    single_experience = re.search(r"\b(?:at least|minimum of|min)?\s*(\d{1,2})\+?\s*(?:years?|yrs?)\b", lower)
    minimum_experience = int(experience_match.group(1)) if experience_match else (
        int(single_experience.group(1)) if single_experience else None
    )
    maximum_experience = int(experience_match.group(2)) if experience_match else None

    if re.search(r"\b(remote|work from home|wfh|fully remote)\b", lower):
        work_mode = "remote"
    elif re.search(r"\bhybrid\b", lower):
        work_mode = "hybrid"
    elif re.search(r"\b(on[- ]?site|onsite|office)\b", lower):
        work_mode = "onsite"
    else:
        work_mode = None

    # Resolve a location only from locations actually present in the published jobs.
    location = None
    for job in jobs:
        candidate_location = (job.location or "").strip()
        if candidate_location and candidate_location.casefold() in lower:
            location = candidate_location
            break
        for token in re.findall(r"[a-zA-Z][a-zA-Z .'-]{2,}", candidate_location):
            token = token.strip()
            if token and token.casefold() in lower:
                location = candidate_location
                break
        if location:
            break

    detected_skills = []
    try:
        detected_skills = matching_service._extract_skills(query)
    except Exception:
        detected_skills = []

    stop_words = {
        "i", "want", "need", "looking", "for", "a", "an", "the", "job", "jobs",
        "role", "roles", "with", "in", "at", "from", "to", "and", "or", "my",
        "experience", "years", "year", "remote", "hybrid", "onsite", "on-site",
        "work", "home", "please", "find", "me",
    }
    role_terms = [
        token for token in re.findall(r"[a-zA-Z][a-zA-Z+#.-]{2,}", lower)
        if token not in stop_words and token not in {s.casefold() for s in detected_skills}
    ]

    query_vector = matching_service.embed_texts([query])[0]
    candidates = []
    for job in jobs:
        job_text = " ".join([
            job.title or "",
            job.description or "",
            job.department or "",
            job.location or "",
            " ".join(job.required_skills or []),
        ]).casefold()

        if work_mode and job.work_mode != work_mode:
            continue
        if location and (job.location or "").casefold() != location.casefold():
            continue
        if minimum_experience is not None:
            job_min = job.minimum_experience_years or 0
            if maximum_experience is not None:
                if job_min > maximum_experience:
                    continue
            elif job_min > minimum_experience and minimum_experience < 10:
                continue

        matched_skills = [
            skill for skill in detected_skills
            if skill.casefold() in job_text
        ]
        role_hits = [
            term for term in role_terms
            if term in (job.title or "").casefold() or term in (job.department or "").casefold()
        ]
        lexical_score = min(
            100,
            len(matched_skills) * 18
            + len(role_hits) * 15
            + (25 if query.casefold() in job_text else 0)
            + (10 if work_mode else 0)
            + (10 if location else 0),
        )

        semantic_score = 0
        if query_vector is not None and job.embedding:
            try:
                import math
                dot = sum(float(a) * float(b) for a, b in zip(query_vector, job.embedding))
                q_norm = math.sqrt(sum(float(a) * float(a) for a in query_vector))
                j_norm = math.sqrt(sum(float(b) * float(b) for b in job.embedding))
                if q_norm and j_norm:
                    semantic_score = round(max(0.0, min(1.0, dot / (q_norm * j_norm))) * 100)
            except Exception:
                semantic_score = 0

        final_score = round(0.45 * lexical_score + 0.55 * semantic_score) if semantic_score else lexical_score
        reason_parts = []
        if matched_skills:
            reason_parts.append("Skills: " + ", ".join(matched_skills[:5]))
        if role_hits:
            reason_parts.append("Role signal: " + ", ".join(role_hits[:4]))
        if job.location:
            reason_parts.append("Location: " + job.location)
        if job.work_mode:
            reason_parts.append("Work mode: " + job.work_mode)
        candidates.append(
            {
                "job": job,
                "score": final_score,
                "matched_skills": matched_skills,
                "reason": " · ".join(reason_parts) or "Relevant published role based on your request.",
            }
        )

    candidates.sort(key=lambda item: (item["score"], item["job"].created_at), reverse=True)
    return {
        "query": query,
        "intent": {
            "role_terms": role_terms[:8],
            "skills": detected_skills[:12],
            "location": location,
            "work_mode": work_mode,
            "minimum_experience_years": minimum_experience,
            "maximum_experience_years": maximum_experience,
        },
        "results": [
            {
                "id": item["job"].id,
                "title": item["job"].title,
                "description": item["job"].description,
                "department": item["job"].department,
                "location": item["job"].location,
                "employment_type": item["job"].employment_type,
                "work_mode": item["job"].work_mode,
                "required_skills": item["job"].required_skills or [],
                "minimum_experience_years": item["job"].minimum_experience_years,
                "fresher_allowed": item["job"].fresher_allowed,
                "match_score": item["score"],
                "matched_skills": item["matched_skills"],
                "reason": item["reason"],
            }
            for item in candidates[:10]
        ],
        "mode": "hard_filters_plus_semantic_retrieval" if query_vector is not None else "hard_filters_plus_lexical_retrieval",
    }


@app.post("/public/jobs/{job_id}/apply")
async def public_apply(
    job_id: int,
    file: UploadFile = File(...),
    full_name: str | None = Form(default=None),
    email: str | None = Form(default=None),
    phone: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    started = perf_counter()
    organization = _public_organization(db)
    job = db.scalar(
        select(Job).where(
            Job.id == job_id,
            Job.organization_id == organization.id,
            Job.status == "open",
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Open job not found")

    if not (email or "").strip():
        raise HTTPException(status_code=422, detail="Email is required to submit an application")

    suffix, content = await _read_resume_upload(file)
    candidate_email = (email or "").strip().lower()
    candidate_name = (full_name or "").strip() or Path(file.filename or "").stem
    first_name, last_name = _split_candidate_name(candidate_name)
    candidate_phone = (phone or "").strip() or None

    admin_id = _public_admin_id(db, organization.id)
    candidate = db.scalar(
        select(Candidate).where(
            Candidate.organization_id == organization.id,
            Candidate.email == candidate_email,
        )
    )
    if candidate is None:
        candidate = Candidate(
            organization_id=organization.id,
            created_by_id=admin_id,
            first_name=first_name,
            last_name=last_name,
            email=candidate_email,
            phone=candidate_phone,
            source="Public Career Portal",
            resume_data={
                "processing_status": "queued",
                "resume_filename": file.filename,
            },
        )
        db.add(candidate)
        db.flush()
    else:
        candidate.first_name = first_name
        candidate.last_name = last_name
        candidate.phone = candidate_phone or candidate.phone
        candidate.source = candidate.source or "Public Career Portal"

    existing_application = db.scalar(
        select(Application.id).where(
            Application.job_id == job.id,
            Application.candidate_id == candidate.id,
        )
    )
    if existing_application is not None:
        db.rollback()
        raise HTTPException(status_code=409, detail="You have already applied for this position")

    storage_key = f"{organization.id}/public/{candidate.id}/{os.urandom(16).hex()}{suffix}"
    storage_reference = private_storage.put_bytes(
        storage_key,
        content,
        file.content_type or "application/octet-stream",
    )
    candidate.resume_storage_key = storage_reference

    stages = ensure_job_stages(db, job)
    application = Application(
        organization_id=organization.id,
        job_id=job.id,
        candidate_id=candidate.id,
        stage_id=stages["Applied"].id,
        status="active",
    )
    db.add(application)
    db.flush()

    subject, body = _stage_email(application, "Applied", db=db)
    email_id = queue_application_email(db, application, subject, body)

    batch_id = uuid4().hex
    processing_job = ResumeProcessingJob(
        batch_id=batch_id,
        organization_id=organization.id,
        created_by_id=admin_id,
        candidate_id=candidate.id,
        application_id=application.id,
        filename=file.filename or f"resume{suffix}",
        storage_path=str(storage_reference),
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        status="queued",
    )
    db.add(processing_job)
    db.commit()
    db.refresh(processing_job)

    processing_mode = "external_queue"
    try:
        task = _enqueue_resume_ingest(processing_job.id)
        processing_job.task_id = task.id
        db.commit()
    except Exception as error:
        # The app also has a DB-backed dispatcher. Keep the job queued so an
        # internal worker can process it instead of failing the public apply.
        dispatcher_enabled = os.getenv("ENABLE_DB_RESUME_DISPATCHER", "true").strip().lower() == "true"
        if not dispatcher_enabled:
            processing_job.status = "failed"
            processing_job.error_message = f"Queue submission failed: {error}"[:4000]
            db.commit()
            private_storage.delete(processing_job.storage_path)
            raise HTTPException(
                status_code=503,
                detail="Your application could not be placed in the processing queue. Please retry.",
            ) from error
        processing_job.status = "queued"
        processing_job.task_id = None
        processing_job.error_message = f"External queue unavailable; using DB dispatcher: {error}"[:4000]
        processing_mode = "db_dispatcher"
        db.commit()

    return {
        "status": "accepted",
        "application_id": application.id,
        "processing_job_id": processing_job.id,
        "processing_mode": processing_mode,
        "message": f"Application submitted for {job.title}. Your resume is being processed in the background.",
        "accepted_handler_ms": round((perf_counter() - started) * 1000, 2),
    }


@app.post("/auth/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register_organization(
    request: OrganizationRegistration,
    db: Session = Depends(get_db),
):
    if APP_ENV != "test":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization registration is disabled. Contact the system administrator for access.",
        )

    normalized_email = str(request.email).strip().lower()
    if db.scalar(select(User.id).where(User.email == normalized_email)) is not None:
        raise HTTPException(status_code=409, detail="A user with this email already exists")

    organization = Organization(name=request.organization_name.strip())
    db.add(organization)
    db.flush()
    user = User(
        organization_id=organization.id,
        email=normalized_email,
        full_name=request.full_name.strip(),
        password_hash=password_hash.hash(request.password),
        role=Role.admin,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/auth/token", response_model=TokenRead)
def login(
    request: Request,
    credentials: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    login_email = credentials.username.strip().lower()
    user = db.scalar(select(User).where(User.email == login_email))

    # Only repair the shared bootstrap account when it is actually missing.
    # Re-hashing the configured password on every successful login made sign-in
    # unnecessarily slow and also caused an extra write transaction.
    bootstrap_email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    bootstrap_password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    bootstrap_password_hash = os.getenv("BOOTSTRAP_ADMIN_PASSWORD_HASH", "").strip()
    bootstrap_password_valid = bool(
        bootstrap_password and credentials.password == bootstrap_password
    ) or bool(
        bootstrap_password_hash
        and password_hash.verify(credentials.password, bootstrap_password_hash)
    )
    if (
        user is None
        and bootstrap_email
        and bootstrap_password_valid
        and login_email == bootstrap_email
    ):
        ensure_bootstrap_account()
        user = db.scalar(select(User).where(User.email == login_email))

    now = datetime.now(timezone.utc)
    if user is not None and user.locked_until is not None and user.locked_until > now:
        raise HTTPException(status_code=429, detail="Account temporarily locked after repeated failed sign-in attempts.")

    valid = bool(user and user.is_active and password_hash.verify(credentials.password, user.password_hash))
    if not valid:
        if user is not None:
            user.failed_login_attempts = int(user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= 5:
                from datetime import timedelta
                user.locked_until = now + timedelta(minutes=15)
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user.failed_login_attempts = 0
    user.locked_until = None
    record_audit(db, user, "auth.login", "user", user.id, after={"ip": request.client.host if request.client else None})
    # create_access_token persists the AuthSession and commits the transaction,
    # so keep audit + session creation in one database commit.
    access_token = create_access_token(user, db=db, ip_address=request.client.host if request.client else None, user_agent=request.headers.get("user-agent"))
    return TokenRead(access_token=access_token, user=UserRead.model_validate(user))


@app.get("/auth/me", response_model=UserRead)
def get_me(user: User = Depends(get_current_user)):
    return user


@app.post("/auth/refresh", response_model=TokenRead)
def refresh_token(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    return TokenRead(access_token=refresh_access_token(token, db))


@app.post("/auth/logout")
def logout(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    from app.security import revoke_access_token
    return {"status": "revoked", "revoked": revoke_access_token(token, db)}


@app.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    request: UserCreate,
    user: User = Depends(require_roles(Role.admin)),
    db: Session = Depends(get_db),
):
    if APP_ENV != "test":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Additional user accounts are disabled. Use the shared recruiting login.",
        )
    email = str(request.email).strip().lower()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    created = User(
        organization_id=user.organization_id,
        email=email,
        full_name=request.full_name.strip(),
        password_hash=password_hash.hash(request.password),
        role=request.role,
        is_active=True,
    )
    db.add(created)
    db.commit()
    db.refresh(created)
    return created



def _refresh_candidate_embedding(candidate_id: int, organization_id: int) -> None:
    """Build a candidate embedding off the request path."""
    try:
        with SessionLocal() as session:
            candidate = session.scalar(
                select(Candidate).where(
                    Candidate.id == candidate_id,
                    Candidate.organization_id == organization_id,
                )
            )
            if candidate is None:
                return
            vector = matching_service.embed_texts([matching_service.candidate_embedding_text(candidate)])[0]
            if vector is not None:
                candidate.embedding = vector
                session.commit()
    except Exception:
        traceback.print_exc()


def _candidate_search_matches(content: str, query: str) -> bool:
    """Evaluate recruiter Boolean search safely against normalized candidate text."""
    tokens = re.findall(r'"[^"]*"|\(|\)|\bAND\b|\bOR\b|\bNOT\b|[^\s()]+', query, flags=re.IGNORECASE)
    tokens = [token.strip() for token in tokens if token.strip()]
    if not tokens:
        return True

    position = 0
    haystack = content.casefold()

    def parse_or():
        nonlocal position
        value = parse_and()
        while position < len(tokens) and tokens[position].casefold() == "or":
            position += 1
            value = value or parse_and()
        return value

    def parse_and():
        nonlocal position
        value = parse_unary()
        while position < len(tokens):
            token = tokens[position].casefold()
            if token == "and":
                position += 1
                value = value and parse_unary()
                continue
            # Recruiter queries commonly omit AND before NOT or a grouped term:
            # "Python SQL NOT Java" means "Python AND SQL AND NOT Java".
            if token == "not" or tokens[position] == "(":
                value = value and parse_unary()
                continue
            break
        return value

    def parse_unary():
        nonlocal position
        if position >= len(tokens):
            return False
        token = tokens[position]
        if token.casefold() == "not":
            position += 1
            return not parse_unary()
        if token == "(":
            position += 1
            value = parse_or()
            if position < len(tokens) and tokens[position] == ")":
                position += 1
            return value
        if token == ")":
            position += 1
            return False
        position += 1
        term = token[1:-1] if len(token) >= 2 and token.startswith('"') and token.endswith('"') else token
        return term.casefold() in haystack

    return parse_or() and position == len(tokens)

READ_ROLES = (Role.admin, Role.recruiter, Role.hiring_manager, Role.interviewer)
WRITE_ROLES = (Role.admin, Role.recruiter)


@app.post("/admin/public-media/upload", response_class=JSONResponse)
async def upload_public_media(
    file: UploadFile = File(...),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    """Upload a careers-site/public asset to Cloudinary, never a private candidate document."""
    content = await file.read(MAX_DOCUMENT_SIZE_BYTES + 1)
    if len(content) > MAX_DOCUMENT_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Public media upload must be 5 MB or smaller.")
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded public media file is empty.")
    content_type = (file.content_type or "").lower()
    if not (content_type.startswith("image/") or content_type.startswith("video/") or content_type == "application/pdf"):
        raise HTTPException(status_code=400, detail="Public media supports images, videos, and PDFs.")
    try:
        result = public_media_service.upload_public(content, file.filename or "public-asset", content_type)
    except PublicMediaError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
     return {"status": "success", "storage": "cloudinary", "asset": result}

@app.get("/recruiting-users", response_model=list[UserRead])
def list_recruiting_users(
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    return db.scalars(
        select(User)
        .where(User.organization_id == user.organization_id, User.is_active.is_(True))
        .order_by(User.full_name.asc())
    ).all()




@app.post("/jobs", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def create_job(
    request: JobCreate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    payload = request.model_dump()
    responsibilities = payload.pop("responsibilities", [])
    job = Job(**payload, organization_id=user.organization_id, created_by_id=user.id)
    db.add(job)
    db.flush()
    job.jd_analysis = matching_service.analyze_job(job)
    if responsibilities:
        job.jd_analysis["responsibilities"] = responsibilities
    job.embedding = None
    ensure_job_stages(db, job)
    record_audit(db, user, "job.created", "job", job.id, after={"title": job.title, "status": job.status})
    db.commit()
    db.refresh(job)
    return job


@app.post("/jobs/from-url", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_job_from_url(
    url: str = Form(...),
    title: str | None = Form(default=None),
    department: str | None = Form(default=None),
    location: str | None = Form(default=None),
    employment_type: str | None = Form(default=None),
    work_mode: str | None = Form(default=None),
    status_value: str = Form(default="open"),
    minimum_experience_years: int | None = Form(default=None),
    fresher_allowed: bool | None = Form(default=None),
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    input_url, markdown_title = _clean_job_link(url)
    source_url, page_title, page = _fetch_job_page(input_url or url)
    effective_title = (title or markdown_title or page_title or "Imported job").strip()[:200]
    analysis = matching_service.parse_job_description(effective_title, page["description"], location or page.get("location"), use_llm=False)
    job = Job(
        organization_id=user.organization_id,
        created_by_id=user.id,
        title=effective_title,
        description=page["description"],
        department=department.strip() if department else None,
        location=(location.strip() if location else page.get("location")),
        employment_type=(employment_type.strip() if employment_type else page.get("employment_type")),
        work_mode=work_mode if work_mode in {"remote", "hybrid", "onsite"} else _infer_work_mode(page["description"]),
        status=status_value if status_value in {"draft", "open", "paused", "closed"} else "open",
        required_skills=list(dict.fromkeys(analysis.get("required_skills", []))),
        minimum_experience_years=(
            minimum_experience_years if minimum_experience_years is not None else analysis.get("minimum_experience_years")
        ),
        fresher_allowed=bool(fresher_allowed) if fresher_allowed is not None else bool(
            re.search(r"freshers?|entry[ -]?level|new graduates?|recent graduates?", page["description"], re.IGNORECASE)
            or re.search(r"\b0\s*(?:years?|yrs?)\b", page["description"], re.IGNORECASE)
        ),
        jd_analysis={**analysis, "source_url": source_url, "source": "Job URL import"},
        embedding=None,
    )
    db.add(job)
    db.flush()
    ensure_job_stages(db, job)
    record_audit(
        db,
        user,
        "job.created_from_url",
        "job",
        job.id,
        after={"title": job.title, "status": job.status, "source_url": source_url},
    )
    db.commit()
    db.refresh(job)
    return job


@app.post("/jobs/from-document/preview", response_class=JSONResponse)
async def preview_job_from_document(
    file: UploadFile = File(...),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    """Extract and normalize a JD for recruiter review without creating a job."""
    suffix, content = await _read_resume_upload(file)
    try:
        parsed = await asyncio.to_thread(
            extractor_service.extract_to_json,
            content,
            f"job{suffix}",
        )
    except DocumentExtractionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    raw_text = str(parsed.get("raw_text") or "").strip()
    if not raw_text:
        raise HTTPException(status_code=422, detail="No readable job description text was found.")

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    title = next(
        (
            line[:200]
            for line in lines
            if len(line) <= 200
            and line.casefold() not in {"job description", "job description:", "jd", "job profile"}
        ),
        Path(file.filename or "Job opening").stem.replace("_", " ").replace("-", " ").strip()[:200] or "Job opening",
    )

    analysis = matching_service.parse_job_description(title, raw_text, use_llm=False)
    skills = set(str(value).casefold() for value in analysis.get("required_skills", []))
    department_map = (
        ("Engineering", {"python", "java", "javascript", "typescript", "react", "fastapi", "django", "node.js", "sql", "aws", "docker"}),
        ("Data", {"python", "sql", "machine learning", "pandas", "numpy", "tableau", "excel"}),
        ("Design", {"figma"}),
        ("Marketing", {"seo", "google analytics", "content", "marketing"}),
        ("Product", {"product management", "product manager", "roadmap"}),
        ("Project Management", {"project management", "agile", "scrum", "jira"}),
        ("Human Resources", {"recruiting", "talent acquisition", "hr"}),
        ("Finance", {"finance", "accounting", "excel", "financial analysis"}),
    )
    department = next((name for name, markers in department_map if any(marker in skills for marker in markers)), None)

    employment_type = next(
        (
            value for value in ("Full-time", "Part-time", "Contract", "Temporary", "Internship")
            if re.search(rf"\b{re.escape(value)}\b", raw_text, re.IGNORECASE)
        ),
        "Full-time",
    )
    minimum_experience = analysis.get("minimum_experience_years")
    fresher_allowed = bool(
        re.search(r"freshers?|entry[ -]?level|new graduates?|recent graduates?", raw_text, re.IGNORECASE)
        or re.search(r"\b0\s*(?:years?|yrs?)\b", raw_text, re.IGNORECASE)
    )

    return {
        "status": "preview",
        "title": title,
        "department": department or "",
        "location": analysis.get("location") or "",
        "employment_type": employment_type,
        "work_mode": analysis.get("work_mode") or "onsite",
        "minimum_experience_years": minimum_experience,
        "fresher_allowed": fresher_allowed,
        "required_skills": analysis.get("required_skills") or [],
        "responsibilities": analysis.get("responsibilities") or [],
        "description": raw_text,
        "education": analysis.get("education"),
        "preferred_skills": analysis.get("preferred_skills") or [],
        "seniority": analysis.get("seniority"),
        "source_filename": file.filename,
        "document_extraction_engine": parsed.get("document_extraction_engine"),
        "review_required": True,
    }


@app.post("/jobs/from-document", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_job_from_document(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    department: str | None = Form(default=None),
    location: str | None = Form(default=None),
    employment_type: str | None = Form(default="Full-time"),
    work_mode: str | None = Form(default=None),
    status_value: str = Form(default="open"),
    minimum_experience_years: int | None = Form(default=None),
    fresher_allowed: bool | None = Form(default=None),
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    if status_value not in {"draft", "open", "paused", "closed"}:
        raise HTTPException(status_code=400, detail="Invalid job status.")

    suffix, content = await _read_resume_upload(file)
    try:
        parsed = await asyncio.to_thread(
        extractor_service.extract_to_json,
        content,
        f"job{suffix}",
    )
    except DocumentExtractionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    raw_text = str(parsed.get("raw_text") or "").strip()
    if not raw_text:
        raise HTTPException(status_code=422, detail="No readable job description text was found.")

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    inferred_title = next(
        (
            line[:200]
            for line in lines
            if len(line) <= 200 and line.casefold() not in {"job description", "job description:", "jd", "job profile"}
        ),
        Path(file.filename or "Job opening").stem.replace("_", " ").replace("-", " ").strip()[:200] or "Job opening",
    )
    effective_title = (title or inferred_title).strip()[:200]
    analysis = matching_service.parse_job_description(effective_title, raw_text, location)
    inferred_fresher = bool(
        re.search(r"freshers?|entry[ -]?level|new graduates?|recent graduates?", raw_text, re.IGNORECASE)
        or re.search(r"\b0\s*(?:years?|yrs?)\b", raw_text, re.IGNORECASE)
    )

    job = Job(
        organization_id=user.organization_id,
        created_by_id=user.id,
        title=effective_title,
        description=raw_text,
        department=department.strip() if department else None,
        location=(location.strip() if location else analysis.get("location")),
        employment_type=employment_type.strip() if employment_type else None,
        work_mode=work_mode if work_mode in {"remote", "hybrid", "onsite"} else _infer_work_mode(raw_text),
        status=status_value,
        required_skills=list(dict.fromkeys(analysis.get("required_skills", []))),
        minimum_experience_years=(
            minimum_experience_years
            if minimum_experience_years is not None
            else analysis.get("minimum_experience_years")
        ),
        fresher_allowed=inferred_fresher if fresher_allowed is None else bool(fresher_allowed),
        jd_analysis=analysis,
        embedding=None,
    )
    analysis["fresher_allowed"] = job.fresher_allowed
    db.add(job)
    db.flush()
    ensure_job_stages(db, job)
    record_audit(
        db,
        user,
        "job.created_from_document",
        "job",
        job.id,
        after={"title": job.title, "status": job.status, "source_file": file.filename},
    )
    db.commit()
    db.refresh(job)
    return job


@app.get("/jobs", response_model=list[JobRead])
def list_jobs(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    return list(
        db.scalars(
            select(Job)
            .where(Job.organization_id == user.organization_id)
            .order_by(Job.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    )


@app.get("/jobs/{job_id}", response_model=JobRead)
def get_job(
    job_id: int,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    return _get_org_record(db, Job, job_id, user.organization_id)


@app.patch("/jobs/{job_id}", response_model=JobRead)
def update_job(
    job_id: int,
    request: JobUpdate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    job = _get_org_record(db, Job, job_id, user.organization_id)
    before = _audit_job(job)
    updates = request.model_dump(exclude_unset=True)
    responsibilities = updates.pop("responsibilities", None)
    for field, value in updates.items():
        setattr(job, field, value)
    if set(updates) & {
        "title", "description", "location", "work_mode", "required_skills", "minimum_experience_years", "fresher_allowed"
    } or responsibilities is not None:
        job.jd_analysis = matching_service.analyze_job(job)
        if responsibilities is not None:
            job.jd_analysis["responsibilities"] = responsibilities
        job.embedding = None
    record_audit(
        db,
        user,
        "job.updated",
        "job",
        job.id,
        before=before,
        after=_audit_job(job),
    )
    db.commit()
    db.refresh(job)
    return job


@app.post("/jobs/{job_id}/archive", response_model=JobRead)
def archive_job(
    job_id: int,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    job = _get_org_record(db, Job, job_id, user.organization_id)
    before = _audit_job(job)
    job.status = "archived"
    record_audit(db, user, "job.archived", "job", job.id, before=before, after=_audit_job(job))
    db.commit()
    db.refresh(job)
    return job


@app.post("/jobs/{job_id}/analyze")
def analyze_job_description(
    job_id: int,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    job = _get_org_record(db, Job, job_id, user.organization_id)
    analysis = matching_service.analyze_job(job)
    job.jd_analysis = analysis
    vector = matching_service.embed_texts([matching_service.job_embedding_text(job)])[0]
    if vector is not None:
        job.embedding = vector
    record_audit(
        db,
        user,
        "job.jd_analyzed",
        "job",
        job.id,
        after={"jd_analysis": analysis, "embedding_ready": job.embedding is not None},
    )
    db.commit()
    return {"job_id": job.id, "jd_analysis": analysis, "embedding_ready": job.embedding is not None}


@app.post("/jobs/{job_id}/matches", response_model=list[CandidateMatchRead])
def rank_job_candidates(
    job_id: int,
    include_archived: bool = Query(default=False),
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    """
    Fast ranking path.

    Candidate/job scoring is deterministic and local. External embeddings and
    LLM summaries are intentionally excluded from the request path so the ATS
    remains responsive under normal public/admin use.
    """
    job = _get_org_record(db, Job, job_id, user.organization_id)
    if not job.jd_analysis:
        job.jd_analysis = matching_service.analyze_job(job)

    candidates = list(
        db.scalars(
            select(Candidate)
            .where(
                Candidate.organization_id == user.organization_id,
                Candidate.archived.is_(True) if include_archived else Candidate.archived.is_(False),
            )
            .order_by(Candidate.created_at.desc())
            .limit(200)
        ).all()
    )

    candidate_ids = [candidate.id for candidate in candidates]
    existing_matches = {}
    if candidate_ids:
        existing_matches = {
            match.candidate_id: match
            for match in db.scalars(
                select(CandidateJobMatch)
                .where(
                    CandidateJobMatch.organization_id == user.organization_id,
                    CandidateJobMatch.job_id == job.id,
                    CandidateJobMatch.candidate_id.in_(candidate_ids),
                )
                .options(selectinload(CandidateJobMatch.candidate))
            ).all()
        }

    results = []
    candidate_scores = []
    for candidate in candidates:
        score = matching_service.score_candidate(job, candidate)
        candidate_scores.append((candidate, score))

    # Optional second-stage reranking. The first pass remains deterministic
    # and safe when the external reranker is disabled or unavailable.
    rerank_documents = [
        {
            "candidate_id": candidate.id,
            "text": (
                f"Candidate: {candidate.first_name} {candidate.last_name}\n"
                f"Skills: {', '.join(str(v) for v in (candidate.resume_data or {}).get('skills') or [])}\n"
                f"Experience: {json.dumps((candidate.resume_data or {}).get('experience') or [], ensure_ascii=False)}\n"
                f"Education: {json.dumps((candidate.resume_data or {}).get('education') or [], ensure_ascii=False)}"
            ),
        }
        for candidate, _ in candidate_scores
    ]
    rerank_results = reranker_service.rerank(
        matching_service.job_embedding_text(job),
        rerank_documents,
        top_n=len(rerank_documents),
    )
    rerank_by_candidate = {}
    for item in rerank_results:
        index = item.get("index")
        if isinstance(index, int) and 0 <= index < len(rerank_documents):
            rerank_by_candidate[rerank_documents[index]["candidate_id"]] = round(
                float(item.get("relevance_score", 0.0)) * 100
            )

    for candidate, score in candidate_scores:
        if candidate.id in rerank_by_candidate:
            rerank_score = rerank_by_candidate[candidate.id]
            score["rerank_score"] = rerank_score
            score["model_score_before_rerank"] = score["model_score"]
            score["model_score"] = round(score["model_score"] * 0.75 + rerank_score * 0.25)
            score["rerank_mode"] = reranker_service.model
        match = existing_matches.get(candidate.id)
        if match is None:
            match = CandidateJobMatch(
                organization_id=user.organization_id,
                job_id=job.id,
                candidate_id=candidate.id,
                candidate=candidate,
            )
            db.add(match)
        else:
            match.candidate = candidate
        match.model_score = score["model_score"]
        match.score_breakdown = {
            **score["score_breakdown"],
            **({
                "rerank_score": score["rerank_score"],
                "rerank_mode": score["rerank_mode"],
                "model_score_before_rerank": score["model_score_before_rerank"],
            } if "rerank_score" in score else {}),
        }
        match.matched_skills = score["matched_skills"]
        match.skill_gaps = score["skill_gaps"]
        match.explanations = score["explanations"]
        match.semantic_mode = score["semantic_mode"]
        candidate.cv_summary = score["cv_summary"]
        results.append(match)

    db.flush()
    record_audit(
        db,
        user,
        "job.candidates_ranked",
        "job",
        job.id,
        after={"candidate_count": len(results), "mode": "fast_local", "reranker_enabled": reranker_service.configured, "reranker_model": reranker_service.model if reranker_service.configured else None, "reranked_candidate_count": len(rerank_by_candidate)},
    )
    db.commit()

    results.sort(
        key=lambda match: match.recruiter_override if match.recruiter_override is not None else match.model_score,
        reverse=True,
    )
    return [_serialize_candidate_match(match, job) for match in results]


@app.get("/jobs/{job_id}/matches", response_model=list[CandidateMatchRead])
def list_job_matches(
    job_id: int,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    job = _get_org_record(db, Job, job_id, user.organization_id)
    if not job.jd_analysis:
        job.jd_analysis = matching_service.analyze_job(job)
    matches = db.scalars(
        select(CandidateJobMatch)
        .where(
            CandidateJobMatch.organization_id == user.organization_id,
            CandidateJobMatch.job_id == job_id,
        )
        .options(selectinload(CandidateJobMatch.candidate))
    ).all()
    results = list(matches)
    results.sort(
        key=lambda match: match.recruiter_override if match.recruiter_override is not None else match.model_score,
        reverse=True,
    )
    return [_serialize_candidate_match(match, job) for match in results]


@app.get("/applications/{application_id}/fit-analysis")
def application_fit_analysis(
    application_id: int,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    application = db.scalar(
        select(Application)
        .where(
            Application.id == application_id,
            Application.organization_id == user.organization_id,
        )
        .options(selectinload(Application.job), selectinload(Application.candidate)),
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    job = application.job
    candidate = application.candidate
    if not job.jd_analysis:
        job.jd_analysis = matching_service.analyze_job(job)

    score = matching_service.score_candidate(job, candidate)
    profile = candidate.resume_data or {}
    experience = profile.get("experience") or []
    projects = profile.get("university_projects") or profile.get("projects") or []

    evidence = []
    for item in experience[:8]:
        if not isinstance(item, dict):
            continue
        role = " · ".join(str(item.get(key)).strip() for key in ("title", "company", "duration") if item.get(key))
        description = str(item.get("description") or "").strip()
        if role or description:
            evidence.append({
                "type": "experience",
                "title": role or "Experience",
                "details": description,
            })
    for project in projects[:10]:
        text_value = str(project).strip()
        if text_value:
            evidence.append({"type": "project", "title": text_value, "details": ""})

    required_skills = job.jd_analysis.get("required_skills", []) if job.jd_analysis else []
    project_text = " ".join(str(project) for project in projects).casefold()
    project_skill_matches = [
        skill for skill in required_skills
        if skill.casefold() in project_text
    ]

    pct = int(score.get("model_score", 0))
    fit = "Strong Fit" if pct >= 75 else "Potential Fit" if pct >= 50 else "Low Fit"
    final_recommendation = (
        "Strong evidence — review first" if pct >= 75
        else "Partial evidence — review highlighted gaps" if pct >= 50
        else "Limited evidence — collect more evidence"
    )
    alignment = (
        "Strong role alignment" if pct >= 75
        else "Partial role alignment" if pct >= 50
        else "Limited role alignment"
    )
    required = score.get("matched_required_skills", [])
    preferred = score.get("matched_preferred_skills", [])
    gaps = score.get("skill_gaps", [])
    experience_years = score.get("experience_years", matching_service._estimate_experience_years(experience))
    education = profile.get("highest_education") or profile.get("education") or []
    breakdown = score.get("score_breakdown", {})
    strengths = []
    if required:
        strengths.append("Required skills: " + ", ".join(required[:10]))
    if preferred:
        strengths.append("Preferred skills: " + ", ".join(preferred[:10]))
    if score.get("project_evidence", {}).get("coverage"):
        strengths.append(f"Project evidence coverage: {score['project_evidence']['coverage']}%")
    if not strengths:
        strengths.append("No strong skill evidence was identified.")
    summary = (
        f"{candidate.first_name} {candidate.last_name}".strip()
        + f" shows {fit.lower()} against {job.title} with an overall match of {pct}%. "
        + "The assessment uses resume skills, experience, education, and project evidence."
    )
    match_explanation = build_match_explanation(
        candidate_name=f"{candidate.first_name} {candidate.last_name}".strip(),
        job_title=job.title,
        match_score=pct,
        matched_required=required,
        matched_preferred=preferred,
        skill_gaps=gaps,
        experience_years=experience_years,
        required_experience_years=job.jd_analysis.get("minimum_experience_years") if job.jd_analysis else None,
        evidence=evidence,
    )
    coding_catalog = {"python", "java", "javascript", "typescript", "c++", "c#", "sql", "react", "node.js", "django", "fastapi", "rest api"}
    required_coding = [skill for skill in (job.jd_analysis or {}).get("required_skills", []) if str(skill).casefold() in coding_catalog]
    matched_coding = [skill for skill in required_coding if skill in required]
    coding_score = round(len(matched_coding) / len(required_coding) * 100) if required_coding else breakdown.get("skills", 0)
    return {
        "application_id": application.id,
        "candidate_id": candidate.id,
        "candidate_name": f"{candidate.first_name} {candidate.last_name}".strip(),
        "job_id": job.id,
        "job_title": job.title,
        "match_score": pct,
        "fit": fit,
        "recommendation": final_recommendation,
        "final_recommendation": final_recommendation,
        "summary": summary,
        "match_explanation": match_explanation,
        "strengths": strengths,
        "gaps": gaps,
        "alignment": alignment,
        "matched_skills": score["matched_skills"],
        "skill_gaps": gaps,
        "required_skills_met": required,
        "preferred_skills_met": preferred,
        "mandatory_skills_met": required,
        "mandatory_skills_missed": gaps,
        "missing_skills": gaps,
        "mandatory_skills_match_score": breakdown.get("skills", 0),
        "coding_skills_score": coding_score,
        "behavioral_skills_score": breakdown.get("experience", 0),
        "experience_score": breakdown.get("experience", 0),
        "experience_years": experience_years,
        "required_experience_years": score.get("required_experience_years"),
        "experience_years_estimate": experience_years,
        "highest_education": profile.get("highest_education"),
        "extracted_education": education,
        "education": education,
        "experience": evidence,
        "projects": [str(project).strip() for project in projects[:10] if str(project).strip()],
        "project_evidence": score.get("project_evidence", {}),
        "match_evidence": score.get("match_evidence", {}),
        "project_skill_matches": list(dict.fromkeys(project_skill_matches)),
        "explanations": score["explanations"],
        "decision_support_only": True,
        "semantic_mode": score.get("semantic_mode"),
        "note": "Job-related screening evidence only. Final hiring decisions remain with the recruiting team.",
    }


@app.patch("/candidate-matches/{match_id}/feedback", response_model=CandidateMatchRead)
def update_candidate_match_feedback(
    match_id: int,
    request: MatchFeedbackUpdate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    match = db.scalar(
        select(CandidateJobMatch)
        .where(
            CandidateJobMatch.id == match_id,
            CandidateJobMatch.organization_id == user.organization_id,
        )
        .options(selectinload(CandidateJobMatch.candidate))
    )
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")
    before = {"recruiter_override": match.recruiter_override, "recruiter_note": match.recruiter_note}
    updates = request.model_dump(exclude_unset=True)
    if "recruiter_override" in updates:
        match.recruiter_override = updates["recruiter_override"]
        match.feedback_by_id = user.id if updates["recruiter_override"] is not None else None
    if "recruiter_note" in updates:
        match.recruiter_note = updates["recruiter_note"]
    record_audit(
        db,
        user,
        "candidate_match.feedback_updated",
        "candidate_job_match",
        match.id,
        before=before,
        after={"recruiter_override": match.recruiter_override, "recruiter_note": match.recruiter_note},
    )
    db.commit()
    db.refresh(match)
    return _serialize_candidate_match(match, match.job if hasattr(match, "job") else None)


@app.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(
    job_id: int,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    job = _get_org_record(db, Job, job_id, user.organization_id)
    has_applications = db.scalar(select(Application.id).where(Application.job_id == job_id).limit(1))
    if has_applications:
        raise HTTPException(status_code=409, detail="A job with applications cannot be deleted")
    record_audit(db, user, "job.deleted", "job", job.id, before=_audit_job(job))
    db.delete(job)
    db.commit()


@app.post("/resume-processing/sync", response_class=JSONResponse)
def sync_resume_lab_candidate(
    request: ResumeLabSyncRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    """Synchronize the complete Resume Lab profile into the ATS candidate record."""
    resume = dict(request.resume_json or {})
    resume.pop("raw_text", None)

    candidate_email = str(resume.get("email") or "").strip().lower()
    if not candidate_email:
        raise HTTPException(
            status_code=422,
            detail="Resume sync requires an email address so the ATS can identify the candidate.",
        )

    first_name, last_name = _split_candidate_name(resume.get("name"))
    candidate = db.scalar(
        select(Candidate).where(
            Candidate.organization_id == user.organization_id,
            Candidate.email == candidate_email,
        )
    )

    created = candidate is None
    if candidate is None:
        candidate = Candidate(
            organization_id=user.organization_id,
            created_by_id=user.id,
            first_name=first_name,
            last_name=last_name,
            email=candidate_email,
            phone=str(resume.get("phone") or "").strip()[:50] or None,
            linkedin_url=str(resume.get("linkedin") or "").strip()[:500] or None,
            source="Resume Lab",
        )
        db.add(candidate)
        db.flush()
    else:
        if first_name:
            candidate.first_name = first_name
        if last_name:
            candidate.last_name = last_name
        if resume.get("phone"):
            candidate.phone = str(resume["phone"]).strip()[:50]
        if resume.get("linkedin"):
            candidate.linkedin_url = str(resume["linkedin"]).strip()[:500]
        candidate.source = candidate.source or "Resume Lab"

    # Preserve recruiter-entered data while updating every non-empty extracted
    # Resume Lab field. Structured resume information stays in resume_data so
    # filters, matching, candidate detail, assistant, and exports all use the
    # same canonical profile.
    existing_profile = dict(candidate.resume_data or {})
    merged_profile = dict(existing_profile)
    list_fields = (
        "skills",
        "experience",
        "education",
        "hobbies",
        "university_projects",
        "projects",
        "certifications",
        "companies",
        "job_titles",
    )
    scalar_fields = (
        "name",
        "email",
        "phone",
        "linkedin",
        "github",
        "highest_education",
        "years_of_experience",
        "notice_period",
        "current_location",
        "preferred_location",
        "work_authorization",
        "is_fresher",
        "resume_quality",
        "extraction_evidence",
        "extraction_confidence",
        "resume_intelligence_version",
        "raw_text_length",
        "document_extraction_engine",
        "document_extraction_warning",
        "resume_validation",
    )
    for field in list_fields:
        value = resume.get(field)
        if isinstance(value, list) and value:
            merged_profile[field] = value
        elif field not in merged_profile:
            merged_profile[field] = []
    for field in scalar_fields:
        value = resume.get(field)
        if value is not None and value != "":
            merged_profile[field] = value

    merged_profile["synced_from"] = "Resume Lab"
    merged_profile["synced_at"] = datetime.now(timezone.utc).isoformat()
    candidate.resume_data = merged_profile

    cv_summary = []
    if merged_profile.get("years_of_experience") is not None:
        cv_summary.append(f"{merged_profile['years_of_experience']} years of experience")
    if merged_profile.get("current_location"):
        cv_summary.append(f"Based in {merged_profile['current_location']}")
    if merged_profile.get("highest_education"):
        cv_summary.append(f"Education: {merged_profile['highest_education']}")
    skills = [str(v).strip() for v in (merged_profile.get("skills") or []) if str(v).strip()]
    if skills:
        cv_summary.append("Skills: " + ", ".join(skills[:8]))
    companies = [str(v).strip() for v in (merged_profile.get("companies") or []) if str(v).strip()]
    if companies:
        cv_summary.append("Companies: " + ", ".join(dict.fromkeys(companies[:6])))
    certifications = [str(v).strip() for v in (merged_profile.get("certifications") or []) if str(v).strip()]
    if certifications:
        cv_summary.append("Certifications: " + ", ".join(dict.fromkeys(certifications[:5])))
    candidate.cv_summary = cv_summary[:12]

    validation = merged_profile.get("resume_validation") or {}
    candidate.needs_review = validation.get("status") not in (None, "valid")

    application_id = None
    match_payload = None
    email_id = None

    if request.job_id is not None:
        job = _get_org_record(db, Job, int(request.job_id), user.organization_id)
        if job.status != "open":
            raise HTTPException(status_code=409, detail="The selected job is not open")

        stages = ensure_job_stages(db, job)
        application = db.scalar(
            select(Application).where(
                Application.organization_id == user.organization_id,
                Application.job_id == job.id,
                Application.candidate_id == candidate.id,
            )
        )
        application_created = application is None
        if application is None:
            application = Application(
                organization_id=user.organization_id,
                job_id=job.id,
                candidate_id=candidate.id,
                stage_id=stages["Applied"].id,
                status="active",
            )
            db.add(application)
            db.flush()

        if not job.jd_analysis:
            job.jd_analysis = matching_service.analyze_job(job)
        score = matching_service.score_candidate(job, candidate)
        match = db.scalar(
            select(CandidateJobMatch).where(
                CandidateJobMatch.organization_id == user.organization_id,
                CandidateJobMatch.job_id == job.id,
                CandidateJobMatch.candidate_id == candidate.id,
            )
        )
        if match is None:
            match = CandidateJobMatch(
                organization_id=user.organization_id,
                job_id=job.id,
                candidate_id=candidate.id,
            )
            db.add(match)
        match.model_score = score["model_score"]
        match.score_breakdown = score["score_breakdown"]
        match.matched_skills = score["matched_skills"]
        match.skill_gaps = score["skill_gaps"]
        match.explanations = score["explanations"]
        match.semantic_mode = score["semantic_mode"]

        application_id = application.id
        match_payload = {
            "model_score": score["model_score"],
            "matched_skills": score["matched_skills"],
            "skill_gaps": score["skill_gaps"],
            "score_breakdown": score["score_breakdown"],
        }

        if application_created:
            subject, body = _stage_email(application, "Applied", db=db)
            email_id = queue_application_email(db, application, subject, body)

    record_audit(
        db,
        user,
        "resume_lab.synced",
        "candidate",
        candidate.id,
        after={
            "created": created,
            "candidate_id": candidate.id,
            "synced_fields": sorted(merged_profile.keys()),
            "application_id": application_id,
        },
    )
    db.commit()
    db.refresh(candidate)

    background_tasks.add_task(_refresh_candidate_embedding, candidate.id, user.organization_id)
    if email_id is not None:
        background_tasks.add_task(deliver_outbox_email, email_id)

    return {
        "status": "success",
        "candidate_id": candidate.id,
        "created": created,
        "application_id": application_id,
        "match": match_payload,
        "synced_fields": sorted(merged_profile.keys()),
        "profile": merged_profile,
        "message": "Resume Lab profile synchronized across the ATS candidate record and selected application.",
    }


@app.post("/candidates/from-resume", response_model=CandidateRead, status_code=status.HTTP_201_CREATED)
async def create_candidate_from_resume(
    file: UploadFile = File(...),
    job_id: int | None = Form(default=None),
    background_tasks: BackgroundTasks = None,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    suffix, content = await _read_resume_upload(file)
    try:
        parsed = await asyncio.to_thread(
        extractor_service.extract_to_json,
        content,
        f"resume{suffix}",
    )
    except DocumentExtractionError as error:
        raise HTTPException(status_code=422, detail=str(error))

    first_name, last_name = _split_candidate_name(parsed.get("name"))
    candidate_email = str(parsed.get("email") or "").strip().lower()
    if not candidate_email:
        raise HTTPException(
            status_code=422,
            detail="The uploaded resume must contain an email address for automatic candidate creation.",
        )

    candidate = db.scalar(
        select(Candidate).where(
            Candidate.organization_id == user.organization_id,
            Candidate.email == candidate_email,
        )
    )
    if candidate is None:
        candidate = Candidate(
            organization_id=user.organization_id,
            created_by_id=user.id,
            first_name=first_name,
            last_name=last_name,
            email=candidate_email,
            phone=parsed.get("phone"),
            linkedin_url=parsed.get("linkedin"),
            source="Admin Resume Upload",
        )
        db.add(candidate)
        db.flush()
    else:
        candidate.first_name = first_name
        candidate.last_name = last_name
        candidate.phone = parsed.get("phone") or candidate.phone
        candidate.linkedin_url = parsed.get("linkedin") or candidate.linkedin_url
        candidate.source = candidate.source or "Admin Resume Upload"

    candidate.resume_data = {
        key: value for key, value in parsed.items() if key != "raw_text"
    }

    storage_key = f"{user.organization_id}/{candidate.id}/{os.urandom(16).hex()}{suffix}"
    storage_dir = Path(os.getenv("RESUME_STORAGE_DIR", "./private_uploads"))
    storage_path = storage_dir / storage_key
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_bytes(content)
    candidate.resume_storage_key = storage_key

    if job_id is not None:
        job = _get_org_record(db, Job, job_id, user.organization_id)
        if job.status != "open":
            raise HTTPException(status_code=409, detail="The selected job is not open")

        existing_application = db.scalar(
            select(Application.id).where(
                Application.job_id == job.id,
                Application.candidate_id == candidate.id,
            )
        )
        if existing_application is None:
            stages = ensure_job_stages(db, job)
            application = Application(
                organization_id=user.organization_id,
                job_id=job.id,
                candidate_id=candidate.id,
                stage_id=stages["Applied"].id,
                status="active",
            )
            db.add(application)
            db.flush()

            if not job.jd_analysis:
                job.jd_analysis = matching_service.analyze_job(job)
            score = matching_service.score_candidate(job, candidate)
            db.add(
                CandidateJobMatch(
                    organization_id=user.organization_id,
                    job_id=job.id,
                    candidate_id=candidate.id,
                    model_score=score["model_score"],
                    score_breakdown=score["score_breakdown"],
                    matched_skills=score["matched_skills"],
                    skill_gaps=score["skill_gaps"],
                    explanations=score["explanations"],
                    semantic_mode=score["semantic_mode"],
                )
            )
            subject, body = _stage_email(application, "Applied", db=db)
            email_id = queue_application_email(db, application, subject, body)

    db.commit()
    if job_id is not None and "email_id" in locals() and background_tasks is not None:
        background_tasks.add_task(deliver_outbox_email, email_id)
    db.refresh(candidate)
    if background_tasks is not None:
        background_tasks.add_task(_refresh_candidate_embedding, candidate.id, user.organization_id)
    return candidate


@app.post("/candidates", response_model=CandidateRead, status_code=status.HTTP_201_CREATED)
def create_candidate(
    request: CandidateCreate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    values = request.model_dump()
    normalized_email = str(request.email).lower()
    values["email"] = normalized_email
    normalized_phone = re.sub(r"[^0-9]", "", request.phone or "")
    duplicate = db.scalar(
        select(Candidate).where(
            Candidate.organization_id == user.organization_id,
            Candidate.email == normalized_email,
        )
    )
    if duplicate is None and normalized_phone:
        existing_candidates = db.scalars(
            select(Candidate).where(Candidate.organization_id == user.organization_id)
        ).all()
        duplicate = next(
            (
                item
                for item in existing_candidates
                if re.sub(r"[^0-9]", "", item.phone or "") == normalized_phone
            ),
            None,
        )
    if duplicate is not None:
        matched_by = "email" if duplicate.email == normalized_email else "phone"
        raise HTTPException(
            status_code=409,
            detail=f"Possible duplicate candidate found by {matched_by}: {duplicate.first_name} {duplicate.last_name} ({duplicate.email})",
        )
    if values.get("resume_data"):
        values["resume_data"] = {
            key: value for key, value in values["resume_data"].items() if key != "raw_text"
        }
    candidate = Candidate(**values, organization_id=user.organization_id, created_by_id=user.id)
    db.add(candidate)
    try:
        db.flush()
        record_audit(db, user, "candidate.created", "candidate", candidate.id, after=_audit_candidate(candidate))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This candidate already exists in your organization")
    db.refresh(candidate)
    if candidate.resume_data:
        _refresh_candidate_embedding(candidate.id, user.organization_id)
    return candidate


@app.get("/candidates/semantic-search")
def semantic_candidate_search(
    q: str = Query(min_length=2, max_length=2000),
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    """
    Semantic candidate retrieval for recruiter search.

    Embeddings are retrieval infrastructure, not a hiring score. Results are
    ranked by similarity only and should be inspected with the candidate evidence.
    """
    query_vector = matching_service.embed_texts([q])[0]
    base = select(Candidate).where(
        Candidate.organization_id == user.organization_id,
        Candidate.archived.is_(False),
    )

    if query_vector is not None and db.bind.dialect.name == "postgresql":
        rows = db.execute(
            select(
                Candidate,
                (1 - Candidate.embedding.cosine_distance(query_vector)).label("similarity"),
            )
            .where(
                Candidate.organization_id == user.organization_id,
                Candidate.archived.is_(False),
                Candidate.embedding.is_not(None),
            )
            .order_by(Candidate.embedding.cosine_distance(query_vector))
            .limit(limit)
        ).all()
        return [
            {
                "candidate_id": candidate.id,
                "name": f"{candidate.first_name} {candidate.last_name}".strip(),
                "email": candidate.email,
                "similarity": round(float(similarity) * 100, 1),
                "skills": (candidate.resume_data or {}).get("skills") or [],
                "location": (candidate.resume_data or {}).get("location"),
                "retrieval_mode": "embedding",
            }
            for candidate, similarity in rows
        ]

    # Safe fallback for local/test environments or when an embedding provider
    # is unavailable. This is retrieval only, never a hiring score.
    candidates = list(db.scalars(base.limit(250)).all())
    query_tokens = set(matching_service._tokens(q))
    ranked = []
    for candidate in candidates:
        profile = candidate.resume_data or {}
        text = matching_service.candidate_embedding_text(candidate)
        tokens = set(matching_service._tokens(text))
        overlap = len(query_tokens & tokens) / max(len(query_tokens), 1)
        if overlap > 0:
            ranked.append((overlap, candidate))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "candidate_id": candidate.id,
            "name": f"{candidate.first_name} {candidate.last_name}".strip(),
            "email": candidate.email,
            "similarity": round(score * 100, 1),
            "skills": (candidate.resume_data or {}).get("skills") or [],
            "location": (candidate.resume_data or {}).get("location"),
            "retrieval_mode": "lexical_fallback",
        }
        for score, candidate in ranked[:limit]
    ]


@app.get("/candidates", response_model=list[CandidateRead])
def list_candidates(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = None,
    skill: str | None = Query(default=None, description="Comma-separated required skills; all must match"),
    source: str | None = None,
    location: str | None = None,
    tags: str | None = Query(default=None, description="Comma-separated candidate tags; all must match"),
    stage_name: str | None = Query(default=None, pattern="^(Applied|Screening|Interview|Offer|Hired|Rejected|withdrawn)$"),
    min_experience_years: int | None = Query(default=None, ge=0, le=60),
    max_experience_years: int | None = Query(default=None, ge=0, le=60),
    notice_period: str | None = None,
    education: str | None = None,
    job_history: str | None = Query(default=None, description="Search company, title, duration, or job-history text"),
    availability: str | None = None,
    preferred_location: str | None = None,
    work_authorization: str | None = None,
    has_applied_job_id: int | None = Query(default=None, ge=1),
    include_archived: bool = False,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    base = (
        select(Candidate)
        .where(Candidate.organization_id == user.organization_id)
        .order_by(Candidate.created_at.desc())
    )
    if not include_archived:
        base = base.where(Candidate.archived.is_(False))

    has_advanced_filters = any(
        value not in (None, "")
        for value in (
            search, skill, source, location, tags, stage_name,
            min_experience_years, max_experience_years, notice_period,
            education, job_history, availability, preferred_location,
            work_authorization, has_applied_job_id,
        )
    )

    # The common candidate-list path is already ordered and paginated by SQL.
    # Avoid materializing the entire organization just to return the first page.
    if not has_advanced_filters:
        return list(db.scalars(base.offset(offset).limit(limit)).all())

    candidates = list(db.scalars(base).all())

    def haystack(candidate: Candidate) -> str:
        profile = candidate.resume_data or {}
        experience = profile.get("experience") or []
        projects = profile.get("university_projects") or profile.get("projects") or []
        return " ".join(
            [
                candidate.first_name or "",
                candidate.last_name or "",
                candidate.email or "",
                candidate.phone or "",
                candidate.source or "",
                str(profile.get("location") or profile.get("address") or ""),
                " ".join(str(value) for value in profile.get("skills") or []),
                " ".join(str(value) for value in projects),
                " ".join(str(value) for value in experience),
            ]
        ).casefold()

    candidate_stage_names: dict[int, set[str]] = {}
    stage_rows = db.execute(
        select(Application.candidate_id, Stage.name)
        .join(Stage, Application.stage_id == Stage.id)
        .where(Application.organization_id == user.organization_id)
    ).all()
    for candidate_id, stage_value in stage_rows:
        candidate_stage_names.setdefault(candidate_id, set()).add(stage_value)

    applied_candidate_ids: set[int] = set()
    if has_applied_job_id is not None:
        applied_candidate_ids = set(
            db.scalars(
                select(Application.candidate_id).where(
                    Application.organization_id == user.organization_id,
                    Application.job_id == has_applied_job_id,
                )
            ).all()
        )

    search_texts = [value for value in (notice_period, education, job_history, availability, preferred_location, work_authorization) if value]
    required_skills = [value.strip().casefold() for value in (skill or "").split(",") if value.strip()]
    required_tags = [value.strip().casefold() for value in (tags or "").split(",") if value.strip()]

    filtered = []
    for candidate in candidates:
        profile = candidate.resume_data or {}
        content = haystack(candidate)

        if search and not _candidate_search_matches(content, search):
            continue
        if required_skills:
            candidate_skill_values = [str(value).casefold() for value in profile.get("skills") or []]
            if not all(
                any(required == current or required in current for current in candidate_skill_values)
                for required in required_skills
            ):
                continue
        if source and source.casefold() not in (candidate.source or "").casefold():
            continue
        if required_tags:
            candidate_tag_values = [str(value).casefold() for value in (candidate.tags or [])]
            if not all(any(req == item or req in item for item in candidate_tag_values) for req in required_tags):
                continue
        if location:
            candidate_location = str(profile.get("location") or profile.get("address") or "")
            if location.casefold() not in candidate_location.casefold():
                continue
        estimated = matching_service._estimate_experience_years(profile.get("experience") or [])
        if min_experience_years is not None and estimated < min_experience_years:
            continue
        if max_experience_years is not None and estimated > max_experience_years:
            continue
        if stage_name:
            stage_values = candidate_stage_names.get(candidate.id, set())
            if stage_name.casefold() not in {value.casefold() for value in stage_values}:
                continue
        if search_texts:
            profile_lower = json.dumps(profile, ensure_ascii=False).casefold()
            if any(query_value.casefold() not in profile_lower for query_value in search_texts):
                continue
        if has_applied_job_id is not None and candidate.id not in applied_candidate_ids:
            continue
        filtered.append(candidate)

    return filtered[offset : offset + limit]


@app.get("/candidates/duplicates")
def find_candidate_duplicates(
    email: str | None = None,
    phone: str | None = None,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    normalized_email = email.strip().lower() if email else None
    normalized_phone = re.sub(r"[^0-9]", "", phone or "")
    candidates = db.scalars(
        select(Candidate)
        .where(Candidate.organization_id == user.organization_id)
        .order_by(Candidate.created_at.desc())
        .limit(500)
    ).all()
    results = []
    for candidate in candidates:
        email_match = normalized_email and candidate.email.lower() == normalized_email
        phone_match = normalized_phone and re.sub(r"[^0-9]", "", candidate.phone or "") == normalized_phone
        if email_match or phone_match:
            results.append(
                {
                    "id": candidate.id,
                    "first_name": candidate.first_name,
                    "last_name": candidate.last_name,
                    "email": candidate.email,
                    "phone": candidate.phone,
                    "source": candidate.source,
                    "matched_by": "email" if email_match else "phone",
                }
            )
    return results[:10]



@app.get("/email-templates")
def get_email_templates(
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    organization = db.get(Organization, user.organization_id)
    custom = organization.email_templates if organization and organization.email_templates else {}
    labels = ["Applied", "Screening", "Interview", "Offer", "Hired", "Rejected", "Interview Reminder 24h", "Interview Reminder 1h"]
    merged = dict(DEFAULT_EMAIL_TEMPLATES)
    merged["Interview Reminder 24h"] = REMINDER_EMAIL_TEMPLATES["24h"]
    merged["Interview Reminder 1h"] = REMINDER_EMAIL_TEMPLATES["1h"]
    return {
        label: custom.get(label) or merged.get(label) or {}
        for label in labels
    }


@app.get("/email-templates/preview")
def preview_email_template(
    template_name: str = Query(..., min_length=1, max_length=100),
    application_id: int | None = None,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    labels = {"Applied", "Screening", "Interview", "Offer", "Hired", "Rejected", "Interview Reminder 24h", "Interview Reminder 1h"}
    if template_name not in labels:
        raise HTTPException(status_code=400, detail="Unknown email template")
    organization = db.get(Organization, user.organization_id)
    custom = organization.email_templates if organization and organization.email_templates else {}
    defaults = dict(DEFAULT_EMAIL_TEMPLATES)
    defaults["Interview Reminder 24h"] = REMINDER_EMAIL_TEMPLATES["24h"]
    defaults["Interview Reminder 1h"] = REMINDER_EMAIL_TEMPLATES["1h"]
    template = custom.get(template_name) or defaults.get(template_name)
    if not template:
        raise HTTPException(status_code=404, detail="Email template not found")

    candidate_name = "Candidate"
    job_title = "Sample role"
    interview_values = {
        "interview_date": "01 October 2026",
        "interview_time": "10:00 AM IST",
        "interview_duration": "60",
        "interview_mode": "Online",
        "meeting_link": "https://example.com/interview",
        "interview_location": "Blupace Tech office",
    }
    if application_id is not None:
        application = _get_org_record(db, Application, application_id, user.organization_id)
        candidate_name = application.candidate.first_name or "Candidate"
        job_title = application.job.title
        interview_values["interview_date"] = application.updated_at.strftime("%d %B %Y") if application.updated_at else interview_values["interview_date"]

    values = {
        "candidate_name": candidate_name,
        "job_title": job_title,
        **interview_values,
        "candidate_portal_url": "https://bluepace-ats-frontend.onrender.com/?portal=preview",
        "company_name": "Blupace Tech",
    }
    subject, body = _render_email_template(template, values)
    return {
        "template_name": template_name,
        "subject": subject,
        "body": body,
        "is_custom": bool(custom.get(template_name)),
    }


@app.post("/email-templates/test")
def send_email_template_test(
    request: EmailTemplateTestRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    labels = {"Applied", "Screening", "Interview", "Offer", "Hired", "Rejected", "Interview Reminder 24h", "Interview Reminder 1h"}
    if request.template_name not in labels:
        raise HTTPException(status_code=400, detail="Unknown email template")
    organization = db.get(Organization, user.organization_id)
    custom = organization.email_templates if organization and organization.email_templates else {}
    defaults = dict(DEFAULT_EMAIL_TEMPLATES)
    defaults["Interview Reminder 24h"] = REMINDER_EMAIL_TEMPLATES["24h"]
    defaults["Interview Reminder 1h"] = REMINDER_EMAIL_TEMPLATES["1h"]
    template = custom.get(request.template_name) or defaults.get(request.template_name)
    if not template:
        raise HTTPException(status_code=404, detail="Email template not found")

    values = {
        "candidate_name": "Test Candidate",
        "job_title": "Sample role",
        "interview_date": "01 October 2026",
        "interview_time": "10:00 AM IST",
        "interview_duration": "60",
        "interview_mode": "Online",
        "meeting_link": "https://example.com/interview",
        "interview_location": "Blupace Tech office",
        "candidate_portal_url": "https://bluepace-ats-frontend.onrender.com/?portal=preview",
        "company_name": "Blupace Tech",
    }
    subject, body = _render_email_template(template, values)
    email = Email(
        organization_id=user.organization_id,
        application_id=None,
        recipient=request.recipient.strip(),
        subject=subject,
        body=body,
        status="pending",
    )
    db.add(email)
    db.flush()
    record_audit(db, user, "email.template_test_sent", "organization", organization.id, after={"template_name": request.template_name, "recipient": request.recipient.strip()})
    db.commit()
    background_tasks.add_task(deliver_outbox_email, email.id)
    return {"status": "queued", "email_id": email.id, "recipient": email.recipient, "subject": email.subject}


@app.patch("/email-templates")
def update_email_templates(
    request: EmailTemplateUpdate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    organization = db.get(Organization, user.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    allowed = {"Applied", "Screening", "Interview", "Offer", "Hired", "Rejected", "Interview Reminder 24h", "Interview Reminder 1h"}
    current = organization.email_templates if organization.email_templates else {}
    merged = dict(current)
    for name, template in request.templates.items():
        if name in allowed:
            merged[name] = {"subject": template.subject, "body": template.body}
    organization.email_templates = merged
    record_audit(db, user, "email.templates_updated", "organization", organization.id, after={"templates": sorted(request.templates.keys())})
    db.commit()
    return get_email_templates(user=user, db=db)


@app.get("/applications/{application_id}/portal-link")
def application_portal_link(
    application_id: int,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    application = _get_org_record(db, Application, application_id, user.organization_id)
    token = create_candidate_portal_token(application.id)
    return {"url": f"{DEPLOYED_FRONTEND_ORIGIN}?portal={urllib.parse.quote(token)}", "application_id": application.id}


@app.get("/public/application/{token}")
def public_application_status(token: str, db: Session = Depends(get_db)):
    try:
        application_id = decode_candidate_portal_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="This candidate portal link is invalid or expired.")
    application = db.scalar(
        select(Application)
        .where(Application.id == application_id)
        .options(selectinload(Application.job), selectinload(Application.candidate), selectinload(Application.stage))
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    interviews = db.scalars(
        select(Interview)
        .where(Interview.application_id == application.id)
        .order_by(Interview.starts_at.desc())
    ).all()
    return {
        "application_id": application.id,
        "candidate_name": f"{application.candidate.first_name} {application.candidate.last_name}".strip(),
        "job_title": application.job.title,
        "stage_name": application.stage.name if application.stage else "Applied",
        "status": application.status,
        "applied_at": application.applied_at,
        "interviews": [
            {
                "id": interview.id,
                "starts_at": interview.starts_at,
                "duration_minutes": interview.duration_minutes,
                "mode": interview.mode,
                "location": interview.location,
                "meeting_url": interview.meeting_url,
                "status": interview.status,
            }
            for interview in interviews
        ],
    }


@app.get("/applications/{application_id}/scorecard", response_model=list[ScorecardRead])
def get_application_scorecards(
    application_id: int,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    application = _get_org_record(db, Application, application_id, user.organization_id)
    return db.scalars(
        select(Scorecard)
        .where(Scorecard.application_id == application.id)
        .order_by(Scorecard.submitted_at.desc())
    ).all()


@app.post("/applications/{application_id}/scorecard", response_model=ScorecardRead)
def submit_application_scorecard(
    application_id: int,
    request: ScorecardCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_roles(Role.admin, Role.recruiter, Role.interviewer)),
    db: Session = Depends(get_db),
):
    application = _get_org_record(db, Application, application_id, user.organization_id)
    was_complete = scorecards_complete(db, application.id)
    scorecard = db.scalar(
        select(Scorecard)
        .where(
            Scorecard.application_id == application.id,
            Scorecard.interviewer_id == user.id,
        )
        .order_by(Scorecard.id.desc())
        .limit(1)
    )
    if scorecard is None:
        scorecard = Scorecard(application_id=application.id, interviewer_id=user.id)
        db.add(scorecard)
    scorecard.ratings = request.ratings
    scorecard.recommendation = request.recommendation
    scorecard.submitted_at = datetime.now(timezone.utc)
    record_audit(
        db,
        user,
        "interview.scorecard_submitted",
        "application",
        application.id,
        after={"recommendation": request.recommendation, "ratings": request.ratings},
    )
    email_ids = run_scorecard_automations(db, application) if not was_complete else []
    db.commit()
    db.refresh(scorecard)
    for email_id in email_ids:
        background_tasks.add_task(deliver_outbox_email, email_id)
    return scorecard


@app.get("/analytics")
def recruitment_analytics(
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    # Analytics used to materialize every Application + Candidate + Job + Stage
    # relationship. For large ATS datasets that was unnecessarily expensive.
    # Fetch only the four scalar fields needed for the dashboard instead.
    rows = db.execute(
        select(
            Stage.name,
            Candidate.source,
            Application.applied_at,
            Application.updated_at,
        )
        .select_from(Application)
        .outerjoin(Stage, Stage.id == Application.stage_id)
        .join(Candidate, Candidate.id == Application.candidate_id)
        .where(Application.organization_id == user.organization_id)
    ).all()

    stage_counts = {stage: 0 for stage in PIPELINE_STAGES}
    source_counts = {}
    total_days_sum = 0.0
    total_days_count = 0
    hired_days_sum = 0.0
    hired_days_count = 0

    for stage_name, source, applied_at, updated_at in rows:
        stage = stage_name or "Applied"
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
        source_name = source or "Unknown"
        source_counts[source_name] = source_counts.get(source_name, 0) + 1
        if applied_at and updated_at:
            days = max(0.0, (updated_at - applied_at).total_seconds() / 86400)
            total_days_sum += days
            total_days_count += 1
            if stage == "Hired":
                hired_days_sum += days
                hired_days_count += 1

    total_applications = len(rows)
    stage_rates = {}
    previous = max(total_applications, 1)
    for stage in PIPELINE_STAGES:
        value = stage_counts.get(stage, 0)
        stage_rates[stage] = round((value / previous) * 100, 1) if previous else 0
        previous = max(value, 1)

    return {
        "total_applications": total_applications,
        "stage_counts": stage_counts,
        "stage_rates": stage_rates,
        "avg_days_in_application": round(total_days_sum / total_days_count, 1) if total_days_count else 0,
        "avg_days_to_hire": round(hired_days_sum / hired_days_count, 1) if hired_days_count else 0,
        "sources": [
            {"name": name, "count": count}
            for name, count in sorted(source_counts.items(), key=lambda item: item[1], reverse=True)
        ],
    }





@app.get("/applications/{application_id}/comparison", response_model=CandidateComparisonRead)
def compare_application_with_job(
    application_id: int,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    application = _get_org_record(db, Application, application_id, user.organization_id)
    job = application.job
    candidate = application.candidate
    analysis = job.jd_analysis or matching_service.analyze_job(job)
    if not job.jd_analysis:
        job.jd_analysis = analysis
        db.commit()
    score = matching_service.score_candidate(job, candidate)
    profile = candidate.resume_data or {}
    candidate_skills = {str(value).casefold(): str(value) for value in profile.get("skills") or []}
    required = analysis.get("required_skills") or job.required_skills or []
    matched = [skill for skill in required if str(skill).casefold() in candidate_skills]
    missing = [skill for skill in required if str(skill).casefold() not in candidate_skills]
    experience = matching_service._estimate_experience_years(profile.get("experience") or [])
    education = analysis.get("education") or "Not specified"
    education_evidence = []
    for item in profile.get("education") or []:
        evidence = " · ".join(str(item.get(key)) for key in ("degree", "university", "graduation_year") if item.get(key))
        if evidence:
            education_evidence.append(evidence)
    projects = [str(item).strip() for item in (profile.get("university_projects") or profile.get("projects") or []) if str(item).strip()]
    gaps = list(missing)
    minimum = analysis.get("minimum_experience_years")
    if minimum is not None and experience < minimum:
        gaps.append(f"Experience below requested {minimum}+ years")
    return {
        "application_id": application.id,
        "job_title": job.title,
        "score": score["model_score"],
        "matched_skills": matched,
        "missing_skills": missing,
        "experience_required": minimum,
        "experience_estimated": experience,
        "education_requirement": education,
        "education_evidence": education_evidence,
        "project_evidence": projects[:12],
        "gaps": gaps,
    }


@app.get("/applications/{application_id}/notes", response_model=list[NoteRead])
def get_application_notes(
    application_id: int,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    application = _get_org_record(db, Application, application_id, user.organization_id)
    rows = db.execute(
        select(Note, User.full_name)
        .join(User, User.id == Note.author_id)
        .where(Note.application_id == application.id, Note.organization_id == user.organization_id)
        .order_by(Note.created_at.desc())
    ).all()
    return [
        {
            "id": note.id,
            "application_id": note.application_id,
            "author_id": note.author_id,
            "author_name": author_name,
            "body": note.body,
            "created_at": note.created_at,
        }
        for note, author_name in rows
    ]


@app.post("/applications/{application_id}/notes", response_model=NoteRead)
def add_application_note(
    application_id: int,
    request: NoteCreate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    application = _get_org_record(db, Application, application_id, user.organization_id)
    note = Note(
        organization_id=user.organization_id,
        application_id=application.id,
        author_id=user.id,
        body=request.body.strip(),
    )
    db.add(note)
    record_audit(db, user, "application.note_added", "application", application.id, after={"note": note.body[:200]})
    db.commit()
    db.refresh(note)
    return {
        "id": note.id,
        "application_id": note.application_id,
        "author_id": note.author_id,
        "author_name": user.full_name,
        "body": note.body,
        "created_at": note.created_at,
    }


@app.get("/talent-pools", response_model=list[TalentPoolRead])
def list_talent_pools(
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    pools = db.scalars(select(TalentPool).where(TalentPool.organization_id == user.organization_id).order_by(TalentPool.created_at.desc())).all()
    return [
        {
            "id": pool.id,
            "name": pool.name,
            "description": pool.description,
            "candidate_count": db.scalar(select(func.count(TalentPoolMembership.id)).where(TalentPoolMembership.pool_id == pool.id)) or 0,
            "created_at": pool.created_at,
        }
        for pool in pools
    ]


@app.post("/talent-pools", response_model=TalentPoolRead)
def create_talent_pool(
    request: TalentPoolCreate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    pool = TalentPool(
        organization_id=user.organization_id,
        name=request.name.strip(),
        description=request.description.strip() if request.description else None,
        created_by_id=user.id,
    )
    db.add(pool)
    record_audit(db, user, "talent_pool.created", "talent_pool", 0, after={"name": pool.name})
    db.commit()
    db.refresh(pool)
    return {"id": pool.id, "name": pool.name, "description": pool.description, "candidate_count": 0, "created_at": pool.created_at}


@app.get("/talent-pools/{pool_id}/candidates")
def list_talent_pool_candidates(
    pool_id: int,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    pool = _get_org_record(db, TalentPool, pool_id, user.organization_id)
    rows = db.execute(
        select(Candidate, TalentPoolMembership.created_at)
        .join(TalentPoolMembership, TalentPoolMembership.candidate_id == Candidate.id)
        .where(TalentPoolMembership.pool_id == pool.id)
        .order_by(TalentPoolMembership.created_at.desc())
    ).all()
    return [
        {
            "id": candidate.id,
            "first_name": candidate.first_name,
            "last_name": candidate.last_name,
            "email": candidate.email,
            "phone": candidate.phone,
            "source": candidate.source,
            "skills": (candidate.resume_data or {}).get("skills", [])[:20],
            "added_at": added_at,
        }
        for candidate, added_at in rows
    ]


@app.post("/talent-pools/{pool_id}/candidates")
def add_candidate_to_talent_pool(
    pool_id: int,
    request: TalentPoolCandidateRequest,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    pool = _get_org_record(db, TalentPool, pool_id, user.organization_id)
    candidate = _get_org_record(db, Candidate, request.candidate_id, user.organization_id)
    existing = db.scalar(select(TalentPoolMembership).where(TalentPoolMembership.pool_id == pool.id, TalentPoolMembership.candidate_id == candidate.id))
    if existing:
        return {"status": "already_member", "candidate_id": candidate.id}
    membership = TalentPoolMembership(pool_id=pool.id, candidate_id=candidate.id, added_by_id=user.id)
    db.add(membership)
    db.flush()
    record_audit(db, user, "talent_pool.candidate_added", "talent_pool", pool.id, after={"candidate_id": candidate.id})
    db.commit()
    return {"status": "added", "candidate_id": candidate.id}


@app.delete("/talent-pools/{pool_id}/candidates/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_candidate_from_talent_pool(
    pool_id: int,
    candidate_id: int,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    pool = _get_org_record(db, TalentPool, pool_id, user.organization_id)
    membership = db.scalar(select(TalentPoolMembership).where(TalentPoolMembership.pool_id == pool.id, TalentPoolMembership.candidate_id == candidate_id))
    if membership is None:
        raise HTTPException(status_code=404, detail="Candidate is not in this talent pool")
    db.delete(membership)
    record_audit(db, user, "talent_pool.candidate_removed", "talent_pool", pool.id, after={"candidate_id": candidate_id})
    db.commit()


@app.post("/applications/{application_id}/interviews", response_model=InterviewRead)
def create_interview_round(
    application_id: int,
    request: InterviewCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    application = _get_org_record(db, Application, application_id, user.organization_id)
    if request.starts_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="Interview date and time must include a timezone.")
    if request.mode == "offline" and not request.location:
        raise HTTPException(status_code=422, detail="Interview location is required for offline interviews.")
    if request.mode == "online" and not request.meeting_url:
        raise HTTPException(status_code=422, detail="Meeting link is required for an online interview.")
    round_number = (db.scalar(select(func.max(Interview.round_number)).where(Interview.application_id == application.id)) or 0) + 1
    interviewer_ids = list(dict.fromkeys(request.interviewer_ids or [application.assigned_interviewer_id or user.id]))
    if not interviewer_ids: interviewer_ids = [user.id]
    members = db.scalars(select(User).where(User.id.in_(interviewer_ids), User.organization_id == user.organization_id, User.is_active.is_(True))).all()
    if len(members) != len(interviewer_ids): raise HTTPException(422, "One or more interviewers are not active members of this organization")
    round_type = request.round_type
    interview = Interview(
        application_id=application.id,
        interviewer_id=interviewer_ids[0],
        starts_at=request.starts_at,
        duration_minutes=request.duration_minutes,
        status="scheduled",
        mode=request.mode,
        location=request.location,
        meeting_url=request.meeting_url,
        round_name=request.round_name,
        round_type=request.round_type,
        round_number=request.round_number if request.round_number else round_number,
        feedback_deadline=request.feedback_deadline,
    )
    db.add(interview)
    db.flush()
    for interviewer_id in interviewer_ids:
        db.add(InterviewParticipant(interview_id=interview.id, user_id=interviewer_id))
        if not db.scalar(select(Scorecard).where(Scorecard.application_id == application.id, Scorecard.interviewer_id == interviewer_id)):
            db.add(Scorecard(application_id=application.id, interviewer_id=interviewer_id))
    application.stage_id = ensure_job_stages(db, application.job)["Interview"].id
    application.status = "active"
    db.flush()
    subject, body = _stage_email(
        application,
        "Interview",
        db=db,
        interview_starts_at=request.starts_at,
        interview_duration_minutes=request.duration_minutes,
        interview_mode=request.mode,
        interview_location=request.location,
        interview_meeting_url=request.meeting_url,
        interview_id=interview.id,
    )
    calendar_bytes = _interview_ics(interview, application).encode("utf-8")
    email_id = queue_application_email(
        db,
        application,
        subject,
        body,
        attachment_filename=f"blupace-interview-{interview.id}.ics",
        attachment_content=base64.b64encode(calendar_bytes).decode("ascii"),
        attachment_content_type="text/calendar",
    )
    record_audit(db, user, "interview.round_scheduled", "application", application.id, after={"round_name": request.round_name, "round_type": request.round_type, "round_number": request.round_number if request.round_number else round_number, "interviewer_ids": interviewer_ids})
    db.commit()
    db.refresh(interview)
    background_tasks.add_task(deliver_outbox_email, email_id)
    return interview


@app.get("/interviewers/availability", response_model=list[InterviewAvailabilityRead])
def list_interviewer_availability(
    user_id: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    stmt = select(InterviewAvailability).where(InterviewAvailability.organization_id == user.organization_id)
    if user_id is not None: stmt = stmt.where(InterviewAvailability.user_id == user_id)
    if start is not None: stmt = stmt.where(InterviewAvailability.starts_at >= start)
    if end is not None: stmt = stmt.where(InterviewAvailability.ends_at <= end)
    return db.scalars(stmt.order_by(InterviewAvailability.starts_at.asc())).all()


@app.post("/interviewers/availability", response_model=InterviewAvailabilityRead)
def create_interviewer_availability(
    request: InterviewAvailabilityCreate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    if request.ends_at <= request.starts_at: raise HTTPException(422, "Availability end must be after start")
    slot = InterviewAvailability(organization_id=user.organization_id, user_id=user.id, starts_at=request.starts_at, ends_at=request.ends_at, note=request.note)
    db.add(slot); db.commit(); db.refresh(slot)
    return slot


@app.get("/interviewer-dashboard")
def interviewer_dashboard(
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    participant_ids = select(InterviewParticipant.interview_id).where(InterviewParticipant.user_id == user.id)
    assigned = db.scalars(select(Interview).where(Interview.id.in_(participant_ids), Interview.status == "scheduled").order_by(Interview.starts_at.asc())).all()
    legacy = db.scalars(select(Interview).where(Interview.interviewer_id == user.id, Interview.status == "scheduled")).all()
    seen = {item.id for item in assigned}
    interviews = assigned + [item for item in legacy if item.id not in seen]
    scorecards = db.scalars(select(Scorecard).where(Scorecard.interviewer_id == user.id)).all()
    pending = [s for s in scorecards if s.submitted_at is None]
    overdue = [i for i in interviews if i.feedback_deadline and i.feedback_deadline < datetime.now(timezone.utc)]
    return {
        "interviews": [{"id": i.id, "application_id": i.application_id, "starts_at": i.starts_at, "duration_minutes": i.duration_minutes, "round_name": i.round_name, "round_type": getattr(i, "round_type", "technical"), "round_number": i.round_number, "status": i.status, "feedback_deadline": i.feedback_deadline} for i in interviews],
        "scorecards_pending": len(pending),
        "scorecards_overdue": len(overdue),
        "completed_scorecards": len([s for s in scorecards if s.submitted_at is not None]),
    }


@app.patch("/interviews/{interview_id}/reschedule", response_model=InterviewRead)
def reschedule_interview(
    interview_id: int,
    request: InterviewCreate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    interview = _get_org_record(db, Interview, interview_id, user.organization_id)
    if interview.status == "cancelled": raise HTTPException(409, "Cancelled interviews cannot be rescheduled")
    interview.starts_at = request.starts_at
    interview.duration_minutes = request.duration_minutes
    interview.mode = request.mode
    interview.location = request.location
    interview.meeting_url = request.meeting_url
    if request.feedback_deadline: interview.feedback_deadline = request.feedback_deadline
    interview.status = "scheduled"
    interview.reminder_24_sent = False
    interview.reminder_1h_sent = False
    record_audit(db, user, "interview.rescheduled", "interview", interview.id, after={"starts_at": request.starts_at.isoformat()})
    db.commit(); db.refresh(interview)
    return interview


@app.post("/interviews/{interview_id}/cancel")
def cancel_interview(
    interview_id: int,
    reason: str,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    interview = _get_org_record(db, Interview, interview_id, user.organization_id)
    if not reason.strip(): raise HTTPException(422, "Cancellation reason is required")
    interview.status = "cancelled"
    interview.cancellation_reason = reason.strip()
    interview.reminder_24_sent = True
    interview.reminder_1h_sent = True
    record_audit(db, user, "interview.cancelled", "interview", interview.id, after={"reason": interview.cancellation_reason})
    db.commit()
    return {"id": interview.id, "status": interview.status, "cancellation_reason": interview.cancellation_reason}


@app.get("/applications/{application_id}/interviews", response_model=list[InterviewRead])
def list_interview_rounds(
    application_id: int,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    application = _get_org_record(db, Application, application_id, user.organization_id)
    return db.scalars(select(Interview).where(Interview.application_id == application.id).order_by(Interview.round_number.asc(), Interview.starts_at.asc())).all()


@app.patch("/interviews/{interview_id}", response_model=InterviewRead)
def reschedule_interview_legacy(
    interview_id: int,
    request: InterviewCreate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    interview = _get_org_record(db, Interview, interview_id, user.organization_id)
    if interview.status == "cancelled": raise HTTPException(409, "Cancelled interviews cannot be rescheduled")
    interview.starts_at = request.starts_at
    interview.duration_minutes = request.duration_minutes
    interview.mode = request.mode
    interview.location = request.location
    interview.meeting_url = request.meeting_url
    interview.round_name = request.round_name
    interview.round_type = request.round_type
    if request.feedback_deadline is not None: interview.feedback_deadline = request.feedback_deadline
    interview.status = "scheduled"
    interview.reminder_24_sent = False
    interview.reminder_1h_sent = False
    record_audit(db, user, "interview.rescheduled", "interview", interview.id, after={"starts_at": request.starts_at.isoformat(), "round_type": request.round_type})
    db.commit(); db.refresh(interview)
    return interview


@app.patch("/interviews/{interview_id}/status")
def update_interview_status(
    interview_id: int,
    request: InterviewStatusUpdate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    interview = _get_org_record(db, Interview, interview_id, user.organization_id)
    interview.status = request.status
    interview.reminder_24_sent = True
    interview.reminder_1h_sent = True
    application = _get_org_record(db, Application, interview.application_id, user.organization_id)
    record_audit(db, user, "interview.status_changed", "interview", interview.id, after={"status": request.status})
    db.commit()
    return {"id": interview.id, "status": interview.status, "application_id": application.id}


@app.get("/applications/{application_id}/offer", response_model=OfferRead)
def get_offer(
    application_id: int,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    application = _get_org_record(db, Application, application_id, user.organization_id)
    offer = db.scalar(select(Offer).where(Offer.application_id == application.id))
    if offer is None:
        raise HTTPException(status_code=404, detail="No offer created for this application")
    return offer


@app.post("/applications/{application_id}/offer", response_model=OfferRead)
def create_or_update_offer(
    application_id: int,
    request: OfferCreate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    application = _get_org_record(db, Application, application_id, user.organization_id)
    offer = db.scalar(select(Offer).where(Offer.application_id == application.id))
    if offer is None:
        offer = Offer(
            organization_id=user.organization_id,
            application_id=application.id,
            position_title=request.position_title.strip(),
            annual_ctc=request.annual_ctc,
            currency=request.currency,
            joining_date=request.joining_date,
            offer_letter_url=request.offer_letter_url,
            notes=request.notes,
            ctc_breakdown=request.ctc_breakdown,
            benefits=request.benefits,
            probation_period=request.probation_period,
            expires_at=request.expires_at,
            status="draft",
            created_by_id=user.id,
        )
        db.add(offer)
    else:
        offer.position_title = request.position_title.strip()
        offer.annual_ctc = request.annual_ctc
        offer.currency = request.currency
        offer.joining_date = request.joining_date
        offer.offer_letter_url = request.offer_letter_url
        offer.notes = request.notes
        offer.ctc_breakdown = request.ctc_breakdown
        offer.benefits = request.benefits
        offer.probation_period = request.probation_period
        offer.expires_at = request.expires_at
        offer.revision = int(offer.revision or 1) + 1
    db.commit()
    db.refresh(offer)
    return offer


@app.patch("/applications/{application_id}/offer", response_model=OfferRead)
def update_offer(
    application_id: int,
    request: OfferUpdate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    application = _get_org_record(db, Application, application_id, user.organization_id)
    offer = db.scalar(select(Offer).where(Offer.application_id == application.id))
    if offer is None:
        raise HTTPException(status_code=404, detail="No offer created for this application")
    values = request.model_dump(exclude_unset=True)
    for field, value in values.items():
        if field == "status":
            continue
        setattr(offer, field, value)
    if values:
        offer.revision = int(offer.revision or 1) + 1
    record_audit(db, user, "offer.updated", "application", application.id, after=request.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(offer)
    return offer


@app.get("/dashboard")
def dashboard_summary(
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    org_id = user.organization_id

    jobs = db.execute(
        select(Job.id, Job.title, Job.status)
        .where(Job.organization_id == org_id)
    ).all()
    stage_rows = db.execute(
        select(Stage.name, func.count(Application.id))
        .select_from(Application)
        .outerjoin(Stage, Stage.id == Application.stage_id)
        .where(Application.organization_id == org_id)
        .group_by(Stage.name)
    ).all()
    stage_counts = {stage: 0 for stage in PIPELINE_STAGES}
    for stage_name, count in stage_rows:
        stage_counts[stage_name or "Applied"] = int(count)

    job_rows = db.execute(
        select(Job.title, func.count(Application.id))
        .select_from(Application)
        .join(Job, Job.id == Application.job_id)
        .where(Application.organization_id == org_id)
        .group_by(Job.title)
        .order_by(func.count(Application.id).desc())
        .limit(10)
    ).all()

    source_rows = db.execute(
        select(Candidate.source, func.count(Application.id))
        .select_from(Application)
        .join(Candidate, Candidate.id == Application.candidate_id)
        .where(Application.organization_id == org_id)
        .group_by(Candidate.source)
        .order_by(func.count(Application.id).desc())
        .limit(10)
    ).all()

    email_rows = db.execute(
        select(Email.status, func.count(Email.id))
        .where(Email.organization_id == org_id)
        .group_by(Email.status)
    ).all()
    email_counts = {"pending": 0, "sent": 0, "failed": 0, "other": 0}
    for status_value, count in email_rows:
        email_counts[status_value if status_value in email_counts else "other"] = int(count)

    now = datetime.now(timezone.utc)
    upcoming_rows = db.execute(
        select(
            Interview.id,
            Interview.application_id,
            Interview.starts_at,
            Interview.duration_minutes,
            Interview.mode,
            Interview.location,
            Interview.meeting_url,
            Interview.status,
            Application.candidate_id,
            Candidate.first_name,
            Candidate.last_name,
            Candidate.email,
            Job.title,
        )
        .select_from(Interview)
        .join(Application, Application.id == Interview.application_id)
        .join(Candidate, Candidate.id == Application.candidate_id)
        .join(Job, Job.id == Application.job_id)
        .where(
            Application.organization_id == org_id,
            Interview.starts_at >= now,
            Interview.status == "scheduled",
        )
        .order_by(Interview.starts_at.asc())
        .limit(12)
    ).all()
    upcoming = [
        {
            "id": row.id,
            "application_id": row.application_id,
            "candidate_id": row.candidate_id,
            "candidate_name": f"{row.first_name} {row.last_name}".strip(),
            "candidate_email": row.email,
            "job_title": row.title,
            "starts_at": row.starts_at,
            "duration_minutes": row.duration_minutes,
            "mode": row.mode,
            "location": row.location,
            "meeting_url": row.meeting_url,
            "status": row.status,
        }
        for row in upcoming_rows
    ]

    recent_rows = db.execute(
        select(
            Application.id,
            Application.candidate_id,
            Application.applied_at,
            Candidate.first_name,
            Candidate.last_name,
            Job.title,
            Stage.name,
        )
        .select_from(Application)
        .join(Candidate, Candidate.id == Application.candidate_id)
        .join(Job, Job.id == Application.job_id)
        .outerjoin(Stage, Stage.id == Application.stage_id)
        .where(Application.organization_id == org_id)
        .order_by(Application.applied_at.desc())
        .limit(10)
    ).all()

    total_applications = int(
        db.scalar(
            select(func.count(Application.id))
            .where(Application.organization_id == org_id)
        ) or 0
    )

    return {
        "metrics": {
            "open_jobs": sum(1 for job in jobs if job.status == "open"),
            "total_jobs": len(jobs),
            "total_applications": total_applications,
            "screening": stage_counts.get("Screening", 0),
            "interviews": stage_counts.get("Interview", 0),
            "offers": stage_counts.get("Offer", 0),
            "hired": stage_counts.get("Hired", 0),
            "rejected": stage_counts.get("Rejected", 0),
        },
        "stage_counts": stage_counts,
        "job_counts": [{"name": name, "count": int(count)} for name, count in job_rows],
        "source_counts": [{"name": name or "Unknown", "count": int(count)} for name, count in source_rows],
        "email_counts": email_counts,
        "upcoming_interviews": upcoming,
        "recent_applications": [
            {
                "id": row.id,
                "candidate_id": row.candidate_id,
                "candidate_name": f"{row.first_name} {row.last_name}".strip(),
                "job_title": row.title,
                "stage_name": row.name or "Applied",
                "applied_at": row.applied_at,
            }
            for row in recent_rows
        ],
    }


@app.get("/email-delivery/status")
def email_delivery_status(
    user: User = Depends(require_roles(*READ_ROLES)),
):
    provider = os.getenv("EMAIL_PROVIDER", "").strip().lower() or "smtp"
    sender = (
        os.getenv("EMAIL_FROM")
        or os.getenv("SMTP_FROM")
        or os.getenv("SMTP_USER")
        or ""
    ).strip()

    if provider == "brevo":
        missing = []
        if not os.getenv("BREVO_API_KEY", "").strip():
            missing.append("BREVO_API_KEY")
        if not sender:
            missing.append("EMAIL_FROM")
    else:
        missing = []
        if not os.getenv("SMTP_HOST", "").strip():
            missing.append("SMTP_HOST")
        if not sender:
            missing.append("SMTP_FROM or SMTP_USER")
        smtp_port = os.getenv("SMTP_PORT", "587").strip()
        try:
            int(smtp_port)
        except ValueError:
            missing.append("SMTP_PORT")

    return {
        "provider": provider,
        "configured": not missing,
        "missing": missing,
        "sender_configured": bool(sender),
    }


@app.post("/emails/{email_id}/retry")
def retry_email(
    email_id: int,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    email = _get_org_record(db, Email, email_id, user.organization_id)
    if email.status == "sent":
        raise HTTPException(status_code=409, detail="This email has already been sent.")
    email.status = "pending"
    email.error_message = None
    email.sent_at = None
    db.commit()
    background_tasks.add_task(deliver_outbox_email, email.id)
    return {
        "status": "queued",
        "email_id": email.id,
        "recipient": email.recipient,
    }


@app.get("/emails")
def list_emails(
    limit: int = Query(default=100, ge=1, le=500),
    status_value: str | None = None,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    statement = select(Email).where(Email.organization_id == user.organization_id)
    if status_value:
        statement = statement.where(Email.status == status_value)
    emails = db.scalars(statement.order_by(Email.id.desc()).limit(limit)).all()
    application_ids = {email.application_id for email in emails if email.application_id is not None}
    applications = {}
    if application_ids:
        applications = {
            application.id: application
            for application in db.scalars(
                select(Application)
                .where(
                    Application.id.in_(application_ids),
                    Application.organization_id == user.organization_id,
                )
                .options(selectinload(Application.job), selectinload(Application.candidate))
            ).all()
        }
    return [
        {
            "id": email.id,
            "application_id": email.application_id,
            "candidate_name": (
                f"{applications[email.application_id].candidate.first_name} {applications[email.application_id].candidate.last_name}".strip()
                if email.application_id in applications else "Candidate"
            ),
            "job_title": applications[email.application_id].job.title if email.application_id in applications else None,
            "recipient": email.recipient,
            "subject": email.subject,
            "status": email.status,
            "error_message": email.error_message,
            "sent_at": email.sent_at,
        }
        for email in emails
    ]


@app.get("/candidates/{candidate_id}/activity")
def candidate_activity(
    candidate_id: int,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    candidate = _get_org_record(db, Candidate, candidate_id, user.organization_id)
    applications = db.scalars(
        select(Application)
        .where(
            Application.candidate_id == candidate.id,
            Application.organization_id == user.organization_id,
        )
        .options(selectinload(Application.job), selectinload(Application.stage))
        .order_by(Application.applied_at.desc())
    ).all()
    application_ids = [application.id for application in applications]
    events = []

    if application_ids:
        for entry in db.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == user.organization_id,
                AuditLog.entity_type == "application",
                AuditLog.entity_id.in_(application_ids),
            )
            .order_by(AuditLog.created_at.desc())
            .limit(100)
        ).all():
            events.append({
                "type": "activity",
                "title": entry.action.replace(".", " · ").replace("_", " ").title(),
                "details": entry.after_data or {},
                "created_at": entry.created_at,
                "application_id": entry.entity_id,
            })

        for email in db.scalars(
            select(Email)
            .where(
                Email.organization_id == user.organization_id,
                Email.application_id.in_(application_ids),
            )
            .order_by(Email.id.desc())
            .limit(100)
        ).all():
            events.append({
                "type": "email",
                "title": email.subject,
                "details": {
                    "status": email.status,
                    "recipient": email.recipient,
                    "error_message": email.error_message,
                },
                "created_at": email.sent_at or datetime.now(timezone.utc),
                "application_id": email.application_id,
            })

        for interview in db.scalars(
            select(Interview)
            .where(Interview.application_id.in_(application_ids))
            .order_by(Interview.starts_at.desc())
            .limit(50)
        ).all():
            events.append({
                "type": "interview",
                "title": "Interview scheduled",
                "details": {
                    "starts_at": interview.starts_at,
                    "duration_minutes": interview.duration_minutes,
                    "mode": interview.mode,
                    "location": interview.location,
                    "meeting_url": interview.meeting_url,
                    "status": interview.status,
                },
                "created_at": interview.starts_at,
                "application_id": interview.application_id,
            })

    events.sort(
        key=lambda event: event.get("created_at")
        if isinstance(event.get("created_at"), datetime)
        else datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return {
        "candidate": {
            "id": candidate.id,
            "name": f"{candidate.first_name} {candidate.last_name}".strip(),
            "email": candidate.email,
            "phone": candidate.phone,
            "source": candidate.source,
        },
        "applications": [
            {
                "id": application.id,
                "job_id": application.job_id,
                "job_title": application.job.title,
                "stage_name": application.stage.name if application.stage else "Applied",
                "status": application.status,
                "applied_at": application.applied_at,
            }
            for application in applications
        ],
        "events": events[:120],
    }


@app.get("/candidates/{candidate_id}", response_model=CandidateRead)
def get_candidate(
    candidate_id: int,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    return _get_org_record(db, Candidate, candidate_id, user.organization_id)


@app.get("/candidates/{candidate_id}/collaboration", response_model=CandidateCollaborationRead)
def get_candidate_collaboration(
    candidate_id: int,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    candidate = _get_org_record(db, Candidate, candidate_id, user.organization_id)
    tags = db.scalars(select(CandidateTag).where(CandidateTag.candidate_id == candidate.id).order_by(CandidateTag.name.asc())).all()
    comments = db.scalars(
        select(CandidateComment).where(
            CandidateComment.candidate_id == candidate.id,
            CandidateComment.organization_id == user.organization_id,
        ).order_by(CandidateComment.created_at.desc())
    ).all()
    followers = db.scalars(
        select(CandidateFollower).where(
            CandidateFollower.candidate_id == candidate.id,
            CandidateFollower.organization_id == user.organization_id,
        )
    ).all()
    follower_ids = {item.user_id for item in followers}
    org_users = db.scalars(
        select(User).where(User.organization_id == user.organization_id, User.is_active.is_(True)).order_by(User.full_name.asc())
    ).all()
    owner = db.get(User, candidate.owner_id) if candidate.owner_id else None
    return {
        "tags": tags,
        "comments": [
            {
                "id": item.id,
                "body": item.body,
                "mentions": item.mentions or [],
                "author_id": item.author_id,
                "author_name": (db.get(User, item.author_id).full_name if db.get(User, item.author_id) else "Unknown"),
                "created_at": item.created_at,
            }
            for item in comments
        ],
        "followers": [
            {"user_id": member.id, "user_name": member.full_name, "following": member.id in follower_ids}
            for member in org_users
        ],
        "following": user.id in follower_ids,
        "owner_id": candidate.owner_id,
        "owner_name": owner.full_name if owner else None,
        "starred": candidate.starred,
        "needs_review": candidate.needs_review,
        "priority": candidate.priority,
    }


@app.post("/candidates/{candidate_id}/collaboration/tags", response_model=CandidateTagRead, status_code=status.HTTP_201_CREATED)
def add_candidate_tag(
    candidate_id: int,
    request: CandidateTagUpdate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    candidate = _get_org_record(db, Candidate, candidate_id, user.organization_id)
    name = request.name.strip()
    tag = db.scalar(select(CandidateTag).where(CandidateTag.candidate_id == candidate.id, func.lower(CandidateTag.name) == name.casefold()))
    if tag:
        tag.color = request.color
    else:
        tag = CandidateTag(organization_id=user.organization_id, candidate_id=candidate.id, name=name, color=request.color)
        db.add(tag)
        current = [str(value) for value in (candidate.tags or []) if str(value).casefold() != name.casefold()]
        candidate.tags = current + [name]
    db.commit()
    db.refresh(tag)
    return tag


@app.patch("/candidates/{candidate_id}/collaboration", response_model=CandidateCollaborationRead)
def update_candidate_collaboration(
    candidate_id: int,
    request: CandidateCollaborationUpdate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    candidate = _get_org_record(db, Candidate, candidate_id, user.organization_id)
    updates = request.model_dump(exclude_unset=True)
    if "owner_id" in updates:
        owner_id = updates["owner_id"]
        if owner_id is not None:
            owner = db.scalar(select(User).where(User.id == owner_id, User.organization_id == user.organization_id, User.is_active.is_(True)))
            if owner is None:
                raise HTTPException(status_code=400, detail="Owner must be an active member of your organization")
        candidate.owner_id = owner_id
    for field in ("starred", "needs_review", "priority"):
        if field in updates and updates[field] is not None:
            setattr(candidate, field, updates[field])
    db.commit()
    return get_candidate_collaboration(candidate.id, user, db)


@app.delete("/candidates/{candidate_id}/collaboration/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_candidate_tag(
    candidate_id: int,
    tag_id: int,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    candidate = _get_org_record(db, Candidate, candidate_id, user.organization_id)
    tag = db.scalar(select(CandidateTag).where(CandidateTag.id == tag_id, CandidateTag.candidate_id == candidate.id, CandidateTag.organization_id == user.organization_id))
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    candidate.tags = [value for value in (candidate.tags or []) if str(value).casefold() != tag.name.casefold()]
    db.delete(tag)
    db.commit()


@app.post("/candidates/{candidate_id}/collaboration/comments", response_model=CandidateCommentRead, status_code=status.HTTP_201_CREATED)
def add_candidate_comment(
    candidate_id: int,
    request: CandidateCommentCreate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    candidate = _get_org_record(db, Candidate, candidate_id, user.organization_id)
    mentioned_names = {match.casefold() for match in re.findall(r"@([A-Za-z][A-Za-z0-9._-]{1,99})", request.body)}
    org_users = db.scalars(select(User).where(User.organization_id == user.organization_id, User.is_active.is_(True))).all()
    mentions = [{"user_id": member.id, "user_name": member.full_name} for member in org_users if member.full_name.casefold() in mentioned_names or member.full_name.split(" ")[0].casefold() in mentioned_names]
    comment = CandidateComment(
        organization_id=user.organization_id,
        candidate_id=candidate.id,
        author_id=user.id,
        body=request.body.strip(),
        mentions=mentions,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return {"id": comment.id, "body": comment.body, "mentions": mentions, "author_id": user.id, "author_name": user.full_name, "created_at": comment.created_at}


@app.post("/candidates/{candidate_id}/collaboration/follow", response_model=CandidateFollowerRead)
def follow_candidate(
    candidate_id: int,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    candidate = _get_org_record(db, Candidate, candidate_id, user.organization_id)
    follower = db.scalar(select(CandidateFollower).where(CandidateFollower.candidate_id == candidate.id, CandidateFollower.user_id == user.id))
    if follower is None:
        db.add(CandidateFollower(organization_id=user.organization_id, candidate_id=candidate.id, user_id=user.id))
        db.commit()
    return {"user_id": user.id, "user_name": user.full_name, "following": True}


@app.delete("/candidates/{candidate_id}/collaboration/follow", status_code=status.HTTP_204_NO_CONTENT)
def unfollow_candidate(
    candidate_id: int,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    candidate = _get_org_record(db, Candidate, candidate_id, user.organization_id)
    follower = db.scalar(select(CandidateFollower).where(CandidateFollower.candidate_id == candidate.id, CandidateFollower.user_id == user.id))
    if follower:
        db.delete(follower)
        db.commit()


@app.patch("/candidates/{candidate_id}", response_model=CandidateRead)
def update_candidate(
    candidate_id: int,
    request: CandidateUpdate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    candidate = _get_org_record(db, Candidate, candidate_id, user.organization_id)
    before = _audit_candidate(candidate)
    updates = request.model_dump(exclude_unset=True)
    if "email" in updates and updates["email"] is not None:
        updates["email"] = str(updates["email"]).lower()
    if updates.get("resume_data"):
        updates["resume_data"] = {
            key: value for key, value in updates["resume_data"].items() if key != "raw_text"
        }
    for field, value in updates.items():
        setattr(candidate, field, value)
    record_audit(
        db,
        user,
        "candidate.updated",
        "candidate",
        candidate.id,
        before=before,
        after=_audit_candidate(candidate),
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This candidate already exists in your organization")
    db.refresh(candidate)
    return candidate


@app.delete("/candidates/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_candidate(
    candidate_id: int,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    candidate = _get_org_record(db, Candidate, candidate_id, user.organization_id)
    has_applications = db.scalar(
        select(Application.id).where(Application.candidate_id == candidate_id).limit(1)
    )
    if has_applications:
        raise HTTPException(status_code=409, detail="A candidate with applications cannot be deleted")
    record_audit(db, user, "candidate.deleted", "candidate", candidate.id, before=_audit_candidate(candidate))
    db.delete(candidate)
    db.commit()


@app.get("/jobs/{job_id}/stages")
def list_job_stages(
    job_id: int,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    job = _get_org_record(db, Job, job_id, user.organization_id)
    stages = ensure_job_stages(db, job)
    db.commit()
    return [
        {"id": stage.id, "name": name, "position": stage.position}
        for name, stage in sorted(stages.items(), key=lambda item: item[1].position)
    ]


@app.post("/candidates/{candidate_id}/resume", response_model=CandidateRead)
async def upload_candidate_resume(
    candidate_id: int,
    file: UploadFile = File(...),
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    candidate = _get_org_record(db, Candidate, candidate_id, user.organization_id)
    suffix, content = await _read_resume_upload(file)

    storage_key = f"{user.organization_id}/{candidate.id}/{os.urandom(16).hex()}{suffix}"
    storage_reference = private_storage.put_bytes(
        storage_key,
        content,
        file.content_type or "application/octet-stream",
    )
    try:
        parsed = extractor_service.extract_to_json(content, f"resume{suffix}")
    except Exception as error:
        private_storage.delete(storage_reference)
        raise HTTPException(status_code=422, detail=f"Resume could not be parsed: {error}")

    before = {"resume_storage_key": candidate.resume_storage_key}
    candidate.resume_storage_key = storage_reference
    candidate.resume_data = {key: value for key, value in parsed.items() if key != "raw_text"}
    if not candidate.phone and parsed.get("phone"):
        candidate.phone = parsed["phone"][:50]
    if not candidate.linkedin_url and parsed.get("linkedin"):
        candidate.linkedin_url = parsed["linkedin"][:500]
    record_audit(
        db,
        user,
        "candidate.resume_uploaded",
        "candidate",
        candidate.id,
        before=before,
        after={"resume_storage_key": storage_key, "parsed_fields": sorted(parsed.keys())},
    )
    db.commit()
    db.refresh(candidate)
    return candidate


@app.post("/applications", response_model=ApplicationRead, status_code=status.HTTP_201_CREATED)
def create_application(
    request: ApplicationCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    job = _get_org_record(db, Job, request.job_id, user.organization_id)
    candidate = _get_org_record(db, Candidate, request.candidate_id, user.organization_id)
    if job.status != "open":
        raise HTTPException(status_code=409, detail="Applications can only be created for open jobs")

    stages = ensure_job_stages(db, job)
    application = Application(
        organization_id=user.organization_id,
        job_id=job.id,
        candidate_id=candidate.id,
        stage_id=stages["Applied"].id,
        status="active",
    )
    db.add(application)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This candidate already applied to this job")
    # Fast local candidate-to-job match on application creation.
    # No external LLM or embedding call is made on this request path.
    if not job.jd_analysis:
        job.jd_analysis = matching_service.analyze_job(job)
    score = matching_service.score_candidate(job, candidate)
    match = db.scalar(
        select(CandidateJobMatch).where(
            CandidateJobMatch.organization_id == user.organization_id,
            CandidateJobMatch.job_id == job.id,
            CandidateJobMatch.candidate_id == candidate.id,
        )
    )
    if match is None:
        match = CandidateJobMatch(
            organization_id=user.organization_id,
            job_id=job.id,
            candidate_id=candidate.id,
        )
        db.add(match)
    match.model_score = score["model_score"]
    match.score_breakdown = score["score_breakdown"]
    match.matched_skills = score["matched_skills"]
    match.skill_gaps = score["skill_gaps"]
    match.explanations = score["explanations"]
    match.semantic_mode = score["semantic_mode"]

    record_audit(
        db,
        user,
        "application.created",
        "application",
        application.id,
        after={
            "job_id": job.id,
            "candidate_id": candidate.id,
            "stage_name": "Applied",
            "match_score": score["model_score"],
        },
    )
    subject, body = _stage_email(application, "Applied", db=db)
    email_ids = [queue_application_email(db, application, subject, body)]
    email_ids.extend(run_stage_automations(db, application, stages["Applied"].name))
    db.commit()
    db.refresh(application)
    for queued_id in email_ids:
        background_tasks.add_task(deliver_outbox_email, queued_id)
    return serialize_application(application)


@app.get("/applications", response_model=list[ApplicationRead])
def list_applications(
    job_id: int | None = None,
    stage_name: str | None = None,
    source: str | None = None,
    skill: str | None = None,
    search: str | None = None,
    applied_after: date | None = None,
    applied_before: date | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    statement = _application_query(
        user.organization_id,
        job_id=job_id,
        stage_name=stage_name,
        source=source,
        skill=skill,
        search=search,
        applied_after=applied_after,
        applied_before=applied_before,
    ).offset(offset).limit(limit)
    return [serialize_application(application) for application in db.scalars(statement).all()]


@app.get("/applications/export.csv")
def export_applications_csv(
    job_id: int | None = None,
    stage_name: str | None = None,
    source: str | None = None,
    skill: str | None = None,
    search: str | None = None,
    applied_after: date | None = None,
    applied_before: date | None = None,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    statement = _application_query(
        user.organization_id,
        job_id=job_id,
        stage_name=stage_name,
        source=source,
        skill=skill,
        search=search,
        applied_after=applied_after,
        applied_before=applied_before,
    ).limit(10000)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Application ID", "Job", "Candidate", "Email", "Source", "Stage", "Applied At", "Skills"])
    for application in db.scalars(statement):
        candidate = application.candidate
        skills = (candidate.resume_data or {}).get("skills", [])
        writer.writerow(
            [
                _safe_csv_value(application.id),
                _safe_csv_value(application.job.title),
                _safe_csv_value(f"{candidate.first_name} {candidate.last_name}"),
                _safe_csv_value(candidate.email),
                _safe_csv_value(candidate.source),
                _safe_csv_value(application.stage.name if application.stage else ""),
                _safe_csv_value(application.applied_at.isoformat()),
                _safe_csv_value(", ".join(skills)),
            ]
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=applications.csv"},
    )


@app.post("/applications/{application_id}/stage", response_model=ApplicationRead)
def update_application_stage(
    application_id: int,
    request: ApplicationStageUpdate,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    application = _get_org_record(db, Application, application_id, user.organization_id)
    if application.status in {*TERMINAL_STAGES.values(), "withdrawn"} and application.stage.name != request.stage_name:
        raise HTTPException(status_code=409, detail="A completed application cannot be moved")

    stages = ensure_job_stages(db, application.job)
    stage = stages[request.stage_name]
    previous_name = application.stage.name if application.stage else None
    if previous_name == request.stage_name and request.stage_name != "Interview":
        return serialize_application(application)

    if request.stage_name == "Interview":
        if request.interview_starts_at is None:
            raise HTTPException(status_code=422, detail="Interview date and time are required.")
        if request.interview_starts_at.tzinfo is None:
            raise HTTPException(status_code=422, detail="Interview date and time must include a timezone.")

        if request.interview_mode == "offline" and not request.interview_location:
            raise HTTPException(status_code=422, detail="Interview location is required for an offline interview.")
        if request.interview_mode == "online" and not request.interview_meeting_url:
            raise HTTPException(status_code=422, detail="Meeting link is required for an online interview.")

        interview = db.scalar(
            select(Interview)
            .where(Interview.application_id == application.id)
            .order_by(Interview.starts_at.desc())
            .limit(1)
        )
        if interview is None:
            interview = Interview(
                application_id=application.id,
                interviewer_id=application.assigned_interviewer_id or user.id,
                starts_at=request.interview_starts_at,
                duration_minutes=request.interview_duration_minutes,
                status="scheduled",
                mode=request.interview_mode,
                location=request.interview_location,
                meeting_url=request.interview_meeting_url,
            )
            db.add(interview)
        else:
            interview.interviewer_id = application.assigned_interviewer_id or user.id
            interview.starts_at = request.interview_starts_at
            interview.duration_minutes = request.interview_duration_minutes
            interview.status = "scheduled"
            interview.mode = request.interview_mode
            interview.location = request.interview_location
            interview.meeting_url = request.interview_meeting_url
            interview.reminder_24_sent = False
            interview.reminder_1h_sent = False

        db.flush()

    application.stage_id = stage.id
    application.status = TERMINAL_STAGES.get(stage.name, "active")
    record_audit(
        db,
        user,
        "application.stage_changed",
        "application",
        application.id,
        before={"stage_name": previous_name, "status": "active"},
        after={
            "stage_name": stage.name,
            "status": application.status,
            "interview_starts_at": request.interview_starts_at.isoformat() if request.interview_starts_at else None,
            "interview_mode": request.interview_mode if stage.name == "Interview" else None,
            "interview_location": request.interview_location if stage.name == "Interview" else None,
        },
    )

    automation_email_ids = run_stage_automations(db, application, stage.name)
    if stage_email_automation_enabled(db, application, stage.name):
        email_id = None
    else:
        subject, body = _stage_email(
            application,
            stage.name,
            db=db,
            interview_starts_at=request.interview_starts_at,
            interview_duration_minutes=request.interview_duration_minutes,
            interview_mode=request.interview_mode,
            interview_location=request.interview_location,
            interview_meeting_url=request.interview_meeting_url,
            interview_id=interview.id if request.stage_name == "Interview" else None,
        )
        if request.stage_name == "Interview" and interview is not None:
            calendar_bytes = _interview_ics(interview, application).encode("utf-8")
            email_id = queue_application_email(
                db,
                application,
                subject,
                body,
                attachment_filename=f"blupace-interview-{interview.id}.ics",
                attachment_content=base64.b64encode(calendar_bytes).decode("ascii"),
                attachment_content_type="text/calendar",
            )
        else:
            email_id = queue_application_email(db, application, subject, body)
    db.commit()
    db.refresh(application)
    if email_id is not None:
        background_tasks.add_task(deliver_outbox_email, email_id)
    for automation_email_id in automation_email_ids:
        background_tasks.add_task(deliver_outbox_email, automation_email_id)
    return serialize_application(application)


@app.post("/applications/bulk-stage", response_model=list[ApplicationRead])
def bulk_update_application_stage(
    request: BulkApplicationUpdate,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    applications = list(
        db.scalars(
            select(Application).where(
                Application.organization_id == user.organization_id,
                Application.id.in_(set(request.application_ids)),
            )
        ).all()
    )
    if len(applications) != len(set(request.application_ids)):
        raise HTTPException(status_code=404, detail="One or more applications were not found")
    email_ids = []
    for application in applications:
        if application.status in {*TERMINAL_STAGES.values(), "withdrawn"} and application.stage.name != request.stage_name:
            raise HTTPException(status_code=409, detail="Completed applications cannot be moved")
        stages = ensure_job_stages(db, application.job)
        previous_name = application.stage.name if application.stage else None
        stage = stages[request.stage_name]
        if previous_name == stage.name:
            continue
        previous_status = application.status
        application.stage_id = stage.id
        application.status = TERMINAL_STAGES.get(stage.name, "active")
        record_audit(
            db,
            user,
            "application.stage_changed",
            "application",
            application.id,
            before={"stage_name": previous_name, "status": previous_status},
            after={"stage_name": stage.name, "status": application.status},
        )
        email_ids.extend(run_stage_automations(db, application, stage.name))
        if not stage_email_automation_enabled(db, application, stage.name):
            subject, body = _stage_email(application, stage.name, db=db)
            email_ids.append(queue_application_email(db, application, subject, body))
    db.commit()
    for email_id in email_ids:
        background_tasks.add_task(deliver_outbox_email, email_id)
    refreshed = [db.get(Application, application.id) for application in applications]
    return [serialize_application(application) for application in refreshed]


@app.get("/audit-logs")
def list_audit_logs(
    entity_type: str | None = None,
    entity_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    statement = select(AuditLog).where(AuditLog.organization_id == user.organization_id)
    if entity_type:
        statement = statement.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        statement = statement.where(AuditLog.entity_id == entity_id)
    entries = db.scalars(statement.order_by(AuditLog.created_at.desc()).limit(limit)).all()
    return [
        {
            "id": entry.id,
            "actor_id": entry.actor_id,
            "action": entry.action,
            "entity_type": entry.entity_type,
            "entity_id": entry.entity_id,
            "before": entry.before_data,
            "after": entry.after_data,
            "created_at": entry.created_at,
        }
        for entry in entries
    ]


class BulkResumeFileManifest(BaseModel):
    filename: str
    size_bytes: int
    content_type: str | None = None


class BulkResumePresignRequest(BaseModel):
    batch_id: str
    files: list[BulkResumeFileManifest]


class BulkResumeFinalizeItem(BaseModel):
    filename: str
    storage_path: str
    size_bytes: int
    content_type: str | None = None


class BulkResumeFinalizeRequest(BaseModel):
    batch_id: str
    files: list[BulkResumeFinalizeItem]
    job_description: str | None = None
    job_id: int | None = None


MAX_BULK_MANIFEST_FILES = 500


def _validate_resume_batch_id(batch_id: str) -> str:
    resolved = (batch_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", resolved):
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    return resolved


def _validate_resume_manifest_file(filename: str, size_bytes: int) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"{filename}: only PDF and DOCX resumes are supported.")
    if size_bytes <= 0:
        raise HTTPException(status_code=400, detail=f"{filename}: the uploaded resume is empty.")
    if size_bytes > MAX_RESUME_SIZE_BYTES:
        raise HTTPException(status_code=413, detail=f"{filename}: resume must be 5 MB or smaller.")
    return suffix


def _resume_dispatcher_enabled() -> bool:
    return os.getenv("ENABLE_DB_RESUME_DISPATCHER", "true").strip().lower() == "true"


def _resume_background_processing_enabled() -> bool:
    return os.getenv("ENABLE_BACKGROUND_RESUME_PROCESSING", "true").strip().lower() == "true"


def _mark_resume_jobs_for_dispatch(
    jobs: list[ResumeProcessingJob],
    background_tasks: BackgroundTasks,
) -> None:
    if not jobs:
        return

    from app.services.queue_tasks import process_resume_ingest_job

    if _resume_dispatcher_enabled():
        for item in jobs:
            item.task_id = f"dispatcher:{item.id}"
        return

    if _resume_background_processing_enabled():
        for item in jobs:
            item.task_id = f"background:{item.id}"
        for item in jobs:
            background_tasks.add_task(process_resume_ingest_job.run, item.id)
        return

    # Celery is an optional external-worker mode. Keep the HTTP request free
    # from broker work for bulk intake by submitting it as one background task.
    background_tasks.add_task(_enqueue_resume_jobs_with_celery, [item.id for item in jobs])


def _enqueue_resume_jobs_with_celery(job_ids: list[int]) -> None:
    from app.services.queue_tasks import process_resume_ingest_job

    with SessionLocal() as db:
        for job_id in job_ids:
            job = db.get(ResumeProcessingJob, job_id)
            if job is None:
                continue
            try:
                task = process_resume_ingest_job.delay(job_id)
                job.task_id = task.id
            except Exception as error:
                job.status = "failed"
                job.error_message = f"Queue submission failed: {error}"[:4000]
        db.commit()


def _local_bulk_upload_signature(storage_key: str, content_type: str, expires_at: int) -> str:
    payload = f"{expires_at}:{content_type}:{storage_key}".encode("utf-8")
    return hmac.new(JWT_SECRET.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _local_bulk_upload_url(request: Request, storage_key: str, content_type: str, expires_at: int) -> str:
    signature = _local_bulk_upload_signature(storage_key, content_type, expires_at)
    query = urllib.parse.urlencode(
        {
            "storage_key": storage_key,
            "content_type": content_type,
            "expires": str(expires_at),
            "signature": signature,
        }
    )
    configured_origin = os.getenv("BACKEND_PUBLIC_ORIGIN", "").strip().rstrip("/")
    if configured_origin:
        base_url = configured_origin
    else:
        forwarded_proto = request.headers.get("x-forwarded-proto", "https").split(",")[0].strip()
        forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", "")).split(",")[0].strip()
        base_url = f"{forwarded_proto}://{forwarded_host}" if forwarded_host else str(request.base_url).rstrip("/")
    return f"{base_url}/resume-processing/batch/upload?{query}"


@app.post("/resume-processing/batch/presign", response_class=JSONResponse)
def presign_bulk_resume_uploads(
    request: Request,
    payload: BulkResumePresignRequest,
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    started = perf_counter()
    if not payload.files:
        raise HTTPException(status_code=400, detail="Add at least one resume to the batch.")
    if len(payload.files) > MAX_BULK_MANIFEST_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"Send at most {MAX_BULK_MANIFEST_FILES} resumes per upload batch.",
        )

    batch_id = _validate_resume_batch_id(payload.batch_id)
    uploads = []
    expires_at = int(datetime.now(timezone.utc).timestamp()) + 3600
    for item in payload.files:
        suffix = _validate_resume_manifest_file(item.filename, int(item.size_bytes))
        content_type = item.content_type or (
            "application/pdf" if suffix == ".pdf"
            else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        storage_key = str(
            Path(str(user.organization_id))
            / "resume_queue"
            / batch_id
            / f"{uuid4().hex}{suffix}"
        )

        storage_provider = private_storage.provider
        if storage_provider in {"r2", "b2"}:
            upload_url = private_storage.presigned_upload_url(
                storage_key,
                content_type=content_type,
                expires_in=3600,
            )
            storage_path = f"{storage_provider}://{storage_key}"
            if not upload_url:
                raise HTTPException(status_code=503, detail=f"Could not create a {storage_provider.upper()} upload URL.")
        else:
            upload_url = _local_bulk_upload_url(request, storage_key, content_type, expires_at)
            storage_path = f"local://{storage_key}"

        uploads.append(
            {
                "filename": item.filename,
                "storage_path": storage_path,
                "size_bytes": int(item.size_bytes),
                "content_type": content_type,
                "upload_url": upload_url,
                "storage_mode": storage_provider,
            }
        )

    return {
        "status": "ready",
        "batch_id": batch_id,
        "storage_mode": private_storage.provider,
        "expires_in": 3600,
        "uploads": uploads,
        "accepted_handler_ms": round((perf_counter() - started) * 1000, 2),
    }


@app.put("/resume-processing/batch/upload", response_class=JSONResponse)
async def upload_bulk_resume_to_local_storage(
    request: Request,
    storage_key: str = Query(...),
    content_type: str = Query("application/octet-stream"),
    expires: int = Query(...),
    signature: str = Query(...),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    if private_storage.provider != "local":
        raise HTTPException(status_code=409, detail="Local bulk upload is disabled while object storage is configured.")

    now = int(datetime.now(timezone.utc).timestamp())
    if expires < now:
        raise HTTPException(status_code=403, detail="Bulk upload URL has expired.")

    expected_signature = _local_bulk_upload_signature(storage_key, content_type, expires)
    if not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(status_code=403, detail="Invalid bulk upload signature.")

    expected_prefix = f"{user.organization_id}/resume_queue/"
    if not storage_key.startswith(expected_prefix):
        raise HTTPException(status_code=400, detail="Invalid bulk upload storage path.")

    content = await request.body()
    if len(content) > MAX_DOCUMENT_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Resume must be 5 MB or smaller.")
    _validate_resume_manifest_file(Path(storage_key).name, len(content))

    private_storage.put_bytes(storage_key, content, content_type=content_type)
    return {
        "status": "uploaded",
        "storage_path": f"local://{storage_key}",
        "size_bytes": len(content),
    }


@app.post("/resume-processing/batch/finalize", response_class=JSONResponse, status_code=status.HTTP_202_ACCEPTED)
def finalize_bulk_resume_uploads(
    request: BulkResumeFinalizeRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    started = perf_counter()
    if not request.files:
        raise HTTPException(status_code=400, detail="Add at least one uploaded resume to finalize.")
    if len(request.files) > MAX_BULK_MANIFEST_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"Send at most {MAX_BULK_MANIFEST_FILES} resumes per finalize request.",
        )

    batch_id = _validate_resume_batch_id(request.batch_id)
    allowed_prefixes = (
        f"r2://{user.organization_id}/resume_queue/{batch_id}/",
        f"b2://{user.organization_id}/resume_queue/{batch_id}/",
        f"local://{user.organization_id}/resume_queue/{batch_id}/",
    )

    target_job_id = None
    if request.job_id is not None:
        target_job = _get_org_record(db, Job, int(request.job_id), user.organization_id)
        if target_job.status != "open":
            raise HTTPException(status_code=409, detail="The selected job is not open")
        target_job_id = target_job.id

    storage_paths = []
    for item in request.files:
        _validate_resume_manifest_file(item.filename, int(item.size_bytes))
        path_value = str(item.storage_path or "")
        if not any(path_value.startswith(prefix) for prefix in allowed_prefixes):
            raise HTTPException(status_code=400, detail=f"{item.filename}: invalid storage path for this batch.")
        storage_paths.append(path_value)

    unique_paths = set(storage_paths)
    if len(unique_paths) != len(storage_paths):
        raise HTTPException(status_code=400, detail="A resume storage path was submitted more than once.")

    existing_paths = set(
        db.scalars(
            select(ResumeProcessingJob.storage_path).where(
                ResumeProcessingJob.organization_id == user.organization_id,
                ResumeProcessingJob.batch_id == batch_id,
                ResumeProcessingJob.storage_path.in_(storage_paths),
            )
        ).all()
    )

    jobs: list[ResumeProcessingJob] = []
    metadata = {}
    if request.job_description and request.job_description.strip():
        metadata["_job_description"] = request.job_description.strip()[:50000]
    if target_job_id is not None:
        metadata["_job_id"] = target_job_id

    for item in request.files:
        if item.storage_path in existing_paths:
            continue
        suffix = Path(item.filename or "").suffix.lower()
        content_type = item.content_type or (
            "application/pdf" if suffix == ".pdf"
            else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        job = ResumeProcessingJob(
            batch_id=batch_id,
            organization_id=user.organization_id,
            created_by_id=user.id,
            filename=item.filename or f"resume{suffix}",
            storage_path=item.storage_path,
            content_type=content_type,
            size_bytes=int(item.size_bytes),
            status="queued",
            result_data=dict(metadata) if metadata else None,
        )
        db.add(job)
        jobs.append(job)

    if jobs:
        db.flush()
        _mark_resume_jobs_for_dispatch(jobs, background_tasks)
        db.commit()
        for job in jobs:
            db.refresh(job)

    return {
        "status": "queued",
        "batch_id": batch_id,
        "accepted": len(jobs),
        "already_registered": len(request.files) - len(jobs),
        "jobs": [
            {
                "job_id": job.id,
                "filename": job.filename,
                "storage_path": job.storage_path,
                "status": job.status,
                "size_bytes": job.size_bytes,
            }
            for job in jobs
        ],
        "accepted_handler_ms": round((perf_counter() - started) * 1000, 2),
        "message": "Uploaded resumes accepted. Extraction and ATS matching are running asynchronously.",
    }


@app.post("/resume-processing/queue", response_class=JSONResponse, status_code=status.HTTP_202_ACCEPTED)
async def queue_resume_processing(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    batch_id: str | None = Form(default=None),
    job_description: str | None = Form(default=None),
    job_id: int | None = Form(default=None),
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    started = perf_counter()
    suffix, content = await _read_resume_upload(file)
    resolved_batch_id = _validate_resume_batch_id(batch_id or uuid4().hex)

    storage_key = str(Path(str(user.organization_id)) / "resume_queue" / resolved_batch_id / f"{uuid4().hex}{suffix}")
    storage_reference = private_storage.put_bytes(
        storage_key,
        content,
        file.content_type or "application/octet-stream",
    )

    target_job_id = None
    if job_id is not None:
        target_job = _get_org_record(db, Job, int(job_id), user.organization_id)
        if target_job.status != "open":
            raise HTTPException(status_code=409, detail="The selected job is not open")
        target_job_id = target_job.id

    job = ResumeProcessingJob(
        batch_id=resolved_batch_id,
        organization_id=user.organization_id,
        created_by_id=user.id,
        filename=file.filename or f"resume{suffix}",
        storage_path=storage_reference,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        status="queued",
    )
    metadata = {}
    if job_description and job_description.strip():
        metadata["_job_description"] = job_description.strip()[:50000]
    if target_job_id is not None:
        metadata["_job_id"] = target_job_id
    if metadata:
        job.result_data = metadata
    db.add(job)
    db.commit()
    db.refresh(job)

    _mark_resume_jobs_for_dispatch([job], background_tasks)
    db.commit()

    return {
        "job_id": job.id,
        "batch_id": resolved_batch_id,
        "filename": job.filename,
        "status": "queued",
        "size_bytes": job.size_bytes,
        "accepted_handler_ms": round((perf_counter() - started) * 1000, 2),
        "message": "Resume accepted. Extraction is running asynchronously.",
    }


@app.get("/resume-processing/jobs", response_class=JSONResponse)
def list_resume_processing_jobs(
    batch_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=10000),
    include_result: bool = False,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    statement = select(ResumeProcessingJob).where(
        ResumeProcessingJob.organization_id == user.organization_id,
    )
    if batch_id:
        statement = statement.where(ResumeProcessingJob.batch_id == batch_id)
    jobs = db.scalars(
        statement.order_by(ResumeProcessingJob.id.desc()).limit(limit)
    ).all()
    return [
        {
            "job_id": job.id,
            "batch_id": job.batch_id,
            "filename": job.filename,
            "status": job.status,
            "size_bytes": job.size_bytes,
            "task_id": job.task_id,
            "result": job.result_data if include_result else None,
            "error_message": job.error_message,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
        }
        for job in jobs
    ]


@app.get("/resume-processing/jobs/{job_id}", response_class=JSONResponse)
def get_resume_processing_job(
    job_id: int,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    job = _get_org_record(db, ResumeProcessingJob, job_id, user.organization_id)
    return {
        "job_id": job.id,
        "batch_id": job.batch_id,
        "filename": job.filename,
        "status": job.status,
        "size_bytes": job.size_bytes,
        "task_id": job.task_id,
        "result": job.result_data,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
    }

def build_resume_job_summary(resume: dict, job_description: str) -> dict:
    from types import SimpleNamespace

    analysis = matching_service.parse_job_description("Resume Lab Validation", job_description)
    job = SimpleNamespace(
        title="Resume Lab Validation",
        description=job_description,
        department=None,
        location=analysis.get("location"),
        employment_type=None,
        work_mode=analysis.get("work_mode") or "onsite",
        status="open",
        required_skills=analysis.get("required_skills", []),
        minimum_experience_years=analysis.get("minimum_experience_years"),
        fresher_allowed=bool(analysis.get("fresher_allowed")),
        jd_analysis=analysis,
        embedding=None,
    )
    name = str(resume.get("name") or "Applicant Candidate").strip().split()
    candidate = SimpleNamespace(
        first_name=name[0] if name else "Applicant",
        last_name=" ".join(name[1:]) if len(name) > 1 else "Candidate",
        email=resume.get("email") or "",
        phone=resume.get("phone"),
        resume_data=resume,
        embedding=None,
        cv_summary=[],
    )
    score = matching_service.score_candidate(job, candidate)
    required = score.get("matched_required_skills", [])
    preferred = score.get("matched_preferred_skills", [])
    gaps = score.get("skill_gaps", [])
    pct = int(score.get("model_score", 0))
    fit = "Strong Fit" if pct >= 75 else "Potential Fit" if pct >= 50 else "Low Fit"
    final_recommendation = (
        "Recommend for next stage" if pct >= 75
        else "Consider for next stage — review highlighted skill gaps" if pct >= 50
        else "Do not recommend for next stage based on current resume evidence"
    )
    experience_years = score.get("experience_years", resume.get("years_of_experience", 0))
    education = resume.get("highest_education") or resume.get("education") or []
    strengths = []
    if required:
        strengths.append("Required skills: " + ", ".join(required[:10]))
    if preferred:
        strengths.append("Preferred skills: " + ", ".join(preferred[:10]))
    if score.get("project_evidence", {}).get("coverage"):
        strengths.append(f"Project evidence coverage: {score['project_evidence']['coverage']}%")
    if not strengths:
        strengths.append("No strong skill evidence was identified.")
    summary = (
        f"{resume.get('name') or 'Candidate'} is a {fit.lower()} for this role with an overall match of "
        f"{pct}%. Key evidence is based on resume skills, experience, education, and project content."
    )
    breakdown = score.get("score_breakdown", {})
    coding_catalog = {"python", "java", "javascript", "typescript", "c++", "c#", "sql", "react", "node.js", "django", "fastapi", "rest api"}
    required_coding = [skill for skill in analysis.get("required_skills", []) if str(skill).casefold() in coding_catalog]
    matched_coding = [skill for skill in required_coding if skill in required]
    coding_score = round(len(matched_coding) / len(required_coding) * 100) if required_coding else breakdown.get("skills", 0)
    return {
        "match_score": pct,
        "fit": fit,
        "recommendation": final_recommendation,
        "final_recommendation": final_recommendation,
        "summary": summary,
        "strengths": strengths,
        "gaps": gaps,
        "required_skills_met": required,
        "preferred_skills_met": preferred,
        "mandatory_skills_met": required,
        "mandatory_skills_missed": gaps,
        "missing_skills": gaps,
        "mandatory_skills_match_score": breakdown.get("skills", 0),
        "coding_skills_score": coding_score,
        "behavioral_skills_score": breakdown.get("experience", 0),
        "experience_score": breakdown.get("experience", 0),
        "experience_years": experience_years,
        "required_experience_years": score.get("required_experience_years"),
        "highest_education": resume.get("highest_education"),
        "extracted_education": education,
        "education": education,
        "project_evidence": score.get("project_evidence", {}),
        "match_evidence": score.get("match_evidence", {}),
        "explanations": score.get("explanations", []),
        "decision_support_only": True,
        "semantic_mode": score.get("semantic_mode"),
    }


@app.post("/extract/", response_class=JSONResponse)
async def extract_document(
    file: UploadFile = File(...),
    job_description: str | None = Form(default=None),
):
    try:
        suffix, content = await _read_resume_upload(file)
        structured_data = extractor_service.extract_to_json(content, f"resume{suffix}")
        payload = {
            "filename": file.filename,
            "status": "success",
            "data": structured_data,
            "resume_validation": structured_data.get("resume_validation"),
        }
        # Job-fit validation is intentionally a separate request so the initial
        # Resume Lab extraction response stays fast and does not wait on matching.
        return payload
    except HTTPException:
        raise
    except DocumentExtractionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        print("\n" + "="*60)
        traceback.print_exc()
        print("="*60 + "\n")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/validate/", response_class=JSONResponse)
async def validate_resume(request: ValidationRequest):
    """
    Fast deterministic validation for Resume Lab.

    Uses the same local requirement parser and candidate scorer as the ATS
    pipeline. No network/LLM call is required.
    """
    from types import SimpleNamespace

    analysis = matching_service.parse_job_description(
        "Resume Lab Validation",
        request.job_description,
    )
    job = SimpleNamespace(
        title="Resume Lab Validation",
        description=request.job_description,
        department=None,
        location=None,
        employment_type=None,
        status="open",
        required_skills=analysis.get("required_skills", []),
        minimum_experience_years=analysis.get("minimum_experience_years"),
        fresher_allowed=bool(analysis.get("fresher_allowed")),
        jd_analysis=analysis,
        embedding=None,
    )
    resume = request.resume_json or {}
    candidate = SimpleNamespace(
        first_name=str(resume.get("name") or "").split(" ")[0] or "Applicant",
        last_name=" ".join(str(resume.get("name") or "").split(" ")[1:]) or "Candidate",
        email=resume.get("email") or "",
        resume_data=resume,
        embedding=None,
        cv_summary=[],
    )

    score = matching_service.score_candidate(job, candidate)
    required_skills = analysis.get("required_skills", [])
    matched_skills = score["matched_skills"]
    missed_skills = score["skill_gaps"]
    coding_catalog = {"python", "java", "javascript", "typescript", "c++", "c#", "sql", "react", "node.js", "django", "fastapi", "rest api"}
    required_coding = [skill for skill in required_skills if skill.casefold() in coding_catalog]
    matched_coding = [skill for skill in required_coding if skill in matched_skills]
    coding_score = round(len(matched_coding) / len(required_coding) * 100) if required_coding else score["score_breakdown"]["skills"]
    recommendation = "Yes" if score["model_score"] >= 75 else "Maybe" if score["model_score"] >= 50 else "No"

    return {
        "status": "success",
        "validation": {
            "match_score": score["model_score"],
            "mandatory_skills_match_score": score["score_breakdown"]["skills"],
            "coding_skills_score": coding_score,
            "behavioral_skills_score": score["score_breakdown"]["experience"],
            "mandatory_skills_met": matched_skills,
            "mandatory_skills_missed": missed_skills,
            "missing_skills": missed_skills,
            "summary": f"Fast local validation completed. Overall match: {score['model_score']}%.",
            "highest_education": resume.get("highest_education"),
            "extracted_education": resume.get("education") or [],
            "is_fresher": bool(resume.get("is_fresher")),
            "extracted_university_projects": resume.get("university_projects") or [],
            "extracted_hobbies": resume.get("hobbies") or [],
            "recommendation": recommendation,
            "semantic_mode": score["semantic_mode"],
        },
    }


@app.post("/validate/ai", response_class=JSONResponse)
async def validate_resume_ai(request: ValidationRequest):
    try:
        result = llm_validator.validate_resume(request.resume_json, request.job_description)
        return {"status": "success", "validation": result}
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(error))


@app.post("/extract/async/", response_class=JSONResponse)
async def extract_document_async(file: UploadFile = File(...)):
    suffix, content = await _read_resume_upload(file)
    payload = base64.b64encode(content).decode("utf-8")
    task = celery_app.send_task(
        "ats.extract_resume_task",
        kwargs={
            "file_name": f"resume{suffix}",
            "file_content_b64": payload,
            "content_type": file.content_type,
        },
    )
    return {"status": "queued", "task_id": task.id}

@app.post("/validate/async/", response_class=JSONResponse)
async def validate_resume_async(request: ValidationRequest):
    task = celery_app.send_task(
        "ats.validate_resume_task",
        kwargs={
            "resume_json": request.resume_json,
            "job_description": request.job_description,
        },
    )
    return {"status": "queued", "task_id": task.id}

@app.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    result = AsyncResult(task_id, app=celery_app)
    return {
        "task_id": task_id,
        "status": result.state,
        "result": result.result if result.ready() else None,
    }

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"message": "Welcome to the BluePace Tech ATS API."}