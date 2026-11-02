"""Public careers: seed + public job posting."""

from __future__ import annotations

import os
import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Job, Organization, Role, User
from app.security import require_roles
from app.services.workflow import ensure_job_stages, record_audit

router = APIRouter()
WRITE_ROLES = (Role.admin, Role.recruiter)


class PublicJobCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=40, max_length=20000)
    department: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    employment_type: str | None = Field(default=None, max_length=50)
    work_mode: str = Field(default="onsite", pattern="^(remote|hybrid|onsite)$")
    required_skills: list[str] = Field(default_factory=list, max_length=40)
    minimum_experience_years: float | None = Field(default=None, ge=0, le=60)
    fresher_allowed: bool = False
    contact_email: EmailStr | None = None
    posted_by_name: str | None = Field(default=None, max_length=120)


def _public_organization(db: Session) -> Organization:
    configured_id = os.getenv("PUBLIC_ORGANIZATION_ID", "").strip()
    if configured_id:
        try:
            org_id = int(configured_id)
        except ValueError as exc:
            raise HTTPException(status_code=503, detail="PUBLIC_ORGANIZATION_ID must be an integer") from exc
        org = db.get(Organization, org_id)
        if org is None:
            raise HTTPException(status_code=503, detail="PUBLIC_ORGANIZATION_ID does not match an organisation")
        return org
    organizations = db.scalars(select(Organization).order_by(Organization.id.asc()).limit(2)).all()
    if len(organizations) == 1:
        return organizations[0]
    if not organizations:
        raise HTTPException(status_code=503, detail="Create an organization before enabling the public portal")
    raise HTTPException(
        status_code=503,
        detail="Multiple organizations exist. Set PUBLIC_ORGANIZATION_ID for the public portal.",
    )


def _portal_actor(db: Session, organization_id: int) -> User:
    admin = db.scalar(
        select(User)
        .where(
            User.organization_id == organization_id,
            User.role == Role.admin,
            User.is_active.is_(True),
        )
        .order_by(User.id.asc())
        .limit(1)
    )
    if admin is not None:
        return admin
    any_user = db.scalar(
        select(User)
        .where(User.organization_id == organization_id, User.is_active.is_(True))
        .order_by(User.id.asc())
        .limit(1)
    )
    if any_user is None:
        raise HTTPException(
            status_code=503,
            detail="No active user is available to own a public job posting for this organisation.",
        )
    return any_user


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
    {
        "title": "DevOps / Platform Engineer",
        "description": (
            "Build and maintain the infrastructure and deployment pipelines that keep BluePace running reliably at scale. "
            "You will manage CI/CD, cloud infrastructure, observability, and developer tooling. "
            "Requirements: experience with AWS or Azure, Docker, Kubernetes or similar, Infrastructure as Code, "
            "and monitoring tools such as Grafana or Prometheus."
        ),
        "department": "Engineering",
        "location": "Bengaluru, India",
        "employment_type": "full-time",
        "work_mode": "hybrid",
        "required_skills": ["AWS", "Docker", "CI/CD", "Terraform", "Kubernetes"],
        "minimum_experience_years": 4.0,
        "fresher_allowed": False,
    },
    {
        "title": "QA Automation Engineer",
        "description": (
            "Ensure the quality and reliability of BluePace products through automated testing and quality processes. "
            "Design and maintain UI and API test suites, integrate tests into CI pipelines, and partner with developers "
            "on testability. Requirements: experience with Playwright or Cypress, API testing, JavaScript/TypeScript, "
            "and CI/CD integration of automated tests."
        ),
        "department": "Engineering",
        "location": "Remote — India",
        "employment_type": "full-time",
        "work_mode": "remote",
        "required_skills": ["Playwright", "Cypress", "API testing", "TypeScript", "CI/CD"],
        "minimum_experience_years": 3.0,
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
        "title": "HR Business Partner",
        "description": (
            "Act as a strategic partner to business leaders, aligning people practices with organizational goals. "
            "You will coach managers on performance and employee relations, drive engagement initiatives, "
            "support workforce planning, and ensure consistent application of HR policies. "
            "Requirements: proven HRBP experience, knowledge of employment law, strong coaching and stakeholder skills."
        ),
        "department": "People",
        "location": "Hyderabad, India",
        "employment_type": "full-time",
        "work_mode": "hybrid",
        "required_skills": ["HRBP", "Employee relations", "Workforce planning", "Coaching", "Employment law"],
        "minimum_experience_years": 5.0,
        "fresher_allowed": False,
    },
    {
        "title": "HR Generalist",
        "description": (
            "Support day-to-day HR operations including employee lifecycle, policies, and employee relations. "
            "Handle onboarding and offboarding, maintain HR records, assist with performance management, "
            "and coordinate with payroll and benefits vendors. Requirements: solid HR operations experience, "
            "working knowledge of Indian labour laws, and strong organizational skills."
        ),
        "department": "People",
        "location": "Hyderabad, India",
        "employment_type": "full-time",
        "work_mode": "onsite",
        "required_skills": ["HR operations", "Onboarding", "Labour compliance", "HRIS"],
        "minimum_experience_years": 3.0,
        "fresher_allowed": False,
    },
    {
        "title": "Learning & Development Specialist",
        "description": (
            "Design and deliver learning programs that build capability and support career growth at BluePace. "
            "Identify learning needs, facilitate leadership and soft-skills programs, manage learning platforms, "
            "and measure training effectiveness. Requirements: L&D or instructional design experience, "
            "strong facilitation skills, and familiarity with LMS tools."
        ),
        "department": "People",
        "location": "Remote — India",
        "employment_type": "full-time",
        "work_mode": "hybrid",
        "required_skills": ["Learning design", "Facilitation", "LMS", "Organizational development"],
        "minimum_experience_years": 4.0,
        "fresher_allowed": False,
    },
    {
        "title": "Compensation & Benefits Analyst",
        "description": (
            "Support competitive and fair compensation structures, benefits programs, and reward strategies. "
            "Conduct salary benchmarking, support annual compensation reviews, administer benefits, "
            "and maintain job architecture. Requirements: experience in compensation or HR analytics, "
            "strong Excel skills, and understanding of Indian compensation practices."
        ),
        "department": "People",
        "location": "Bengaluru, India",
        "employment_type": "full-time",
        "work_mode": "hybrid",
        "required_skills": ["Compensation", "Benefits", "Salary benchmarking", "Excel", "HR analytics"],
        "minimum_experience_years": 3.0,
        "fresher_allowed": False,
    },
    {
        "title": "Employee Relations Specialist",
        "description": (
            "Handle sensitive employee relations matters with fairness and care. Investigate complaints, "
            "advise managers on disciplinary and performance processes, support conflict resolution, "
            "and ensure compliance with policies and labour laws. Requirements: experience in employee or "
            "industrial relations, strong knowledge of Indian employment laws, and excellent judgment."
        ),
        "department": "People",
        "location": "Hyderabad, India",
        "employment_type": "full-time",
        "work_mode": "hybrid",
        "required_skills": ["Employee relations", "Investigations", "Labour law", "Conflict resolution"],
        "minimum_experience_years": 4.0,
        "fresher_allowed": False,
    },
    {
        "title": "HR Operations Executive",
        "description": (
            "Support core HR operations and ensure smooth day-to-day people processes. Manage employee "
            "documentation and HRIS data, coordinate joining formalities, support attendance and leave queries, "
            "and assist with engagement activities. Requirements: graduate degree preferably in HR, "
            "basic understanding of HR processes, strong attention to detail, and willingness to learn HR systems."
        ),
        "department": "People",
        "location": "Hyderabad, India",
        "employment_type": "full-time",
        "work_mode": "onsite",
        "required_skills": ["HR administration", "Documentation", "HRIS", "Employee support"],
        "minimum_experience_years": 1.0,
        "fresher_allowed": True,
    },
]


@router.post("/public/jobs", status_code=status.HTTP_201_CREATED)
def create_public_job(payload: PublicJobCreate, db: Session = Depends(get_db)):
    """Public careers form: publish an open role without recruiter login."""
    title = " ".join(payload.title.split()).strip()
    description = payload.description.strip()
    if re.search(r"\[demo\]|demo data", title, flags=re.I) or description.lower().startswith("demo data"):
        raise HTTPException(status_code=400, detail="Demo titles or DEMO DATA descriptions are not allowed on the public form.")

    organization = _public_organization(db)
    actor = _portal_actor(db, organization.id)

    skills: list[str] = []
    for raw in payload.required_skills or []:
        skill = " ".join(str(raw).split()).strip()
        if skill and skill not in skills:
            skills.append(skill[:80])
        if len(skills) >= 40:
            break

    job = Job(
        organization_id=organization.id,
        created_by_id=actor.id,
        owner_id=actor.id,
        title=title[:200],
        description=description[:20000],
        department=(payload.department or "").strip()[:200] or None,
        location=(payload.location or "").strip()[:200] or None,
        employment_type=(payload.employment_type or "").strip()[:50] or None,
        work_mode=payload.work_mode,
        status="open",
        required_skills=skills,
        minimum_experience_years=payload.minimum_experience_years,
        fresher_allowed=bool(payload.fresher_allowed),
        tags=["careers-portal", "public-form"],
        jd_analysis={
            "source": "public_job_form",
            "contact_email": str(payload.contact_email) if payload.contact_email else None,
            "posted_by_name": (payload.posted_by_name or "").strip()[:120] or None,
        },
    )
    db.add(job)
    db.flush()
    ensure_job_stages(db, job)
    record_audit(
        db,
        actor,
        "job.public_form_created",
        "job",
        job.id,
        after={"title": job.title, "status": job.status, "source": "public_job_form"},
    )
    db.commit()
    db.refresh(job)
    return {
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
        "status": job.status,
        "source_url": None,
    }


@router.post("/jobs/seed-public-openings")
def seed_public_openings(
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    """Create sample open roles for GET /public/jobs (idempotent by title)."""
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
