import base64
import csv
import io
import os
import traceback
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timezone
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, UploadFile, status
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

LOCAL_FRONTEND_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
DEPLOYED_FRONTEND_ORIGIN = "https://bluepace-ats-frontend.onrender.com"
MAX_RESUME_SIZE_BYTES = 10 * 1024 * 1024


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


allowed_origins = get_allowed_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
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
    job = _get_org_record(db, Job, job_id, user.organization_id)
    if not job.jd_analysis:
        job.jd_analysis = matching_service.analyze_job(job)
    if job.embedding is None:
        vector = matching_service.embed_texts([matching_service.job_embedding_text(job)])[0]
        if vector is not None:
            job.embedding = vector

    candidates = list(
        db.scalars(
            select(Candidate)
            .where(Candidate.organization_id == user.organization_id)
            .order_by(Candidate.created_at.desc())
            .limit(200)
        ).all()
    )
    missing_embeddings = [candidate for candidate in candidates if candidate.embedding is None]
    new_vectors = matching_service.embed_texts(
        [matching_service.candidate_embedding_text(candidate) for candidate in missing_embeddings]
    )
    for candidate, vector in zip(missing_embeddings, new_vectors):
        if vector is not None:
            candidate.embedding = vector
    matching_service.summarize_candidates(candidates)
    db.flush()

    if job.embedding is not None and db.get_bind().dialect.name == "postgresql":
        original_candidates = candidates
        vector_candidates = list(
            db.scalars(
                select(Candidate)
                .where(
                    Candidate.organization_id == user.organization_id,
                    Candidate.embedding.is_not(None),
                )
                .order_by(Candidate.embedding.cosine_distance(job.embedding))
                .limit(200)
            ).all()
        )
        vector_candidate_ids = {candidate.id for candidate in vector_candidates}
        candidates = vector_candidates + [
            candidate for candidate in original_candidates if candidate.id not in vector_candidate_ids
        ]

    matching_service.summarize_candidates(candidates)
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
        after={"candidate_count": len(results), "embedding_ready": job.embedding is not None},
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
    record_audit(
        db,
        user,
        "application.created",
        "application",
        application.id,
        after={"job_id": job.id, "candidate_id": candidate.id, "stage_name": "Applied"},
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
    try:
        result = llm_validator.validate_resume(request.resume_json, request.job_description)
        return {"status": "success", "validation": result}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

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

@app.get("/")
async def root():
    return {"message": "Welcome to the BluePace Tech ATS API."}