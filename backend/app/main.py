import base64
import csv
import io
import os
import asyncio
import re
import socket
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

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, status, Request
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from pydantic import BaseModel
from celery.result import AsyncResult
from sqlalchemy import String, cast, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from celery_app import celery_app
from app.database import SessionLocal, get_db, initialize_database
from app.models import (
    Application,
    AuditLog,
    Candidate,
    CandidateJobMatch,
    CandidateDocument,
    Email,
    Interview,
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
)
from app.schemas import (
    ApplicationCreate,
    ApplicationRead,
    ApplicationStageUpdate,
    BulkApplicationUpdate,
    CandidateMatchRead,
    CandidateCreate,
    CandidateRead,
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
    CandidateComparisonRead,
    OrganizationRegistration,
    TokenRead,
    UserCreate,
    UserRead,
)
from app.security import create_access_token, create_candidate_portal_token, decode_candidate_portal_token, get_current_user, password_hash, require_roles
from app.services.extractor import DocumentExtractionError, extractor_service
from app.services.email_notifications import deliver_outbox_email
from app.services.llm_validator import llm_validator
from app.services.matching import matching_service
from app.routers.next_features import router as next_features_router, run_scorecard_automations, run_stage_automations, stage_email_automation_enabled
from app.services.workflow import (
    PIPELINE_STAGES,
    TERMINAL_STAGES,
    ensure_job_stages,
    queue_application_email,
    record_audit,
    serialize_application,
)


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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    ensure_bootstrap_account()
    reminder_task = asyncio.create_task(interview_reminder_loop())
    try:
        yield
    finally:
        reminder_task.cancel()
        try:
            await reminder_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="BluePace Tech ATS API", version="0.4.0", lifespan=lifespan)

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
DEPLOYED_BACKEND_ORIGIN = os.getenv("BACKEND_PUBLIC_ORIGIN", "https://bluepace-ats-11.onrender.com")
MAX_RESUME_SIZE_BYTES = 10 * 1024 * 1024

def ensure_bootstrap_account() -> None:
    email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    full_name = os.getenv("BOOTSTRAP_ADMIN_NAME", "Blupace Tech Recruiting").strip() or "Blupace Tech Recruiting"
    organization_name = os.getenv("BOOTSTRAP_ORGANIZATION_NAME", "Blupace Tech").strip() or "Blupace Tech"
    if not email or not password:
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
                password_hash=password_hash.hash(password),
                role=Role.admin,
                is_active=True,
            )
            db.add(user)
        else:
            user.organization_id = organization.id
            user.full_name = full_name
            user.password_hash = password_hash.hash(password)
            user.role = Role.admin
            user.is_active = True

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
    if suffix not in {".pdf", ".docx"}:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX resumes are supported.")

    content = await file.read(MAX_RESUME_SIZE_BYTES + 1)
    if len(content) > MAX_RESUME_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Resume must be 10MB or smaller.")
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

class ValidationRequest(BaseModel):
    resume_json: dict
    job_description: str


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

def _serialize_candidate_match(match: CandidateJobMatch) -> dict:
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
        "score_breakdown": match.score_breakdown or {},
        "matched_skills": match.matched_skills or [],
        "skill_gaps": match.skill_gaps or [],
        "explanations": match.explanations or [],
        "semantic_mode": match.semantic_mode,
        "cv_summary": match.candidate.cv_summary or [],
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


@app.post("/public/jobs/{job_id}/apply")
async def public_apply(
    job_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    full_name: str | None = Form(default=None),
    email: str | None = Form(default=None),
    phone: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
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

    suffix, content = await _read_resume_upload(file)
    try:
        parsed = extractor_service.extract_to_json(content, f"resume{suffix}")
    except DocumentExtractionError as error:
        raise HTTPException(status_code=422, detail=str(error))

    candidate_name = full_name or parsed.get("name")
    first_name, last_name = _split_candidate_name(candidate_name)
    candidate_email = (email or parsed.get("email") or "").strip().lower()
    if not candidate_email:
        raise HTTPException(status_code=422, detail="Email is required either in the form or the resume")
    candidate_phone = (phone or parsed.get("phone") or "").strip() or None

    # This application path is deliberately local-only for speed: no LLM parsing,
    # no embeddings, and no AI summary generation are placed on the request path.
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
        )
        db.add(candidate)
        db.flush()
    else:
        candidate.first_name = first_name
        candidate.last_name = last_name
        candidate.phone = candidate_phone or candidate.phone
        candidate.source = candidate.source or "Public Career Portal"

    candidate.resume_data = {
        key: value for key, value in parsed.items() if key != "raw_text"
    }

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
    storage_dir = Path(os.getenv("RESUME_STORAGE_DIR", "./private_uploads"))
    storage_path = storage_dir / storage_key
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_bytes(content)
    candidate.resume_storage_key = storage_key

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

    if not job.jd_analysis:
        job.jd_analysis = matching_service.analyze_job(job)
    score = matching_service.score_candidate(job, candidate)
    match = CandidateJobMatch(
        organization_id=organization.id,
        job_id=job.id,
        candidate_id=candidate.id,
        model_score=score["model_score"],
        score_breakdown=score["score_breakdown"],
        matched_skills=score["matched_skills"],
        skill_gaps=score["skill_gaps"],
        explanations=score["explanations"],
        semantic_mode=score["semantic_mode"],
    )
    db.add(match)
    subject, body = _stage_email(application, "Applied", db=db)
    email_id = queue_application_email(db, application, subject, body)
    db.commit()
    if background_tasks is not None:
        background_tasks.add_task(deliver_outbox_email, email_id)

    return {
        "status": "success",
        "application_id": application.id,
        "message": f"Application submitted for {job.title}.",
    }


@app.post("/auth/register", response_model=UserRead, status_code=status.HTTP_403_FORBIDDEN)
def register_organization():
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Organization registration is disabled. Contact the system administrator for access.",
    )


@app.post("/auth/token", response_model=TokenRead)
def login(
    request: Request,
    credentials: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    login_email = credentials.username.strip().lower()
    user = db.scalar(select(User).where(User.email == login_email))

    # The single shared recruiting account is configured in Render. Reconcile it
    # at login time as well as startup so a fresh/ephemeral database can recover
    # the shared account without enabling public registration.
    bootstrap_email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    bootstrap_password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    if (
        bootstrap_email
        and bootstrap_password
        and login_email == bootstrap_email
        and credentials.password == bootstrap_password
    ):
        ensure_bootstrap_account()
        user = db.scalar(select(User).where(User.email == login_email))
        if user is not None:
            db.expire(user)
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
    db.commit()
    return TokenRead(access_token=create_access_token(user, db=db))


@app.get("/auth/me", response_model=UserRead)
def get_me(user: User = Depends(get_current_user)):
    return user

@app.post("/auth/logout")
def logout(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    from app.security import revoke_access_token
    return {"status": "revoked", "revoked": revoke_access_token(token, db)}


@app.post("/users", response_model=UserRead, status_code=status.HTTP_403_FORBIDDEN)
def create_user():
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Additional user accounts are disabled. Use the shared recruiting login.",
    )



def _candidate_search_matches(content: str, query: str) -> bool:
    query = " ".join(query.split()).strip()
    if not query:
        return True
    for any_group in re.split(r"\s+OR\s+", query, flags=re.IGNORECASE):
        terms = re.split(r"\s+AND\s+", any_group, flags=re.IGNORECASE)
        group_ok = True
        for raw_term in terms:
            term = raw_term.strip()
            negate = bool(re.match(r"^NOT\s+", term, flags=re.IGNORECASE))
            if negate:
                term = re.sub(r"^NOT\s+", "", term, flags=re.IGNORECASE).strip()
            if not term:
                continue
            present = term.casefold() in content.casefold()
            if (negate and present) or ((not negate) and (not present)):
                group_ok = False
                break
        if group_ok:
            return True
    return False


READ_ROLES = (Role.admin, Role.recruiter, Role.hiring_manager, Role.interviewer)
WRITE_ROLES = (Role.admin, Role.recruiter)


@app.post("/jobs", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def create_job(
    request: JobCreate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    job = Job(**request.model_dump(), organization_id=user.organization_id, created_by_id=user.id)
    db.add(job)
    db.flush()
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
        parsed = extractor_service.extract_to_json(content, f"job{suffix}")
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
    for field, value in updates.items():
        setattr(job, field, value)
    if set(updates) & {
        "title", "description", "location", "required_skills", "minimum_experience_years", "fresher_allowed"
    }:
        job.jd_analysis = None
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

    candidate_stage_names = {}
    stage_rows = db.execute(
        select(Application.candidate_id, Stage.name)
        .join(Stage, Application.stage_id == Stage.id)
        .where(Application.organization_id == user.organization_id)
    ).all()
    for candidate_id, stage_value in stage_rows:
        candidate_stage_names.setdefault(candidate_id, set()).add(stage_value)

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

    results = []
    for candidate in candidates:
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
        results.append(match)

    db.flush()
    record_audit(
        db,
        user,
        "job.candidates_ranked",
        "job",
        job.id,
        after={"candidate_count": len(results), "mode": "fast_local"},
    )
    db.commit()

    for match in results:
        db.refresh(match)
    results.sort(
        key=lambda match: match.recruiter_override if match.recruiter_override is not None else match.model_score,
        reverse=True,
    )
    return [_serialize_candidate_match(match) for match in results]


@app.get("/jobs/{job_id}/matches", response_model=list[CandidateMatchRead])
def list_job_matches(
    job_id: int,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    _get_org_record(db, Job, job_id, user.organization_id)
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
    return [_serialize_candidate_match(match) for match in results]


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

    alignment = (
        "Strong role alignment" if score["model_score"] >= 75
        else "Partial role alignment" if score["model_score"] >= 50
        else "Limited role alignment"
    )
    return {
        "application_id": application.id,
        "candidate_id": candidate.id,
        "candidate_name": f"{candidate.first_name} {candidate.last_name}".strip(),
        "job_id": job.id,
        "job_title": job.title,
        "match_score": score["model_score"],
        "alignment": alignment,
        "matched_skills": score["matched_skills"],
        "skill_gaps": score["skill_gaps"],
        "experience_years_estimate": matching_service._estimate_experience_years(experience),
        "experience": evidence,
        "projects": [str(project).strip() for project in projects[:10] if str(project).strip()],
        "project_skill_matches": list(dict.fromkeys(project_skill_matches)),
        "education": profile.get("education") or [],
        "explanations": score["explanations"],
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
    return _serialize_candidate_match(match)


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
        parsed = extractor_service.extract_to_json(content, f"resume{suffix}")
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
    return candidate


@app.get("/candidates", response_model=list[CandidateRead])
def list_candidates(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = None,
    skill: str | None = None,
    source: str | None = None,
    location: str | None = None,
    tags: str | None = Query(default=None, description="Comma-separated candidate tags"),
    stage_name: str | None = Query(default=None, pattern="^(Applied|Screening|Interview|Offer|Hired|Rejected|withdrawn)$"),
    min_experience_years: int | None = Query(default=None, ge=0, le=60),
    max_experience_years: int | None = Query(default=None, ge=0, le=60),
    notice_period: str | None = None,
    education: str | None = None,
    availability: str | None = None,
    preferred_location: str | None = None,
    work_authorization: str | None = None,
    has_applied_job_id: int | None = Query(default=None, ge=1),
    include_archived: bool = False,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    candidates = list(
        db.scalars(
            select(Candidate)
            .where(Candidate.organization_id == user.organization_id)
            .order_by(Candidate.created_at.desc())
        ).all()
    )

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

    filtered = []
    for candidate in candidates:
        profile = candidate.resume_data or {}
        content = haystack(candidate)
        if search and not _candidate_search_matches(content, search):
            continue
        if skill and skill.casefold() not in " ".join(str(value) for value in profile.get("skills") or []).casefold():
            continue
        if source and source.casefold() not in (candidate.source or "").casefold():
            continue
        candidate_tag_values = [str(value).casefold() for value in (candidate.tags or [])]
        if tags:
            required_tags = [value.strip().casefold() for value in tags.split(",") if value.strip()]
            if required_tags and not all(any(req == item or req in item for item in candidate_tag_values) for req in required_tags):
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
        profile_lower = json.dumps(profile, ensure_ascii=False).casefold()
        for query_value, keys in [
            (notice_period, ("notice_period", "notice period")),
            (education, ("highest_education", "education", "degree")),
            (availability, ("availability", "available_from", "available")),
            (preferred_location, ("preferred_location", "preferred location")),
            (work_authorization, ("work_authorization", "work authorization", "visa", "authorization")),
        ]:
            if query_value and not (query_value.casefold() in profile_lower):
                continue
        if has_applied_job_id is not None:
            applied = db.scalar(select(Application.id).where(
                Application.organization_id == user.organization_id,
                Application.candidate_id == candidate.id,
                Application.job_id == has_applied_job_id,
            ))
            if applied is None:
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
    email_ids = run_scorecard_automations(db, application)
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
    applications = db.scalars(
        select(Application)
        .where(Application.organization_id == user.organization_id)
        .options(selectinload(Application.stage), selectinload(Application.job), selectinload(Application.candidate))
    ).all()
    stage_counts = {stage: 0 for stage in PIPELINE_STAGES}
    source_counts = {}
    total_days = []
    hired_days = []
    for application in applications:
        stage = application.stage.name if application.stage else "Applied"
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
        source = application.candidate.source or "Unknown"
        source_counts[source] = source_counts.get(source, 0) + 1
        if application.updated_at and application.applied_at:
            days = max(0, (application.updated_at - application.applied_at).total_seconds() / 86400)
            total_days.append(days)
            if stage == "Hired":
                hired_days.append(days)
    stage_rates = {}
    previous = max(len(applications), 1)
    for stage in PIPELINE_STAGES:
        value = stage_counts.get(stage, 0)
        stage_rates[stage] = round((value / previous) * 100, 1) if previous else 0
        previous = max(value, 1)
    return {
        "total_applications": len(applications),
        "stage_counts": stage_counts,
        "stage_rates": stage_rates,
        "avg_days_in_application": round(sum(total_days) / len(total_days), 1) if total_days else 0,
        "avg_days_to_hire": round(sum(hired_days) / len(hired_days), 1) if hired_days else 0,
        "sources": [{"name": k, "count": v} for k, v in sorted(source_counts.items(), key=lambda item: item[1], reverse=True)],
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
        raise HTTPException(status_code=422, detail="Meeting link is required for online interviews.")
    round_number = (db.scalar(select(func.max(Interview.round_number)).where(Interview.application_id == application.id)) or 0) + 1
    interview = Interview(
        application_id=application.id,
        interviewer_id=application.assigned_interviewer_id or user.id,
        starts_at=request.starts_at,
        duration_minutes=request.duration_minutes,
        status="scheduled",
        mode=request.mode,
        location=request.location,
        meeting_url=request.meeting_url,
        round_name=request.round_name,
        round_number=round_number,
        feedback_deadline=request.feedback_deadline,
    )
    db.add(interview)
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
    email_id = queue_application_email(db, application, subject, body)
    record_audit(db, user, "interview.round_scheduled", "application", application.id, after={"round_name": request.round_name, "round_number": round_number})
    db.commit()
    db.refresh(interview)
    background_tasks.add_task(deliver_outbox_email, email_id)
    return interview


@app.get("/applications/{application_id}/interviews", response_model=list[InterviewRead])
def list_interview_rounds(
    application_id: int,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    application = _get_org_record(db, Application, application_id, user.organization_id)
    return db.scalars(select(Interview).where(Interview.application_id == application.id).order_by(Interview.round_number.asc(), Interview.starts_at.asc())).all()


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
    jobs = db.scalars(select(Job).where(Job.organization_id == user.organization_id)).all()
    applications = db.scalars(
        select(Application)
        .where(Application.organization_id == user.organization_id)
        .options(selectinload(Application.job), selectinload(Application.candidate), selectinload(Application.stage))
        .order_by(Application.applied_at.desc())
    ).all()
    stage_counts = {stage: 0 for stage in PIPELINE_STAGES}
    job_counts = {}
    source_counts = {}
    for application in applications:
        stage_name = application.stage.name if application.stage else "Applied"
        stage_counts[stage_name] = stage_counts.get(stage_name, 0) + 1
        job_name = application.job.title
        job_counts[job_name] = job_counts.get(job_name, 0) + 1
        source = application.candidate.source or "Unknown"
        source_counts[source] = source_counts.get(source, 0) + 1

    application_ids = [application.id for application in applications]
    email_counts = {"pending": 0, "sent": 0, "failed": 0, "other": 0}
    if application_ids:
        for status_value, count in db.execute(
            select(Email.status, func.count(Email.id))
            .where(
                Email.organization_id == user.organization_id,
                Email.application_id.in_(application_ids),
            )
            .group_by(Email.status)
        ).all():
            email_counts[status_value if status_value in email_counts else "other"] = count

    now = datetime.now(timezone.utc)
    upcoming = []
    if application_ids:
        interviews = db.scalars(
            select(Interview)
            .where(
                Interview.application_id.in_(application_ids),
                Interview.starts_at >= now,
                Interview.status == "scheduled",
            )
            .order_by(Interview.starts_at.asc())
            .limit(12)
        ).all()
        applications_by_id = {application.id: application for application in applications}
        for interview in interviews:
            application = applications_by_id.get(interview.application_id)
            if application is not None:
                upcoming.append({
                    "id": interview.id,
                    "application_id": application.id,
                    "candidate_id": application.candidate_id,
                    "candidate_name": f"{application.candidate.first_name} {application.candidate.last_name}".strip(),
                    "candidate_email": application.candidate.email,
                    "job_title": application.job.title,
                    "starts_at": interview.starts_at,
                    "duration_minutes": interview.duration_minutes,
                    "mode": interview.mode,
                    "location": interview.location,
                    "meeting_url": interview.meeting_url,
                    "status": interview.status,
                })

    return {
        "metrics": {
            "open_jobs": sum(1 for job in jobs if job.status == "open"),
            "total_jobs": len(jobs),
            "total_applications": len(applications),
            "screening": stage_counts.get("Screening", 0),
            "interviews": stage_counts.get("Interview", 0),
            "offers": stage_counts.get("Offer", 0),
            "hired": stage_counts.get("Hired", 0),
            "rejected": stage_counts.get("Rejected", 0),
        },
        "stage_counts": stage_counts,
        "job_counts": [{"name": name, "count": count} for name, count in sorted(job_counts.items(), key=lambda item: item[1], reverse=True)[:10]],
        "source_counts": [{"name": name, "count": count} for name, count in sorted(source_counts.items(), key=lambda item: item[1], reverse=True)[:10]],
        "email_counts": email_counts,
        "upcoming_interviews": upcoming,
        "recent_applications": [
            {
                "id": application.id,
                "candidate_id": application.candidate_id,
                "candidate_name": f"{application.candidate.first_name} {application.candidate.last_name}".strip(),
                "job_title": application.job.title,
                "stage_name": application.stage.name if application.stage else "Applied",
                "applied_at": application.applied_at,
            }
            for application in applications[:10]
        ],
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
    storage_dir = Path(os.getenv("RESUME_STORAGE_DIR", "./private_uploads"))
    storage_path = storage_dir / storage_key
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_bytes(content)
    try:
        parsed = extractor_service.extract_to_json(content, f"resume{suffix}")
    except Exception as error:
        storage_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Resume could not be parsed: {error}")

    before = {"resume_storage_key": candidate.resume_storage_key}
    candidate.resume_storage_key = storage_key
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
    email_ids.extend(run_stage_automations(db, application, stage.name))
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
    if request.stage_name == "Interview":
        raise HTTPException(
            status_code=422,
            detail="Schedule interviews individually so each candidate receives the correct date, time, mode and location/link.",
        )

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

@app.post("/extract/", response_class=JSONResponse)
async def extract_document(file: UploadFile = File(...)):
    try:
        suffix, content = await _read_resume_upload(file)
        structured_data = extractor_service.extract_to_json(content, f"resume{suffix}")
        return {"filename": file.filename, "status": "success", "data": structured_data}
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