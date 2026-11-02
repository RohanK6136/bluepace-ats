"""Seed real open roles for the public careers portal (not DEMO DATA)."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Job, Role, User
from app.security import require_roles
from app.services.workflow import ensure_job_stages, record_audit

router = APIRouter()
WRITE_ROLES = (Role.admin, Role.recruiter)

PUBLIC_OPENING_SEEDS = [
    {
        "title": "Senior Full Stack Engineer",
        "description": (
            "BluePace Tech is hiring a Senior Full Stack Engineer to build and harden our ATS platform. "
            "You will own recruiter-facing React workspaces, FastAPI services, and public careers flows. "
            "Responsibilities include shipping reliable REST APIs, improving resume processing throughput, "
            "and collaborating with product on hiring workflows. Requirements: strong Python and TypeScript, "
            "Postgres, REST design, and experience with production SaaS systems."
        ),
        "department": "Engineering",
        "location": "Hyderabad, India",
        "employment_type": "full-time",
        "work_mode": "hybrid",
        "required_skills": ["Python", "FastAPI", "React", "TypeScript", "PostgreSQL"],
        "minimum_experience_years": 4.0,
        "fresher_allowed": False,
    },
    {
        "title": "Backend Engineer — ATS Platform",
        "description": (
            "Join the platform team to design FastAPI services for jobs, applications, and AI-assisted recruiting. "
            "Work includes public job listing APIs, document extraction pipelines, and observability. "
            "Requirements: Python, SQL, API security basics, and comfort with background job processing."
        ),
        "department": "Engineering",
        "location": "Bengaluru, India",
        "employment_type": "full-time",
        "work_mode": "remote",
        "required_skills": ["Python", "SQL", "REST APIs", "Docker"],
        "minimum_experience_years": 2.0,
        "fresher_allowed": False,
    },
    {
        "title": "Technical Recruiter",
        "description": (
            "BluePace Tech seeks a Technical Recruiter to run end-to-end hiring for engineering and product roles. "
            "You will publish openings, screen candidates, coordinate interviews, and partner with hiring managers. "
            "Experience with an ATS, structured interviews, and technical hiring is preferred."
        ),
        "department": "People",
        "location": "Hyderabad, India",
        "employment_type": "full-time",
        "work_mode": "hybrid",
        "required_skills": ["Technical recruiting", "ATS", "Sourcing", "Interview coordination"],
        "minimum_experience_years": 3.0,
        "fresher_allowed": False,
    },
    {
        "title": "Frontend Engineer (React)",
        "description": (
            "Build polished recruiter and candidate experiences in React. Focus areas include the careers portal, "
            "application flows, dashboards, and accessible UI. Requirements: React, modern CSS, API integration, "
            "and attention to performance and accessibility."
        ),
        "department": "Engineering",
        "location": "Remote — India",
        "employment_type": "full-time",
        "work_mode": "remote",
        "required_skills": ["React", "JavaScript", "CSS", "Accessibility"],
        "minimum_experience_years": 2.0,
        "fresher_allowed": False,
    },
]


@router.post("/jobs/seed-public-openings")
def seed_public_openings(
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    """Create real open roles for GET /public/jobs (idempotent by title)."""
    org_id = user.organization_id
    created = []
    skipped = []
    try:
        for seed in PUBLIC_OPENING_SEEDS:
            existing = db.scalar(
                select(Job)
                .where(
                    Job.organization_id == org_id,
                    Job.title == seed["title"],
                    Job.status == "open",
                )
                .limit(1)
            )
            if existing is not None:
                skipped.append({"id": existing.id, "title": existing.title})
                continue
            job = Job(
                organization_id=org_id,
                created_by_id=user.id,
                owner_id=user.id,
                title=seed["title"],
                description=seed["description"],
                department=seed["department"],
                location=seed["location"],
                employment_type=seed["employment_type"],
                work_mode=seed["work_mode"],
                status="open",
                required_skills=seed["required_skills"],
                minimum_experience_years=seed["minimum_experience_years"],
                fresher_allowed=seed["fresher_allowed"],
                tags=["careers-portal", seed["department"]],
            )
            db.add(job)
            db.flush()
            ensure_job_stages(db, job)
            record_audit(
                db,
                user,
                "job.seed_public_opening",
                "job",
                job.id,
                after={"title": job.title, "status": job.status},
            )
            created.append({"id": job.id, "title": job.title})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "status": "ready",
        "message": (
            "Sample open roles are ready. They appear on the public careers portal when this "
            "organisation is PUBLIC_ORGANIZATION_ID."
        ),
        "created": created,
        "skipped": skipped,
        "public_jobs_path": "/public/jobs",
    }
