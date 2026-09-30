import os
import base64
import traceback
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from celery.result import AsyncResult
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from celery_app import celery_app
from app.database import get_db, initialize_database
from app.models import Application, Candidate, Job, Organization, Role, User
from app.schemas import (
    CandidateCreate,
    CandidateRead,
    CandidateUpdate,
    JobCreate,
    JobRead,
    JobUpdate,
    OrganizationRegistration,
    TokenRead,
    UserCreate,
    UserRead,
)
from app.security import create_access_token, get_current_user, password_hash, require_roles
from app.services.extractor import extractor_service
from app.services.llm_validator import llm_validator


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="BluePace Tech ATS API", version="0.3.0", lifespan=lifespan)

allowed_origins = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

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
    for field, value in request.model_dump(exclude_unset=True).items():
        setattr(job, field, value)
    db.commit()
    db.refresh(job)
    return job


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
    candidate = Candidate(**values, organization_id=user.organization_id, created_by_id=user.id)
    db.add(candidate)
    try:
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
    updates = request.model_dump(exclude_unset=True)
    if "email" in updates and updates["email"] is not None:
        updates["email"] = str(updates["email"]).lower()
    for field, value in updates.items():
        setattr(candidate, field, value)
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
    db.delete(candidate)
    db.commit()

@app.post("/extract/", response_class=JSONResponse)
async def extract_document(file: UploadFile = File(...)):
    if file.content_type not in ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]:
        raise HTTPException(status_code=400, detail="Unsupported file type.")
    try:
        content = await file.read()
        structured_data = extractor_service.extract_to_json(content, file.filename)
        return {"filename": file.filename, "status": "success", "data": structured_data}
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
    if file.content_type not in ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]:
        raise HTTPException(status_code=400, detail="Unsupported file type.")

    content = await file.read()
    payload = base64.b64encode(content).decode("utf-8")
    task = celery_app.send_task(
        "ats.extract_resume_task",
        kwargs={
            "file_name": file.filename,
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