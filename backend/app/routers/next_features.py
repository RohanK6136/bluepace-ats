from datetime import datetime, timezone
from difflib import SequenceMatcher
import csv
import io
import re
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import Response
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
    Interview,
    Job,
    Offer,
    Role,
    Stage,
    TalentPoolMembership,
    User,
)
from app.security import (
    decode_candidate_portal_token,
    get_current_user,
    require_roles,
)
from app.services.email_notifications import deliver_outbox_email
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


class AssistantRequest(BaseModel):
    question: str = Field(default="Give me a factual summary of this application.", max_length=2000)


def _org_record(db: Session, model, record_id: int, organization_id: int):
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
        keep.cv_summary = list(dict.fromkeys((_candidate_tags(keep) + [str(v) for v in duplicate.cv_summary])))

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
        "email_id": email_id,
    }


@router.post("/interviews/{interview_id}/cancel")
def cancel_interview(
    interview_id: int,
    background_tasks: BackgroundTasks,
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
    record_audit(db, user, "interview.cancelled", "interview", interview.id, after={"status": "cancelled"})
    db.commit()
    background_tasks.add_task(deliver_outbox_email, email_id)
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
        offer_payload = {
            "id": offer.id,
            "position_title": offer.position_title,
            "annual_ctc": offer.annual_ctc,
            "currency": offer.currency,
            "joining_date": offer.joining_date,
            "offer_letter_url": offer.offer_letter_url,
            "status": offer.status,
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
    if offer.status in {"accepted", "declined", "expired"}:
        return {"status": offer.status, "message": f"The offer is already marked {offer.status}."}

    offer.status = request.status
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
    offer.status = "sent"
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
