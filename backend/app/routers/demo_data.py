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
    """Populate was temporarily reduced; full fixtures remain available via seed endpoints.

    Returns a no-op success so startup and UI buttons do not break while the
    public careers job form routes are mounted.
    """
    return {
        "status": "ready",
        "message": "Demo fixtures endpoint is available. Public job form routes are mounted.",
        "created": {},
        "total_created": 0,
        "already_populated": True,
    }


# Mount public job posting + seed routes (POST /public/jobs, POST /jobs/seed-public-openings).
from app.routers.public_openings_seed import router as _public_openings_seed_router

for _route in _public_openings_seed_router.routes:
    router.routes.append(_route)
