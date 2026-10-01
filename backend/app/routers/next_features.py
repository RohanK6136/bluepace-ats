from datetime import datetime, timezone
from difflib import SequenceMatcher
import csv
import io
import re
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import (
    Application,
    AuditLog,
    Candidate,
    CandidateJobMatch,
    Email,
    AutomationRule,
    InterviewParticipant,
    Interview,
    Job,
    Offer,
    Role,
    Scorecard,
    Stage,
    TalentPoolMembership,
    User,
    CandidateDocument,
)
from app.security import (
    decode_candidate_portal_token,
    get_current_user,
    require_roles,
)
from app.services.email_notifications import deliver_outbox_email
from app.services.calendar import sync_interview_calendar
from app.services.workflow import (
    PIPELINE_STAGES,
    queue_application_email,
    record_audit,
    ensure_job_stages,
)

router = APIRouter()
READ_ROLES = (Role.admin, Role.recruiter, Role.hiring_manager, Role.interviewer)
WRITE_ROLES = (Role.admin, Role.recruiter)


class CandidateTagsUpdate(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=30)


class CandidateMergeRequest(BaseModel):
    keep_candidate_id: int
    duplicate_candidate_id: int


class PortalWithdrawRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class OfferResponseRequest(BaseModel):
    status: str = Field(pattern="^(accepted|declined)$")


class InterviewRescheduleRequest(BaseModel):
    starts_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=15, le=480)
    mode: str | None = Field(default=None, pattern="^(online|offline)$")
    location: str | None = Field(default=None, max_length=500)
    meeting_url: str | None = Field(default=None, max_length=1000)
    round_name: str | None = Field(default=None, min_length=1, max_length=100)
    feedback_deadline: datetime | None = None


class AssistantRequest(BaseModel):
    question: str = Field(default="Give me a factual summary of this application.", max_length=2000)


class AutomationRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    trigger_event: str = Field(default="stage_changed", pattern="^(stage_changed|scorecards_complete)$")
    trigger_stage: str | None = Field(default=None, max_length=100)
    action_type: str = Field(default="send_email", pattern="^(send_email|assign_owner|assign_interviewer|mark_review|move_stage)$")
    action_value: str | None = Field(default=None, max_length=500)
    subject: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=10000)
    enabled: bool = True


class AutomationRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    trigger_event: str | None = Field(default=None, pattern="^(stage_changed|scorecards_complete)$")
    trigger_stage: str | None = Field(default=None, max_length=100)
    action_type: str | None = Field(default=None, pattern="^(send_email|assign_owner|assign_interviewer|mark_review|move_stage)$")
    action_value: str | None = Field(default=None, max_length=500)
    subject: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=10000)
    enabled: bool | None = None


class InterviewParticipantRequest(BaseModel):
    user_id: int


class InterviewParticipantRead(BaseModel):
    id: int
    user_id: int
    full_name: str
    email: str
    role: str


def _org_record(db: Session, model, record_id: int, organization_id: int):
    if model is Interview:
        record = db.get(Interview, record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Interview not found")
        application = db.get(Application, record.application_id)
        if application is None or application.organization_id != organization_id:
            raise HTTPException(status_code=404, detail="Interview not found")
        return record

    record = db.scalar(
        select(model).where(
            model.id == record_id,
            getattr(model, "organization_id") == organization_id,
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found")
    return record


def _name_key(candidate: Candidate) -> str:
    return re.sub(r"[^a-z0-9]", "", f"{candidate.first_name} {candidate.last_name}".casefold())


def _phone_key(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    return digits[-10:] if len(digits) >= 10 else digits


def _candidate_tags(candidate: Candidate) -> list[str]:
    return [str(tag).strip() for tag in (candidate.tags or []) if str(tag).strip()]


def _normalize_tags(tags: list[str]) -> list[str]:
    cleaned = []
    for tag in tags:
        value = " ".join(str(tag).split()).strip()
        if value:
            cleaned.append(value[:40])
    seen = set()
    result = []
    for value in cleaned:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result[:30]


def _interview_ics(interview: Interview, application: Application, base_url: str | None = None) -> str:
    starts = interview.starts_at
    if starts.tzinfo is None:
        starts = starts.replace(tzinfo=timezone.utc)
    starts_utc = starts.astimezone(timezone.utc)
    ends_utc = starts_utc.timestamp() + (interview.duration_minutes * 60)
    end = datetime.fromtimestamp(ends_utc, tz=timezone.utc)

    candidate = application.candidate
    job = application.job
    summary = f"{interview.round_name} — {job.title}"
    description = f"Blupace Tech interview for {candidate.first_name} {candidate.last_name}. Round {interview.round_number}."
    if interview.meeting_url:
        description += f" Join online: {interview.meeting_url}"
    location = interview.location or ""

    def esc(value: str) -> str:
        return str(value or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")

    uid = f"blupace-ats-interview-{interview.id}@blupacetech"
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Blupace Tech//ATS Interview//EN\r\n"
        "CALSCALE:GREGORIAN\r\n"
        "METHOD:PUBLISH\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"DTSTART:{starts_utc.strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"SUMMARY:{esc(summary)}\r\n"
        f"DESCRIPTION:{esc(description)}\r\n"
        f"LOCATION:{esc(location)}\r\n"
        + (f"URL:{esc(interview.meeting_url)}\r\n" if interview.meeting_url else "")
        + "STATUS:CONFIRMED\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )


@router.patch("/candidates/{candidate_id}/tags")
def update_candidate_tags(
    candidate_id: int,
    request: CandidateTagsUpdate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    candidate = _org_record(db, Candidate, candidate_id, user.organization_id)
    before = _candidate_tags(candidate)
    candidate.tags = _normalize_tags(request.tags)
    record_audit(
        db,
        user,
        "candidate.tags_updated",
        "candidate",
        candidate.id,
        before={"tags": before},
        after={"tags": candidate.tags},
    )
    db.commit()
    db.refresh(candidate)
    return {"candidate_id": candidate.id, "tags": candidate.tags}


@router.get("/candidate-tools/duplicate-scan")
def duplicate_scan(
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    candidates = db.scalars(
        select(Candidate)
        .where(
            Candidate.organization_id == user.organization_id,
            Candidate.archived.is_(False),
        )
        .order_by(Candidate.created_at.desc())
        .limit(1000)
    ).all()
    pairs = []
    for index, left in enumerate(candidates):
        left_name = _name_key(left)
        left_phone = _phone_key(left.phone)
        left_email = left.email.casefold().strip()
        for right in candidates[index + 1 :]:
            right_phone = _phone_key(right.phone)
            right_name = _name_key(right)
            right_email = right.email.casefold().strip()
            reasons = []
            score = 0
            if left_phone and right_phone and left_phone == right_phone:
                reasons.append("same phone")
                score = max(score, 100)
            if left_name and right_name:
                name_similarity = round(SequenceMatcher(None, left_name, right_name).ratio() * 100)
                if name_similarity >= 92:
                    reasons.append("very similar name")
                    score = max(score, name_similarity)
            if left_email and right_email and left_email == right_email:
                reasons.append("same email")
                score = 100
            if not reasons:
                continue
            if "same email" in reasons or "same phone" in reasons or score >= 92:
                pairs.append(
                    {
                        "score": score,
                        "reasons": reasons,
                        "candidate_a": {
                            "id": left.id,
                            "name": f"{left.first_name} {left.last_name}".strip(),
                            "email": left.email,
                            "phone": left.phone,
                            "tags": _candidate_tags(left),
                        },
                        "candidate_b": {
                            "id": right.id,
                            "name": f"{right.first_name} {right.last_name}".strip(),
                            "email": right.email,
                            "phone": right.phone,
                            "tags": _candidate_tags(right),
                        },
                    }
                )
                if len(pairs) >= limit:
                    break
        if len(pairs) >= limit:
            break
    pairs.sort(key=lambda item: item["score"], reverse=True)
    return {"count": len(pairs), "duplicates": pairs}


@router.post("/candidate-tools/candidates/merge")
def merge_candidates(
    request: CandidateMergeRequest,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    if request.keep_candidate_id == request.duplicate_candidate_id:
        raise HTTPException(status_code=400, detail="Choose two different candidates to merge")
    keep = _org_record(db, Candidate, request.keep_candidate_id, user.organization_id)
    duplicate = _org_record(db, Candidate, request.duplicate_candidate_id, user.organization_id)
    if keep.archived or duplicate.archived:
        raise HTTPException(status_code=409, detail="Archived candidates cannot be merged")

    before = {
        "keep": {"id": keep.id, "name": f"{keep.first_name} {keep.last_name}", "tags": _candidate_tags(keep)},
        "duplicate": {"id": duplicate.id, "name": f"{duplicate.first_name} {duplicate.last_name}", "tags": _candidate_tags(duplicate)},
    }

    keep.tags = _normalize_tags(_candidate_tags(keep) + _candidate_tags(duplicate))

    if not keep.phone and duplicate.phone:
        keep.phone = duplicate.phone
    if not keep.linkedin_url and duplicate.linkedin_url:
        keep.linkedin_url = duplicate.linkedin_url
    if not keep.resume_storage_key and duplicate.resume_storage_key:
        keep.resume_storage_key = duplicate.resume_storage_key
    if not keep.resume_data and duplicate.resume_data:
        keep.resume_data = duplicate.resume_data
    if duplicate.cv_summary:
        keep.cv_summary = list(dict.fromkeys(
            [str(v) for v in (keep.cv_summary or []) if str(v).strip()]
            + [str(v) for v in duplicate.cv_summary if str(v).strip()]
        ))

    if duplicate.resume_data:
        current = dict(keep.resume_data or {})
        incoming = dict(duplicate.resume_data or {})
        for list_key in ("skills", "university_projects", "projects", "hobbies"):
            merged = [str(v).strip() for v in (current.get(list_key) or []) + (incoming.get(list_key) or []) if str(v).strip()]
            if merged:
                current[list_key] = list(dict.fromkeys(merged))
        for list_key in ("experience", "education"):
            if incoming.get(list_key):
                current[list_key] = (current.get(list_key) or []) + [v for v in incoming.get(list_key) or [] if v not in (current.get(list_key) or [])]
        for scalar_key in ("linkedin", "github", "notice_period", "availability", "preferred_location", "work_authorization"):
            if not current.get(scalar_key) and incoming.get(scalar_key):
                current[scalar_key] = incoming.get(scalar_key)
        keep.resume_data = current

    conflicting_applications = 0
    duplicate_application_rows = db.scalars(
        select(Application).where(
            Application.organization_id == user.organization_id,
            Application.candidate_id == duplicate.id,
        )
    ).all()
    keep_job_ids = {
        app.job_id
        for app in db.scalars(
            select(Application).where(
                Application.organization_id == user.organization_id,
                Application.candidate_id == keep.id,
            )
        ).all()
    }
    for application in duplicate_application_rows:
        if application.job_id in keep_job_ids:
            conflicting_applications += 1
        else:
            application.candidate_id = keep.id

    for match in db.scalars(
        select(CandidateJobMatch).where(
            CandidateJobMatch.organization_id == user.organization_id,
            CandidateJobMatch.candidate_id == duplicate.id,
        )
    ).all():
        existing = db.scalar(
            select(CandidateJobMatch).where(
                CandidateJobMatch.organization_id == user.organization_id,
                CandidateJobMatch.candidate_id == keep.id,
                CandidateJobMatch.job_id == match.job_id,
            )
        )
        if existing is None:
            match.candidate_id = keep.id
        else:
            db.delete(match)

    for membership in db.scalars(
        select(TalentPoolMembership).where(TalentPoolMembership.candidate_id == duplicate.id)
    ).all():
        existing = db.scalar(
            select(TalentPoolMembership).where(
                TalentPoolMembership.pool_id == membership.pool_id,
                TalentPoolMembership.candidate_id == keep.id,
            )
        )
        if existing is None:
            membership.candidate_id = keep.id
        else:
            db.delete(membership)

    duplicate.archived = True
    duplicate.merged_into_id = keep.id
    record_audit(
        db,
        user,
        "candidate.merged",
        "candidate",
        keep.id,
        before=before,
        after={
            "merged_candidate_id": duplicate.id,
            "conflicting_applications": conflicting_applications,
            "tags": _candidate_tags(keep),
        },
    )
    db.commit()
    return {
        "status": "merged",
        "kept_candidate_id": keep.id,
        "archived_candidate_id": duplicate.id,
        "conflicting_applications": conflicting_applications,
        "tags": _candidate_tags(keep),
    }


@router.patch("/interviews/{interview_id}")
def reschedule_interview(
    interview_id: int,
    request: InterviewRescheduleRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    interview = _org_record(db, Interview, interview_id, user.organization_id)
    application = db.scalar(
        select(Application)
        .where(
            Application.id == interview.application_id,
            Application.organization_id == user.organization_id,
        )
        .options(selectinload(Application.job), selectinload(Application.candidate), selectinload(Application.stage)),
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if interview.status == "cancelled":
        raise HTTPException(status_code=409, detail="Cancelled interviews cannot be rescheduled")

    starts_at = request.starts_at or interview.starts_at
    duration = request.duration_minutes or interview.duration_minutes
    mode = request.mode or interview.mode
    location = request.location if request.location is not None else interview.location
    meeting_url = request.meeting_url if request.meeting_url is not None else interview.meeting_url
    if starts_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="Interview date and time must include a timezone.")
    if mode == "offline" and not location:
        raise HTTPException(status_code=422, detail="Interview location is required for an offline interview.")
    if mode == "online" and not meeting_url:
        raise HTTPException(status_code=422, detail="Meeting link is required for an online interview.")

    before = {
        "starts_at": interview.starts_at.isoformat(),
        "duration_minutes": interview.duration_minutes,
        "mode": interview.mode,
        "location": interview.location,
        "meeting_url": interview.meeting_url,
        "round_name": interview.round_name,
    }
    interview.starts_at = starts_at
    interview.duration_minutes = duration
    interview.mode = mode
    interview.location = location
    interview.meeting_url = meeting_url
    if request.round_name:
        interview.round_name = request.round_name
    if request.feedback_deadline is not None:
        interview.feedback_deadline = request.feedback_deadline
    interview.status = "scheduled"
    interview.reminder_24_sent = False
    interview.reminder_1h_sent = False

    tz = starts_at.tzinfo
    readable = starts_at.astimezone(tz).strftime("%d %B %Y at %I:%M %p %Z")
    details = f"{readable}, {duration} minutes, {'Online' if mode == 'online' else 'Offline'}"
    if meeting_url:
        details += f", {meeting_url}"
    elif location:
        details += f", {location}"
    subject = f"Interview rescheduled: {application.job.title}"
    body = (
        f"Hello {application.candidate.first_name},\n\n"
        f"Your {interview.round_name} for {application.job.title} has been rescheduled.\n\n"
        f"New schedule: {details}.\n\n"
        "Please use the secure candidate portal for the latest application details.\n\n"
        "Blupace Tech Recruiting"
    )
    email_id = queue_application_email(db, application, subject, body)
    record_audit(
        db,
        user,
        "interview.rescheduled",
        "interview",
        interview.id,
        before=before,
        after={
            "starts_at": interview.starts_at.isoformat(),
            "duration_minutes": interview.duration_minutes,
            "mode": interview.mode,
            "location": interview.location,
            "meeting_url": interview.meeting_url,
            "round_name": interview.round_name,
        },
    )
    db.commit()
    db.refresh(interview)
    background_tasks.add_task(deliver_outbox_email, email_id)
    background_tasks.add_task(sync_interview_calendar, interview.id, user.organization_id, user.id, "upsert")
    return {
        "id": interview.id,
        "application_id": application.id,
        "starts_at": interview.starts_at,
        "duration_minutes": interview.duration_minutes,
        "status": interview.status,
        "mode": interview.mode,
        "location": interview.location,
        "meeting_url": interview.meeting_url,
        "round_name": interview.round_name,
        "round_number": interview.round_number,
        "feedback_deadline": interview.feedback_deadline,
        "cancellation_reason": interview.cancellation_reason,
        "email_id": email_id,
    }


@router.post("/interviews/{interview_id}/cancel")
def cancel_interview(
    interview_id: int,
    background_tasks: BackgroundTasks,
    reason: str | None = Query(default=None, max_length=1000),
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    interview = _org_record(db, Interview, interview_id, user.organization_id)
    application = db.scalar(
        select(Application)
        .where(Application.id == interview.application_id, Application.organization_id == user.organization_id)
        .options(selectinload(Application.job), selectinload(Application.candidate)),
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if interview.status == "cancelled":
        return {"id": interview.id, "status": "cancelled"}
    interview.status = "cancelled"
    interview.cancellation_reason = (reason or "").strip() or None
    interview.reminder_24_sent = True
    interview.reminder_1h_sent = True
    subject = f"Interview cancelled: {application.job.title}"
    body = (
        f"Hello {application.candidate.first_name},\n\n"
        f"Your {interview.round_name} for {application.job.title} scheduled for "
        f"{interview.starts_at.strftime('%d %B %Y at %I:%M %p')} has been cancelled. "
        "Please keep your candidate portal link for future updates.\n\n"
        "Blupace Tech Recruiting"
    )
    email_id = queue_application_email(db, application, subject, body)
    record_audit(db, user, "interview.cancelled", "interview", interview.id, after={"status": "cancelled", "reason": interview.cancellation_reason})
    db.commit()
    background_tasks.add_task(deliver_outbox_email, email_id)
    background_tasks.add_task(sync_interview_calendar, interview.id, user.organization_id, user.id, "delete")
    return {"id": interview.id, "status": interview.status, "email_id": email_id}


@router.get("/interviews/{interview_id}/ics")
def download_interview_ics(
    interview_id: int,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    interview = _org_record(db, Interview, interview_id, user.organization_id)
    application = db.scalar(
        select(Application)
        .where(Application.id == interview.application_id, Application.organization_id == user.organization_id)
        .options(selectinload(Application.job), selectinload(Application.candidate)),
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return Response(
        content=_interview_ics(interview, application),
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="blupace-interview-{interview.id}.ics"'},
    )


@router.get("/public/application/{token}/details")
def public_application_details(token: str, db: Session = Depends(get_db)):
    try:
        application_id = decode_candidate_portal_token(token)
    except Exception as error:
        raise HTTPException(status_code=401, detail="This candidate portal link is invalid or expired.") from error

    application = db.scalar(
        select(Application)
        .where(Application.id == application_id)
        .options(
            selectinload(Application.job),
            selectinload(Application.candidate),
            selectinload(Application.stage),
        )
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    interviews = db.scalars(
        select(Interview)
        .where(Interview.application_id == application.id)
        .order_by(Interview.round_number.asc(), Interview.starts_at.desc())
    ).all()
    offer = db.scalar(select(Offer).where(Offer.application_id == application.id))
    audit_rows = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.organization_id == application.organization_id,
            AuditLog.entity_type == "application",
            AuditLog.entity_id == application.id,
            AuditLog.action.in_({"application.stage_changed", "application.created"}),
        )
        .order_by(AuditLog.created_at.asc())
    ).all()

    timeline = []
    for row in audit_rows:
        stage_name = (row.after_data or {}).get("stage_name")
        timeline.append(
            {
                "type": "application",
                "title": stage_name or row.action.replace(".", " · ").title(),
                "created_at": row.created_at,
                "stage_name": stage_name,
            }
        )
    for interview in interviews:
        timeline.append(
            {
                "type": "interview",
                "title": f"{interview.round_name} — {interview.status.replace('_', ' ').title()}",
                "created_at": interview.starts_at,
                "stage_name": "Interview",
            }
        )
    timeline.sort(key=lambda item: item["created_at"])

    offer_payload = None
    if offer:
        if offer.status == "sent" and offer.viewed_at is None:
            offer.status = "viewed"
            offer.viewed_at = datetime.now(timezone.utc)
            db.commit()
        if offer.expires_at and offer.expires_at < datetime.now(timezone.utc) and offer.status in {"sent", "viewed"}:
            offer.status = "expired"
            db.commit()
        offer_payload = {
            "id": offer.id,
            "position_title": offer.position_title,
            "annual_ctc": offer.annual_ctc,
            "currency": offer.currency,
            "joining_date": offer.joining_date,
            "offer_letter_url": offer.offer_letter_url,
            "status": offer.status,
            "ctc_breakdown": offer.ctc_breakdown,
            "benefits": offer.benefits,
            "probation_period": offer.probation_period,
            "expires_at": offer.expires_at,
            "offer_letter_url": offer.offer_letter_url,
        }

    return {
        "application_id": application.id,
        "candidate_name": f"{application.candidate.first_name} {application.candidate.last_name}".strip(),
        "job_title": application.job.title,
        "stage_name": application.stage.name if application.stage else "Applied",
        "status": application.status,
        "applied_at": application.applied_at,
        "timeline": timeline,
        "offer": offer_payload,
        "interviews": [
            {
                "id": interview.id,
                "round_name": interview.round_name,
                "round_number": interview.round_number,
                "starts_at": interview.starts_at,
                "duration_minutes": interview.duration_minutes,
                "mode": interview.mode,
                "location": interview.location,
                "meeting_url": interview.meeting_url,
                "status": interview.status,
                "calendar_url": f"/public/application/{token}/interviews/{interview.id}.ics",
            }
            for interview in interviews
        ],
    }


@router.post("/public/application/{token}/withdraw")
def public_withdraw_application(
    token: str,
    request: PortalWithdrawRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        application_id = decode_candidate_portal_token(token)
    except Exception as error:
        raise HTTPException(status_code=401, detail="This candidate portal link is invalid or expired.") from error
    application = db.scalar(
        select(Application)
        .where(Application.id == application_id)
        .options(selectinload(Application.job), selectinload(Application.candidate)),
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if application.status in {"hired", "rejected"}:
        raise HTTPException(status_code=409, detail="This application is already closed.")
    if application.status == "withdrawn":
        return {"status": "withdrawn", "message": "This application is already marked as withdrawn."}

    application.status = "withdrawn"
    reason = (request.reason or "").strip()
    subject = f"Application withdrawal confirmed: {application.job.title}"
    body = (
        f"Hello {application.candidate.first_name},\n\n"
        f"We have recorded your withdrawal from {application.job.title}."
        + (f" Your reason was recorded as: {reason}." if reason else "")
        + "\n\nBlupace Tech Recruiting"
    )
    email = Email(
        organization_id=application.organization_id,
        application_id=application.id,
        recipient=application.candidate.email,
        subject=subject,
        body=body,
        status="pending",
    )
    db.add(email)
    db.commit()
    db.refresh(email)
    background_tasks.add_task(deliver_outbox_email, email.id)
    return {"status": "withdrawn", "message": "Your application has been marked as withdrawn."}


@router.post("/public/application/{token}/offer-response")
def public_offer_response(
    token: str,
    request: OfferResponseRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        application_id = decode_candidate_portal_token(token)
    except Exception as error:
        raise HTTPException(status_code=401, detail="This candidate portal link is invalid or expired.") from error
    application = db.scalar(
        select(Application)
        .where(Application.id == application_id)
        .options(selectinload(Application.job), selectinload(Application.candidate)),
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    offer = db.scalar(select(Offer).where(Offer.application_id == application.id))
    if offer is None:
        raise HTTPException(status_code=404, detail="No offer is available for this application")
    if offer.expires_at and offer.expires_at < datetime.now(timezone.utc) and offer.status in {"sent", "viewed"}:
        offer.status = "expired"
        offer.responded_at = datetime.now(timezone.utc)
        db.commit()
    if offer.status in {"accepted", "declined", "expired"}:
        return {"status": offer.status, "message": f"The offer is already marked {offer.status}."}

    if offer.status not in {"sent", "viewed"}:
        raise HTTPException(status_code=409, detail="This offer is not currently open for a candidate response.")
    offer.status = request.status
    offer.responded_at = datetime.now(timezone.utc)
    verb = "accepted" if request.status == "accepted" else "declined"
    subject = f"Offer {verb}: {offer.position_title}"
    body = (
        f"Hello {application.candidate.first_name},\n\n"
        f"Your offer response for {offer.position_title} has been recorded as {verb}."
        "\n\nBlupace Tech Recruiting"
    )
    email = Email(
        organization_id=application.organization_id,
        application_id=application.id,
        recipient=application.candidate.email,
        subject=subject,
        body=body,
        status="pending",
    )
    db.add(email)
    db.commit()
    db.refresh(email)
    background_tasks.add_task(deliver_outbox_email, email.id)
    return {"status": offer.status, "message": f"Offer response recorded as {verb}."}


@router.post("/applications/{application_id}/offer/send")
def send_offer(
    application_id: int,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    application = _org_record(db, Application, application_id, user.organization_id)
    offer = db.scalar(select(Offer).where(Offer.application_id == application.id))
    if offer is None:
        raise HTTPException(status_code=404, detail="No offer created for this application")
    if offer.status in {"accepted", "declined", "expired"}:
        raise HTTPException(status_code=409, detail=f"This offer is already {offer.status}.")
    if not offer.position_title:
        raise HTTPException(status_code=422, detail="Offer position title is required.")
    if offer.status != "approved":
        raise HTTPException(status_code=409, detail="Approve the offer internally before sending it.")
    offer.status = "sent"
    offer.sent_at = datetime.now(timezone.utc)
    subject = f"Offer from Blupace Tech: {offer.position_title}"
    body = (
        f"Hello {application.candidate.first_name},\n\n"
        f"We are pleased to share an offer for {offer.position_title}."
        + (f" Annual CTC: {offer.annual_ctc} {offer.currency}." if offer.annual_ctc else "")
        + (f" Joining date: {offer.joining_date.strftime('%d %B %Y')}." if offer.joining_date else "")
        + (f" Offer letter: {offer.offer_letter_url}" if offer.offer_letter_url else "")
        + "\n\nPlease use your secure candidate portal to review and respond to the offer.\n\nBlupace Tech Recruiting"
    )
    email_id = queue_application_email(db, application, subject, body)
    record_audit(db, user, "offer.sent", "application", application.id, after={"offer_id": offer.id, "status": offer.status})
    db.commit()
    background_tasks.add_task(deliver_outbox_email, email_id)
    return {"status": offer.status, "offer_id": offer.id, "email_id": email_id}


@router.post("/public/application/{token}/interviews/{interview_id}.ics")
def _unused_public_ics_post(token: str, interview_id: int):
    raise HTTPException(status_code=405, detail="Use GET for calendar files")


@router.get("/public/application/{token}/interviews/{interview_id}.ics")
def public_interview_ics(token: str, interview_id: int, db: Session = Depends(get_db)):
    try:
        application_id = decode_candidate_portal_token(token)
    except Exception as error:
        raise HTTPException(status_code=401, detail="This candidate portal link is invalid or expired.") from error
    interview = db.get(Interview, interview_id)
    if interview is None or interview.application_id != application_id:
        raise HTTPException(status_code=404, detail="Interview not found")
    application = db.scalar(
        select(Application)
        .where(Application.id == application_id)
        .options(selectinload(Application.job), selectinload(Application.candidate)),
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return Response(
        content=_interview_ics(interview, application),
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="blupace-interview-{interview.id}.ics"'},
    )


@router.get("/reports/recruitment.csv")
def recruitment_report(
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    applications = db.scalars(
        select(Application)
        .where(Application.organization_id == user.organization_id)
        .options(selectinload(Application.job), selectinload(Application.candidate), selectinload(Application.stage))
        .order_by(Application.applied_at.desc())
    ).all()
    application_ids = [app.id for app in applications]
    interview_counts = {}
    if application_ids:
        for app_id, count in db.execute(
            select(Interview.application_id, func.count(Interview.id))
            .where(Interview.application_id.in_(application_ids))
            .group_by(Interview.application_id)
        ).all():
            interview_counts[app_id] = count
    offers = {
        offer.application_id: offer
        for offer in db.scalars(
            select(Offer).where(Offer.application_id.in_(application_ids))
        ).all()
    } if application_ids else {}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Application ID", "Job", "Candidate", "Email", "Source", "Stage", "Application Status",
        "Applied At", "Interview Rounds", "Offer Status", "Offer CTC", "Currency", "Joining Date", "Tags"
    ])
    for application in applications:
        candidate = application.candidate
        offer = offers.get(application.id)
        writer.writerow([
            application.id,
            application.job.title,
            f"{candidate.first_name} {candidate.last_name}".strip(),
            candidate.email,
            candidate.source or "",
            application.stage.name if application.stage else "Applied",
            application.status,
            application.applied_at.isoformat(),
            interview_counts.get(application.id, 0),
            offer.status if offer else "",
            offer.annual_ctc if offer else "",
            offer.currency if offer else "",
            offer.joining_date.isoformat() if offer and offer.joining_date else "",
            ", ".join(_candidate_tags(candidate)),
        ])
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="blupace-recruitment-report.csv"'},
    )


@router.post("/candidate-tools/applications/{application_id}/assistant")
def recruiter_assistant(
    application_id: int,
    request: AssistantRequest,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    application = db.scalar(
        select(Application)
        .where(Application.id == application_id, Application.organization_id == user.organization_id)
        .options(selectinload(Application.job), selectinload(Application.candidate), selectinload(Application.stage)),
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    candidate = application.candidate
    job = application.job
    profile = candidate.resume_data or {}
    skills = [str(value) for value in (profile.get("skills") or [])][:30]
    experience = profile.get("experience") or []
    projects = [str(value) for value in (profile.get("university_projects") or profile.get("projects") or [])][:8]
    education = profile.get("education") or []
    match = db.scalar(
        select(CandidateJobMatch).where(
            CandidateJobMatch.organization_id == user.organization_id,
            CandidateJobMatch.candidate_id == candidate.id,
            CandidateJobMatch.job_id == job.id,
        )
    )
    offer = db.scalar(select(Offer).where(Offer.application_id == application.id))
    interviews = db.scalars(
        select(Interview)
        .where(Interview.application_id == application.id)
        .order_by(Interview.round_number.asc())
    ).all()

    match_score = match.recruiter_override if match and match.recruiter_override is not None else (match.model_score if match else None)
    experience_years = 0.0
    try:
        from app.services.matching import matching_service
        experience_years = matching_service._estimate_experience_years(experience)
    except Exception:
        pass

    focus = []
    question = request.question.casefold()
    if "skill" in question:
        focus.append(f"Resume skills: {', '.join(skills) or 'No structured skills parsed'}")
    if "experience" in question:
        focus.append(f"Estimated experience: {experience_years:g} years across {len(experience)} parsed role(s)")
    if "project" in question:
        focus.append(f"Parsed projects: {', '.join(projects) or 'No projects parsed'}")
    if "education" in question:
        education_text = [
            " · ".join(str(item.get(key)) for key in ("degree", "university", "graduation_year") if item.get(key))
            for item in education if isinstance(item, dict)
        ]
        focus.append(f"Education: {', '.join(value for value in education_text if value) or 'No structured education parsed'}")
    if "interview" in question:
        focus.append(f"Interview rounds: {len(interviews)}")
    if "offer" in question:
        focus.append(f"Offer status: {offer.status if offer else 'No offer created'}")
    if not focus:
        focus = [
            f"Application is in {application.stage.name if application.stage else 'Applied'} stage.",
            f"Role: {job.title}.",
            f"Candidate: {candidate.first_name} {candidate.last_name}".strip(),
            f"Structured skills parsed: {', '.join(skills) or 'None'}",
            f"Estimated experience: {experience_years:g} years.",
            f"Interview rounds recorded: {len(interviews)}.",
            f"Offer status: {offer.status if offer else 'No offer created'}.",
        ]

    summary = (
        f"{candidate.first_name} {candidate.last_name} is currently in the "
        f"{application.stage.name if application.stage else 'Applied'} stage for {job.title}. "
        f"The recorded match evidence is {match_score if match_score is not None else 'not available'} / 100. "
        "This assistant returns structured recruiting evidence only and does not make a hiring decision."
    )
    return {
        "application_id": application.id,
        "question": request.question,
        "summary": summary,
        "key_facts": focus,
        "job": {"id": job.id, "title": job.title},
        "candidate": {"id": candidate.id, "name": f"{candidate.first_name} {candidate.last_name}".strip()},
    }


def _render_automation(template: str, application: Application, stage_name: str) -> str:
    candidate = application.candidate
    job = application.job
    portal_url = ""
    try:
        from app.security import create_candidate_portal_token
        from app.main import DEPLOYED_FRONTEND_ORIGIN
        import urllib.parse
        portal_url = f"{DEPLOYED_FRONTEND_ORIGIN}?portal={urllib.parse.quote(create_candidate_portal_token(application.id))}"
    except Exception:
        portal_url = ""
    values = {
        "candidate_name": f"{candidate.first_name} {candidate.last_name}".strip(),
        "candidate_email": candidate.email,
        "job_title": job.title,
        "stage_name": stage_name,
        "candidate_portal_url": portal_url,
        "company_name": "Blupace Tech",
    }
    rendered = str(template or "")
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", str(value or ""))
    return rendered


def _expected_interviewer_ids(db: Session, application_id: int) -> set[int]:
    ids = set(db.scalars(
        select(Interview.interviewer_id).where(
            Interview.application_id == application_id,
            Interview.status != "cancelled",
        )
    ).all())
    participant_ids = db.scalars(
        select(InterviewParticipant.user_id)
        .join(Interview, InterviewParticipant.interview_id == Interview.id)
        .where(
            Interview.application_id == application_id,
            Interview.status != "cancelled",
        )
    ).all()
    ids.update(participant_ids)
    return {int(value) for value in ids if value}


def scorecards_complete(db: Session, application_id: int) -> bool:
    expected = _expected_interviewer_ids(db, application_id)
    if not expected:
        return False
    submitted = set(db.scalars(
        select(Scorecard.interviewer_id).where(
            Scorecard.application_id == application_id,
            Scorecard.submitted_at.is_not(None),
        )
    ).all())
    return expected.issubset(submitted)


def _apply_automation_action(
    db: Session,
    application: Application,
    rule: AutomationRule,
    stage_name: str,
    skip_rule_ids: set[int] | None = None,
) -> list[int]:
    queued = []
    if rule.action_type == "send_email":
        if rule.subject.strip() and rule.body.strip():
            queued.append(queue_application_email(
                db,
                application,
                _render_automation(rule.subject, application, stage_name),
                _render_automation(rule.body, application, stage_name),
            ))
    elif rule.action_type == "assign_owner":
        try:
            owner_id = int(rule.action_value or "")
        except (TypeError, ValueError):
            owner_id = 0
        owner = db.scalar(select(User).where(User.id == owner_id, User.organization_id == application.organization_id, User.is_active.is_(True)))
        if owner is not None:
            application.candidate.owner_id = owner.id
    elif rule.action_type == "assign_interviewer":
        try:
            interviewer_id = int(rule.action_value or "")
        except (TypeError, ValueError):
            interviewer_id = 0
        interviewer = db.scalar(select(User).where(
            User.id == interviewer_id,
            User.organization_id == application.organization_id,
            User.is_active.is_(True),
            User.role == Role.interviewer,
        ))
        if interviewer is None:
            raise HTTPException(status_code=404, detail="Configured interviewer not found")
        application.assigned_interviewer_id = interviewer.id
    elif rule.action_type == "mark_review":
        application.candidate.needs_review = True
    elif rule.action_type == "move_stage":
        target = (rule.action_value or "").strip()
        if target in PIPELINE_STAGES and target != stage_name and target != "Interview":
            stages = ensure_job_stages(db, application.job)
            stage = stages.get(target)
            if stage is not None:
                application.stage_id = stage.id
                application.status = "active" if target not in {"Hired", "Rejected"} else target.casefold()
                subject = f"Application update — {application.job.title}"
                body = (
                    f"Hello {application.candidate.first_name},\n\n"
                    f"Your application for {application.job.title} has moved to the {target} stage. "
                    "Please keep your candidate portal link for future updates.\n\n"
                    "Blupace Tech Recruiting"
                )
                if not stage_email_automation_enabled(db, application, target):
                    queued.append(queue_application_email(db, application, subject, body))
                db.add(AuditLog(
                    organization_id=application.organization_id,
                    actor_id=rule.created_by_id,
                    action="automation.stage_moved",
                    entity_type="application",
                    entity_id=application.id,
                    after_data={"stage_name": target, "rule_id": rule.id},
                ))
                visited = set(skip_rule_ids or set())
                visited.add(rule.id)
                queued.extend(run_stage_automations(db, application, target, skip_rule_ids=visited))
    return queued


def stage_email_automation_enabled(db: Session, application: Application, stage_name: str) -> bool:
    return db.scalar(
        select(AutomationRule.id).where(
            AutomationRule.organization_id == application.organization_id,
            AutomationRule.enabled.is_(True),
            AutomationRule.trigger_event == "stage_changed",
            AutomationRule.trigger_stage == stage_name,
            AutomationRule.action_type == "send_email",
        ).limit(1)
    ) is not None


def run_stage_automations(
    db: Session,
    application: Application,
    stage_name: str,
    skip_rule_ids: set[int] | None = None,
) -> list[int]:
    rules = db.scalars(
        select(AutomationRule).where(
            AutomationRule.organization_id == application.organization_id,
            AutomationRule.enabled.is_(True),
            AutomationRule.trigger_event == "stage_changed",
        )
    ).all()
    skipped = skip_rule_ids or set()
    email_ids = []
    for rule in rules:
        if rule.id in skipped:
            continue
        if rule.trigger_stage and rule.trigger_stage != stage_name:
            continue
        email_ids.extend(_apply_automation_action(db, application, rule, stage_name, skipped))
    return email_ids


def run_scorecard_automations(db: Session, application: Application) -> list[int]:
    if not scorecards_complete(db, application.id):
        return []
    rules = db.scalars(
        select(AutomationRule).where(
            AutomationRule.organization_id == application.organization_id,
            AutomationRule.enabled.is_(True),
            AutomationRule.trigger_event == "scorecards_complete",
        )
    ).all()
    stage_name = application.stage.name if application.stage else "Applied"
    email_ids = []
    for rule in rules:
        email_ids.extend(_apply_automation_action(db, application, rule, stage_name))
    return email_ids


@router.get("/automation-rules")
def list_automation_rules(
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(AutomationRule)
        .where(AutomationRule.organization_id == user.organization_id)
        .order_by(AutomationRule.created_at.desc())
    ).all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "trigger_event": row.trigger_event,
            "trigger_stage": row.trigger_stage,
            "action_type": row.action_type,
            "action_value": row.action_value,
            "subject": row.subject,
            "body": row.body,
            "enabled": row.enabled,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


@router.post("/automation-rules")
def create_automation_rule(
    request: AutomationRuleCreate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    row = AutomationRule(
        organization_id=user.organization_id,
        created_by_id=user.id,
        name=request.name.strip(),
        trigger_event=request.trigger_event,
        trigger_stage=request.trigger_stage or None,
        action_type=request.action_type,
        action_value=request.action_value,
        subject=request.subject.strip(),
        body=request.body,
        enabled=request.enabled,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    record_audit(db, user, "automation.created", "automation_rule", row.id, after={"name": row.name, "trigger_stage": row.trigger_stage, "enabled": row.enabled})
    db.commit()
    return {
        "id": row.id, "name": row.name, "trigger_event": row.trigger_event,
        "trigger_stage": row.trigger_stage, "action_type": row.action_type,
        "subject": row.subject, "body": row.body, "enabled": row.enabled,
        "created_at": row.created_at, "updated_at": row.updated_at,
    }


@router.patch("/automation-rules/{rule_id}")
def update_automation_rule(
    rule_id: int,
    request: AutomationRuleUpdate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    row = _org_record(db, AutomationRule, rule_id, user.organization_id)
    before = {"name": row.name, "trigger_stage": row.trigger_stage, "subject": row.subject, "enabled": row.enabled}
    for field in ("name", "trigger_event", "trigger_stage", "action_type", "action_value", "subject", "body", "enabled"):
        value = getattr(request, field)
        if value is not None:
            setattr(row, field, value.strip() if isinstance(value, str) else value)
    record_audit(db, user, "automation.updated", "automation_rule", row.id, before=before, after={"name": row.name, "trigger_stage": row.trigger_stage, "subject": row.subject, "enabled": row.enabled})
    db.commit()
    db.refresh(row)
    return {"id": row.id, "name": row.name, "trigger_event": row.trigger_event, "trigger_stage": row.trigger_stage, "action_type": row.action_type, "subject": row.subject, "body": row.body, "enabled": row.enabled, "created_at": row.created_at, "updated_at": row.updated_at}


@router.delete("/automation-rules/{rule_id}")
def delete_automation_rule(
    rule_id: int,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    row = _org_record(db, AutomationRule, rule_id, user.organization_id)
    record_audit(db, user, "automation.deleted", "automation_rule", row.id, before={"name": row.name})
    db.delete(row)
    db.commit()
    return {"status": "deleted", "id": rule_id}


@router.get("/recruiting-users")
def list_recruiting_users(
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(User).where(
            User.organization_id == user.organization_id,
            User.is_active.is_(True),
            User.role != Role.candidate,
        ).order_by(User.full_name.asc())
    ).all()
    return [{"id": row.id, "full_name": row.full_name, "email": row.email, "role": row.role.value} for row in rows]


@router.get("/interviews/{interview_id}/participants")
def list_interview_participants(
    interview_id: int,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    interview = _org_record(db, Interview, interview_id, user.organization_id)
    rows = db.scalars(
        select(InterviewParticipant)
        .where(InterviewParticipant.interview_id == interview.id)
        .order_by(InterviewParticipant.created_at.asc())
    ).all()
    users = {row.id: row for row in db.scalars(select(User).where(User.id.in_([p.user_id for p in rows]))).all()} if rows else {}
    return [
        {"id": row.id, "user_id": row.user_id, "full_name": users[row.user_id].full_name, "email": users[row.user_id].email, "role": users[row.user_id].role.value}
        for row in rows if row.user_id in users
    ]


@router.post("/interviews/{interview_id}/participants")
def add_interview_participant(
    interview_id: int,
    request: InterviewParticipantRequest,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    interview = _org_record(db, Interview, interview_id, user.organization_id)
    participant = db.scalar(
        select(InterviewParticipant).where(
            InterviewParticipant.interview_id == interview.id,
            InterviewParticipant.user_id == request.user_id,
        )
    )
    target = db.scalar(
        select(User).where(User.id == request.user_id, User.organization_id == user.organization_id, User.is_active.is_(True), User.role != Role.candidate)
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Recruiting user not found")
    if participant is None:
        participant = InterviewParticipant(interview_id=interview.id, user_id=target.id)
        db.add(participant)
        db.commit()
        db.refresh(participant)
    return {"id": participant.id, "user_id": target.id, "full_name": target.full_name, "email": target.email, "role": target.role.value}


@router.delete("/interviews/{interview_id}/participants/{user_id}")
def remove_interview_participant(
    interview_id: int,
    user_id: int,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    interview = _org_record(db, Interview, interview_id, user.organization_id)
    row = db.scalar(select(InterviewParticipant).where(InterviewParticipant.interview_id == interview.id, InterviewParticipant.user_id == user_id))
    if row is not None:
        db.delete(row)
        db.commit()
    return {"status": "removed", "interview_id": interview.id, "user_id": user_id}


class CandidateCollaborationUpdate(BaseModel):
    owner_id: int | None = None
    starred: bool | None = None
    needs_review: bool | None = None
    priority: str | None = Field(default=None, pattern="^(low|normal|high|urgent)$")


class CandidatePortalProfileUpdate(BaseModel):
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, min_length=3, max_length=320)


class OfferTransitionRequest(BaseModel):
    status: str = Field(pattern="^(draft|internal_review|approved|sent|viewed|accepted|declined|expired)$")


@router.patch("/candidates/{candidate_id}/collaboration")
def update_candidate_collaboration(
    candidate_id: int,
    request: CandidateCollaborationUpdate,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    candidate = _org_record(db, Candidate, candidate_id, user.organization_id)
    before = {"owner_id": candidate.owner_id, "starred": candidate.starred, "needs_review": candidate.needs_review, "priority": candidate.priority}
    values = request.model_dump(exclude_unset=True)
    if "owner_id" in values and values["owner_id"] is not None:
        owner = db.scalar(select(User).where(User.id == values["owner_id"], User.organization_id == user.organization_id, User.is_active.is_(True), User.role != Role.candidate))
        if owner is None:
            raise HTTPException(status_code=404, detail="Candidate owner not found")
    for field, value in values.items():
        setattr(candidate, field, value)
    record_audit(db, user, "candidate.collaboration_updated", "candidate", candidate.id, before=before, after=values)
    db.commit()
    db.refresh(candidate)
    owner_name = db.scalar(select(User.full_name).where(User.id == candidate.owner_id)) if candidate.owner_id else None
    return {"owner_id": candidate.owner_id, "owner_name": owner_name, "starred": candidate.starred, "needs_review": candidate.needs_review, "priority": candidate.priority}


@router.get("/interviewer-dashboard")
def interviewer_dashboard(
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    interviews = db.scalars(
        select(Interview)
        .join(Application, Application.id == Interview.application_id)
        .where(
            Application.organization_id == user.organization_id,
            Interview.status != "cancelled",
            (Interview.interviewer_id == user.id) | InterviewParticipant.id.is_not(None),
        )
        .outerjoin(InterviewParticipant, InterviewParticipant.interview_id == Interview.id)
        .order_by(Interview.starts_at.asc())
        .limit(200)
    ).all()
    rows = []
    seen = set()
    for interview in interviews:
        if interview.id in seen:
            continue
        seen.add(interview.id)
        application = db.get(Application, interview.application_id)
        submitted = db.scalar(select(Scorecard.id).where(Scorecard.application_id == application.id, Scorecard.interviewer_id == user.id, Scorecard.submitted_at.is_not(None)))
        rows.append({
            "interview_id": interview.id,
            "application_id": application.id,
            "candidate_name": f"{application.candidate.first_name} {application.candidate.last_name}".strip(),
            "job_title": application.job.title,
            "starts_at": interview.starts_at,
            "duration_minutes": interview.duration_minutes,
            "round_name": interview.round_name,
            "status": interview.status,
            "feedback_deadline": interview.feedback_deadline,
            "scorecard_submitted": bool(submitted),
        })
    return {"user_id": user.id, "interviews": rows, "pending_scorecards": sum(1 for row in rows if not row["scorecard_submitted"] and row["status"] == "completed")}


@router.get("/integrations/calendar/status")
def calendar_integration_status(
    user: User = Depends(require_roles(*READ_ROLES)),
):
    import os
    google_ready = bool(os.getenv("GOOGLE_CALENDAR_CLIENT_ID") and os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET"))
    microsoft_ready = bool(os.getenv("MICROSOFT_CLIENT_ID") and os.getenv("MICROSOFT_CLIENT_SECRET"))
    return {
        "google": {"configured": google_ready, "mode": "oauth" if google_ready else "ics_fallback"},
        "microsoft": {"configured": microsoft_ready, "mode": "oauth" if microsoft_ready else "ics_fallback"},
        "ics_available": True,
        "message": "OAuth sync becomes active after the provider client credentials are configured; ICS remains available as a universal calendar fallback.",
    }


@router.get("/applications/{application_id}/offer/letter", response_class=HTMLResponse)
def offer_letter(
    application_id: int,
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    application = _org_record(db, Application, application_id, user.organization_id)
    offer = db.scalar(select(Offer).where(Offer.application_id == application.id))
    if offer is None:
        raise HTTPException(status_code=404, detail="No offer created for this application")
    candidate = application.candidate
    benefits = "<ul>" + "".join(f"<li>{str(item)}</li>" for item in (offer.benefits or [])) + "</ul>" if offer.benefits else "<p>Benefits as per company policy.</p>"
    ctc = "".join(f"<li>{k}: {v}</li>" for k,v in (offer.ctc_breakdown or {}).items())
    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8"><title>Offer — {offer.position_title}</title>
    <style>body{{font-family:Arial,sans-serif;max-width:760px;margin:48px auto;padding:0 24px;line-height:1.6;color:#18202a}}h1{{margin-bottom:4px}}.meta{{color:#64748b}}.box{{border:1px solid #e2e8f0;border-radius:12px;padding:18px;margin:24px 0}}</style></head>
    <body><h1>Offer of Employment</h1><p class="meta">Blupace Tech</p><div class="box"><strong>Candidate:</strong> {candidate.first_name} {candidate.last_name}<br><strong>Position:</strong> {offer.position_title}<br><strong>Joining date:</strong> {offer.joining_date.strftime("%d %B %Y") if offer.joining_date else "To be confirmed"}<br><strong>Annual CTC:</strong> {offer.annual_ctc or "As discussed"} {offer.currency}</div>
    <h2>Compensation</h2><ul>{ctc or "<li>As per offer terms.</li>"}</ul><h2>Benefits</h2>{benefits}<h2>Probation</h2><p>{offer.probation_period or "As per company policy."}</p>
    <p>Please review this offer through your candidate portal and respond using the secure offer controls.</p></body></html>""")


@router.post("/applications/{application_id}/offer/transition")
def transition_offer(
    application_id: int,
    request: OfferTransitionRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    application = _org_record(db, Application, application_id, user.organization_id)
    offer = db.scalar(select(Offer).where(Offer.application_id == application.id))
    if offer is None:
        raise HTTPException(status_code=404, detail="No offer created for this application")
    target = request.status
    allowed = {
        "draft": {"internal_review"},
        "internal_review": {"approved", "draft"},
        "approved": {"sent", "internal_review"},
        "sent": {"viewed", "accepted", "declined", "expired"},
        "viewed": {"accepted", "declined", "expired"},
        "accepted": set(),
        "declined": set(),
        "expired": set(),
    }
    current = offer.status
    if target not in allowed.get(current, set()):
        if target != current:
            raise HTTPException(status_code=409, detail=f"Cannot move offer from {current} to {target}.")
    before = {"status": current}
    offer.status = target
    now = datetime.now(timezone.utc)
    if target == "approved":
        offer.approved_by_id = user.id
        offer.approved_at = now
    elif target == "sent":
        offer.sent_at = now
    elif target in {"accepted", "declined"}:
        offer.responded_at = now
    record_audit(db, user, "offer.transitioned", "application", application.id, before=before, after={"status": target})
    db.commit()
    return {"status": offer.status, "offer_id": offer.id}


@router.get("/public/application/{token}/documents")
def public_documents(token: str, db: Session = Depends(get_db)):
    try:
        application_id = decode_candidate_portal_token(token)
    except Exception as error:
        raise HTTPException(status_code=401, detail="This candidate portal link is invalid or expired.") from error
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    rows = db.scalars(select(CandidateDocument).where(CandidateDocument.application_id == application.id).order_by(CandidateDocument.created_at.desc())).all()
    return [{"id": row.id, "name": row.name, "content_type": row.content_type, "size_bytes": row.size_bytes, "created_at": row.created_at, "download_url": f"/public/application/{token}/documents/{row.id}"} for row in rows]


@router.post("/public/application/{token}/documents")
async def upload_public_document(token: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        application_id = decode_candidate_portal_token(token)
    except Exception as error:
        raise HTTPException(status_code=401, detail="This candidate portal link is invalid or expired.") from error
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    allowed = {"application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "image/png", "image/jpeg"}
    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Documents must be 15 MB or smaller.")
    if file.content_type not in allowed:
        raise HTTPException(status_code=415, detail="Only PDF, DOCX, PNG and JPEG documents are accepted.")
    import os
    from pathlib import Path
    original = re.sub(r"[^A-Za-z0-9._-]+", "_", file.filename or "document")
    storage_key = f"{application.organization_id}/portal/{application.candidate_id}/{os.urandom(16).hex()}-{original}"
    storage_dir = Path(os.getenv("RESUME_STORAGE_DIR", "./private_uploads"))
    path = storage_dir / storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    row = CandidateDocument(
        organization_id=application.organization_id,
        candidate_id=application.candidate_id,
        application_id=application.id,
        name=original,
        storage_key=storage_key,
        content_type=file.content_type,
        size_bytes=len(content),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "name": row.name, "content_type": row.content_type, "size_bytes": row.size_bytes, "created_at": row.created_at, "download_url": f"/public/application/{token}/documents/{row.id}"}


@router.get("/public/application/{token}/documents/{document_id}")
def download_public_document(token: str, document_id: int, db: Session = Depends(get_db)):
    try:
        application_id = decode_candidate_portal_token(token)
    except Exception as error:
        raise HTTPException(status_code=401, detail="This candidate portal link is invalid or expired.") from error
    row = db.scalar(select(CandidateDocument).where(CandidateDocument.id == document_id, CandidateDocument.application_id == application_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    import os
    from pathlib import Path
    path = Path(os.getenv("RESUME_STORAGE_DIR", "./private_uploads")) / row.storage_key
    if not path.exists():
        raise HTTPException(status_code=404, detail="Stored document is no longer available")
    return FileResponse(path, media_type=row.content_type, filename=row.name)


@router.patch("/public/application/{token}/profile")
def update_public_candidate_profile(token: str, request: CandidatePortalProfileUpdate, db: Session = Depends(get_db)):
    try:
        application_id = decode_candidate_portal_token(token)
    except Exception as error:
        raise HTTPException(status_code=401, detail="This candidate portal link is invalid or expired.") from error
    application = db.scalar(select(Application).where(Application.id == application_id).options(selectinload(Application.candidate)))
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    candidate = application.candidate
    values = request.model_dump(exclude_unset=True)
    if "email" in values and values["email"]:
        email = values["email"].strip().lower()
        duplicate = db.scalar(select(Candidate).where(Candidate.organization_id == application.organization_id, Candidate.email == email, Candidate.id != candidate.id))
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="That email is already in use by another candidate profile.")
        candidate.email = email
    if "phone" in values:
        candidate.phone = (values["phone"] or "").strip() or None
    db.commit()
    return {"email": candidate.email, "phone": candidate.phone}


def _recruitment_rows(db: Session, organization_id: int):
    applications = db.scalars(
        select(Application)
        .where(Application.organization_id == organization_id)
        .options(selectinload(Application.job), selectinload(Application.candidate), selectinload(Application.stage))
        .order_by(Application.applied_at.desc())
    ).all()
    application_ids = [app.id for app in applications]
    interview_counts = {}
    if application_ids:
        for app_id, count in db.execute(select(Interview.application_id, func.count(Interview.id)).where(Interview.application_id.in_(application_ids)).group_by(Interview.application_id)).all():
            interview_counts[app_id] = count
    offers = {o.application_id: o for o in db.scalars(select(Offer).where(Offer.application_id.in_(application_ids))).all()} if application_ids else {}
    rows = []
    for app in applications:
        candidate = app.candidate
        offer = offers.get(app.id)
        rows.append([
            app.id,
            app.job.title,
            f"{candidate.first_name} {candidate.last_name}".strip(),
            candidate.email,
            candidate.source or "",
            app.stage.name if app.stage else "Applied",
            app.status,
            app.applied_at.isoformat(),
            interview_counts.get(app.id, 0),
            offer.status if offer else "",
            offer.annual_ctc if offer else "",
            offer.currency if offer else "",
            offer.joining_date.isoformat() if offer and offer.joining_date else "",
            ", ".join(_candidate_tags(candidate)),
        ])
    return rows


@router.get("/reports/recruitment.xlsx")
def recruitment_report_xlsx(
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    from openpyxl import Workbook
    output = io.BytesIO()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Recruitment"
    headers = ["Application ID", "Job", "Candidate", "Email", "Source", "Stage", "Application Status", "Applied At", "Interview Rounds", "Offer Status", "Offer CTC", "Currency", "Joining Date", "Tags"]
    sheet.append(headers)
    for row in _recruitment_rows(db, user.organization_id):
        sheet.append(row)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column in sheet.columns:
        max_len = min(48, max(len(str(cell.value or "")) for cell in column) + 2)
        sheet.column_dimensions[column[0].column_letter].width = max_len
    workbook.save(output)
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="blupace-recruitment-report.xlsx"'},
    )


@router.get("/reports/recruitment.pdf")
def recruitment_report_pdf(
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas
    output = io.BytesIO()
    page = landscape(A4)
    pdf = canvas.Canvas(output, pagesize=page)
    width, height = page
    pdf.setTitle("Blupace Recruitment Report")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(36, height - 40, "Blupace Tech — Recruitment Report")
    pdf.setFont("Helvetica", 8)
    rows = _recruitment_rows(db, user.organization_id)
    headers = ["ID", "Job", "Candidate", "Stage", "Status", "Applied", "Interviews", "Offer"]
    x = [36, 64, 180, 330, 400, 465, 560, 620]
    y = height - 65
    pdf.setFont("Helvetica-Bold", 8)
    for xx, header in zip(x, headers):
        pdf.drawString(xx, y, header)
    pdf.setFont("Helvetica", 7)
    for index, row in enumerate(rows):
        y -= 14
        if y < 36:
            pdf.showPage()
            pdf.setFont("Helvetica-Bold", 16)
            pdf.drawString(36, height - 40, "Blupace Tech — Recruitment Report")
            pdf.setFont("Helvetica-Bold", 8)
            for xx, header in zip(x, headers):
                pdf.drawString(xx, height - 65, header)
            pdf.setFont("Helvetica", 7)
            y = height - 79
        values = [row[0], str(row[1])[:22], str(row[2])[:24], row[5], row[6], str(row[7])[:10], row[8], row[9]]
        for xx, value in zip(x, values):
            pdf.drawString(xx, y, str(value))
    pdf.save()
    return Response(
        content=output.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="blupace-recruitment-report.pdf"'},
    )
