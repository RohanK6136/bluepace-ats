import base64
import csv
import io
import os
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

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from celery.result import AsyncResult
from sqlalchemy import String, cast, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from celery_app import celery_app
from app.database import get_db, initialize_database
from app.models import (
    Application,
    AuditLog,
    Candidate,
    CandidateJobMatch,
    Email,
    Job,
    Organization,
    Role,
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
    OrganizationRegistration,
    TokenRead,
    UserCreate,
    UserRead,
)
from app.security import create_access_token, get_current_user, password_hash, require_roles
from app.services.extractor import DocumentExtractionError, extractor_service
from app.services.email_notifications import deliver_outbox_email
from app.services.llm_validator import llm_validator
from app.services.matching import matching_service
from app.services.workflow import (
    PIPELINE_STAGES,
    TERMINAL_STAGES,
    ensure_job_stages,
    queue_application_email,
    record_audit,
    serialize_application,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="BluePace Tech ATS API", version="0.3.0", lifespan=lifespan)


@app.middleware("http")
async def add_process_time_header(request, call_next):
    started = perf_counter()
    response = await call_next(request)
    elapsed_ms = (perf_counter() - started) * 1000
    response.headers["X-Process-Time-ms"] = f"{elapsed_ms:.2f}"
    return response

LOCAL_FRONTEND_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
DEPLOYED_FRONTEND_ORIGIN = "https://bluepace-ats-frontend.onrender.com"
MAX_RESUME_SIZE_BYTES = 10 * 1024 * 1024

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
            if isinstance(candidate, dict) and candidate.get("@type") in {"JobPosting", ["JobPosting"]}:
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
def public_jobs(db: Session = Depends(get_db)):
    organization = _public_organization(db)
    jobs = db.scalars(
        select(Job)
        .where(Job.organization_id == organization.id, Job.status == "open")
        .order_by(Job.created_at.desc())
        .limit(100)
    ).all()
    return [
        {
            "id": job.id,
            "title": job.title,
            "description": job.description,
            "department": job.department,
            "location": job.location,
            "employment_type": job.employment_type,
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
    db.commit()

    return {
        "status": "success",
        "application_id": application.id,
        "message": f"Application submitted for {job.title}.",
    }


@app.post("/auth/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register_organization(request: OrganizationRegistration, db: Session = Depends(get_db)):
    organization = Organization(name=request.organization_name)
    db.add(organization)
    db.flush()
    user = User(
        organization_id=organization.id,
        email=str(request.email).lower(),
        full_name=request.full_name,
        password_hash=password_hash.hash(request.password),
        role=Role.admin,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    db.refresh(user)
    return user


@app.post("/auth/token", response_model=TokenRead)
def login(
    credentials: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.email == credentials.username.strip().lower()))
    if user is None or not user.is_active or not password_hash.verify(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenRead(access_token=create_access_token(user))


@app.get("/auth/me", response_model=UserRead)
def get_me(user: User = Depends(get_current_user)):
    return user


@app.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    request: UserCreate,
    current_user: User = Depends(require_roles(Role.admin)),
    db: Session = Depends(get_db),
):
    user = User(
        organization_id=current_user.organization_id,
        email=str(request.email).lower(),
        full_name=request.full_name,
        password_hash=password_hash.hash(request.password),
        role=request.role,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    db.refresh(user)
    return user


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
    status_value: str = Form(default="open"),
    minimum_experience_years: int | None = Form(default=None),
    fresher_allowed: bool | None = Form(default=None),
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    source_url, markdown_title, page = _fetch_job_page(_clean_job_link(url)[0] or url)
    effective_title = (title or markdown_title or page.get("title") or "Imported job").strip()[:200]
    analysis = matching_service.parse_job_description(effective_title, page["description"], location or page.get("location"), use_llm=False)
    job = Job(
        organization_id=user.organization_id,
        created_by_id=user.id,
        title=effective_title,
        description=page["description"],
        department=department.strip() if department else None,
        location=(location.strip() if location else page.get("location")),
        employment_type=(employment_type.strip() if employment_type else page.get("employment_type")),
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

    candidates = list(
        db.scalars(
            select(Candidate)
            .where(Candidate.organization_id == user.organization_id)
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

    db.commit()
    db.refresh(candidate)
    return candidate


@app.post("/candidates", response_model=CandidateRead, status_code=status.HTTP_201_CREATED)
def create_candidate(
    request: CandidateCreate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    values = request.model_dump()
    values["email"] = str(request.email).lower()
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
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    return list(
        db.scalars(
            select(Candidate)
            .where(Candidate.organization_id == user.organization_id)
            .order_by(Candidate.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    )


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
    email_id = queue_application_email(
        db,
        application,
        f"Application received: {job.title}",
        f"Hello {candidate.first_name},\n\nYour application for {job.title} has been received.",
    )
    db.commit()
    db.refresh(application)
    background_tasks.add_task(deliver_outbox_email, email_id)
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
    if application.status in TERMINAL_STAGES.values() and application.stage.name != request.stage_name:
        raise HTTPException(status_code=409, detail="A completed application cannot be moved")
    stages = ensure_job_stages(db, application.job)
    stage = stages[request.stage_name]
    previous_name = application.stage.name if application.stage else None
    if previous_name == request.stage_name:
        return serialize_application(application)
    application.stage_id = stage.id
    application.status = TERMINAL_STAGES.get(stage.name, "active")
    record_audit(
        db,
        user,
        "application.stage_changed",
        "application",
        application.id,
        before={"stage_name": previous_name, "status": "active"},
        after={"stage_name": stage.name, "status": application.status},
    )
    email_id = queue_application_email(
        db,
        application,
        f"Application update: {application.job.title}",
        f"Hello {application.candidate.first_name},\n\nYour application status is now {stage.name}.",
    )
    db.commit()
    db.refresh(application)
    background_tasks.add_task(deliver_outbox_email, email_id)
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
        if application.status in TERMINAL_STAGES.values() and application.stage.name != request.stage_name:
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
        email_ids.append(
            queue_application_email(
                db,
                application,
                f"Application update: {application.job.title}",
                f"Hello {application.candidate.first_name},\n\nYour application status is now {stage.name}.",
            )
        )
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