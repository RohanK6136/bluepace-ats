"""Safe, idempotent demo-data population for the authenticated ATS workspace.

All records created here are synthetic. The endpoint deliberately avoids outbound email,
published jobs, real candidate files, and reminder-triggered notifications.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Application,
    AutomationRule,
    Candidate,
    CandidateComment,
    CandidateDocumentRequest,
    CandidateFollower,
    CandidateJobMatch,
    CandidatePortalQuestion,
    CandidateTag,
    Email,
    Interview,
    InterviewAvailability,
    InterviewParticipant,
    Job,
    Note,
    Offer,
    Role,
    Scorecard,
    Stage,
    TalentPool,
    TalentPoolMembership,
    User,
)
from app.security import require_roles
from app.services.workflow import ensure_job_stages, record_audit

router = APIRouter()
WRITE_ROLES = (Role.admin, Role.recruiter)


def _first(db: Session, model, *conditions):
    return db.scalar(select(model).where(*conditions).limit(1))


@router.post("/demo-data/populate")
def populate_demo_data(
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    """Create idempotent synthetic open vacancies for a careers-portal demo."""
    from app.routers.public_openings_seed import PUBLIC_OPENING_SEEDS

    created = []
    skipped = []
    try:
        # Ten varied roles are sufficient for the public careers demonstration.
        for seed in PUBLIC_OPENING_SEEDS[:10]:
            existing = db.scalar(
                select(Job)
                .where(
                    Job.organization_id == user.organization_id,
                    Job.title == seed["title"],
                )
                .limit(1)
            )
            if existing is not None:
                skipped.append({"id": existing.id, "title": existing.title})
                continue
            job = Job(
                organization_id=user.organization_id,
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
                tags=["careers-portal", "demo", seed["department"]],
            )
            db.add(job)
            db.flush()
            ensure_job_stages(db, job)
            record_audit(
                db,
                user,
                "job.demo_opening_created",
                "job",
                job.id,
                after={"title": job.title, "status": job.status, "demo": True},
            )
            created.append({"id": job.id, "title": job.title})
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "status": "ready",
        "message": "Ten synthetic demo vacancies are available. They are marked with the demo tag.",
        "created": created,
        "skipped": skipped,
        "total_created": len(created),
        "total_available": len(created) + len(skipped),
        "already_populated": not bool(created),
    }


# Mount public job posting + seed routes (POST /public/jobs, POST /jobs/seed-public-openings).
from app.routers.public_openings_seed import router as _public_openings_seed_router

for _route in _public_openings_seed_router.routes:
    router.routes.append(_route)
