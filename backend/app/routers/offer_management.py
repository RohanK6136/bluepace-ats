from datetime import datetime, timezone
import html
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column, Session

from app.database import Base, get_db
from app.models import Application, Offer, Role, User
from app.security import decode_candidate_portal_token, require_roles
from app.services.workflow import queue_application_email, record_audit
from app.services.email_notifications import deliver_outbox_email

router = APIRouter()
READ_ROLES = (Role.admin, Role.recruiter, Role.hiring_manager, Role.interviewer)
WRITE_ROLES = (Role.admin, Role.recruiter, Role.hiring_manager)
APPROVAL_ROLES = (Role.admin, Role.hiring_manager)


class OfferRevision(Base):
    __tablename__ = "offer_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    before_data: Mapped[dict] = mapped_column(JSON, default=dict)
    after_data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class OfferApproval(Base):
    __tablename__ = "offer_approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), index=True)
    approver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="approved")
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class OfferAcceptanceRecord(Base):
    __tablename__ = "offer_acceptance_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(30))
    acknowledgement: Mapped[str] = mapped_column(Text)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    ip_address: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    portal_token_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)


class OfferCreateRequest(BaseModel):
    application_id: int
    position_title: str = Field(min_length=1, max_length=200)
    annual_ctc: str | None = Field(default=None, max_length=100)
    currency: str = Field(default="INR", min_length=3, max_length=10)
    joining_date: datetime | None = None
    probation_period: str | None = Field(default=None, max_length=100)
    benefits: list[str] = Field(default_factory=list, max_length=30)
    ctc_breakdown: dict = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=5000)
    expires_at: datetime | None = None


class OfferPatchRequest(BaseModel):
    position_title: str | None = Field(default=None, min_length=1, max_length=200)
    annual_ctc: str | None = Field(default=None, max_length=100)
    currency: str | None = Field(default=None, min_length=3, max_length=10)
    joining_date: datetime | None = None
    probation_period: str | None = Field(default=None, max_length=100)
    benefits: list[str] | None = Field(default=None, max_length=30)
    ctc_breakdown: dict | None = None
    notes: str | None = Field(default=None, max_length=5000)
    expires_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=1000)


class OfferTransitionRequest(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


class OfferResponseRequest(BaseModel):
    status: str = Field(pattern="^(accepted|declined)$")
    acknowledgement: str | None = Field(default=None, max_length=2000)


def _now():
    return datetime.now(timezone.utc)


def _org_offer(db: Session, offer_id: int, organization_id: int) -> Offer:
    offer = db.scalar(select(Offer).where(Offer.id == offer_id, Offer.organization_id == organization_id))
    if offer is None:
        raise HTTPException(status_code=404, detail="Offer not found")
    return offer


def _offer_data(offer: Offer) -> dict:
    return {
        "id": offer.id,
        "application_id": offer.application_id,
        "position_title": offer.position_title,
        "annual_ctc": offer.annual_ctc,
        "currency": offer.currency,
        "joining_date": offer.joining_date.isoformat() if offer.joining_date else None,
        "probation_period": offer.probation_period,
        "benefits": offer.benefits or [],
        "ctc_breakdown": offer.ctc_breakdown or {},
        "notes": offer.notes,
        "status": offer.status,
        "approved_by_id": offer.approved_by_id,
        "approved_at": offer.approved_at.isoformat() if offer.approved_at else None,
        "sent_at": offer.sent_at.isoformat() if offer.sent_at else None,
        "viewed_at": offer.viewed_at.isoformat() if offer.viewed_at else None,
        "responded_at": offer.responded_at.isoformat() if offer.responded_at else None,
        "expires_at": offer.expires_at.isoformat() if offer.expires_at else None,
        "revision": offer.revision,
        "offer_letter_url": offer.offer_letter_url,
    }


def _serialize_offer(db: Session, offer: Offer) -> dict:
    revisions = db.scalars(select(OfferRevision).where(OfferRevision.offer_id == offer.id).order_by(OfferRevision.created_at.desc())).all()
    approvals = db.scalars(select(OfferApproval).where(OfferApproval.offer_id == offer.id).order_by(OfferApproval.created_at.desc())).all()
    acceptances = db.scalars(select(OfferAcceptanceRecord).where(OfferAcceptanceRecord.offer_id == offer.id).order_by(OfferAcceptanceRecord.accepted_at.desc())).all()
    return {
        **_offer_data(offer),
        "revisions": [{"id": r.id, "revision": r.revision, "actor_id": r.actor_id, "reason": r.reason, "before": r.before_data, "after": r.after_data, "created_at": r.created_at} for r in revisions],
        "approvals": [{"id": a.id, "approver_id": a.approver_id, "status": a.status, "comment": a.comment, "created_at": a.created_at} for a in approvals],
        "acceptance_records": [{"id": a.id, "action": a.action, "acknowledgement": a.acknowledgement, "accepted_at": a.accepted_at, "ip_address": a.ip_address, "user_agent": a.user_agent} for a in acceptances],
    }


def _ensure_open(offer: Offer):
    if offer.expires_at and offer.expires_at < _now() and offer.status in {"sent", "viewed"}:
        offer.status = "expired"
        offer.responded_at = _now()
    if offer.status in {"accepted", "declined", "expired"}:
        raise HTTPException(status_code=409, detail=f"Offer is already {offer.status}.")


def _offer_letter_html(application: Application, offer: Offer) -> str:
    candidate = application.candidate
    benefits = "".join(f"<li>{html.escape(str(item))}</li>" for item in (offer.benefits or [])) or "<li>As per company policy</li>"
    breakdown = "".join(
        f"<tr><td>{html.escape(str(key))}</td><td>{html.escape(str(value))}</td></tr>"
        for key, value in (offer.ctc_breakdown or {}).items()
    ) or "<tr><td>Total CTC</td><td>{}</td></tr>".format(html.escape(offer.annual_ctc or "As specified in the offer"))
    joining = offer.joining_date.strftime("%d %B %Y") if offer.joining_date else "To be mutually agreed"
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>Offer Letter - {html.escape(candidate.first_name)} {html.escape(candidate.last_name)}</title><style>body{{font-family:Arial,sans-serif;max-width:820px;margin:40px auto;padding:40px;color:#172033}}h1{{font-size:28px}}table{{width:100%;border-collapse:collapse;margin:20px 0}}td{{border:1px solid #ddd;padding:10px}}.meta{{background:#f6f8fb;padding:16px;border-radius:10px}}footer{{margin-top:50px;color:#667085;font-size:12px}}</style></head><body><p>Blupace Tech Recruiting</p><h1>Offer of Employment</h1><p>Dear {html.escape(candidate.first_name)},</p><p>We are pleased to offer you the position of <strong>{html.escape(offer.position_title)}</strong>.</p><div class='meta'><p><strong>Annual CTC:</strong> {html.escape(offer.annual_ctc or "As specified")} {html.escape(offer.currency)}</p><p><strong>Joining date:</strong> {html.escape(joining)}</p><p><strong>Probation:</strong> {html.escape(offer.probation_period or "As per company policy")}</p></div><h2>CTC breakdown</h2><table><tbody>{breakdown}</tbody></table><h2>Benefits</h2><ul>{benefits}</ul><p>{html.escape(offer.notes or "We look forward to welcoming you to the team.")}</p><p>Sincerely,<br><strong>Blupace Tech Recruiting</strong></p><footer>This document is generated from BluePace ATS offer revision {offer.revision}.</footer></body></html>"""


@router.get("/offer-management/offers")
def list_offers(user: User = Depends(require_roles(*READ_ROLES)), db: Session = Depends(get_db)):
    offers = db.scalars(select(Offer).where(Offer.organization_id == user.organization_id).order_by(Offer.updated_at.desc())).all()
    return [_serialize_offer(db, offer) for offer in offers]


@router.post("/offer-management/offers")
def create_offer(request: OfferCreateRequest, user: User = Depends(require_roles(*WRITE_ROLES)), db: Session = Depends(get_db)):
    application = db.scalar(select(Application).where(Application.id == request.application_id, Application.organization_id == user.organization_id))
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    existing = db.scalar(select(Offer).where(Offer.application_id == application.id))
    if existing is not None:
        raise HTTPException(status_code=409, detail="An offer already exists for this application")
    offer = Offer(
        organization_id=user.organization_id,
        application_id=application.id,
        position_title=request.position_title,
        annual_ctc=request.annual_ctc,
        currency=request.currency,
        joining_date=request.joining_date,
        notes=request.notes,
        ctc_breakdown=request.ctc_breakdown,
        benefits=request.benefits,
        probation_period=request.probation_period,
        expires_at=request.expires_at,
        status="draft",
        revision=1,
        created_by_id=user.id,
    )
    db.add(offer)
    db.flush()
    record_audit(db, user, "offer.created", "offer", offer.id, after=_offer_data(offer))
    db.commit()
    db.refresh(offer)
    return _serialize_offer(db, offer)


@router.patch("/offer-management/offers/{offer_id}")
def update_offer(offer_id: int, request: OfferPatchRequest, user: User = Depends(require_roles(*WRITE_ROLES)), db: Session = Depends(get_db)):
    offer = _org_offer(db, offer_id, user.organization_id)
    if offer.status not in {"draft", "internal_review"}:
        raise HTTPException(status_code=409, detail="Only draft or internally reviewed offers can be edited. Create a revision before changing an approved/sent offer.")
    before = _offer_data(offer)
    changes = request.model_dump(exclude_unset=True, exclude={"reason"})
    for key, value in changes.items():
        setattr(offer, key, value)
    offer.revision = int(offer.revision or 1) + 1
    after = _offer_data(offer)
    revision = OfferRevision(organization_id=user.organization_id, offer_id=offer.id, revision=offer.revision, actor_id=user.id, reason=request.reason or "Offer updated", before_data=before, after_data=after)
    db.add(revision)
    record_audit(db, user, "offer.revised", "offer", offer.id, before=before, after=after)
    db.commit()
    db.refresh(offer)
    return _serialize_offer(db, offer)


@router.post("/offer-management/offers/{offer_id}/submit-review")
def submit_offer_review(offer_id: int, request: OfferTransitionRequest, user: User = Depends(require_roles(*WRITE_ROLES)), db: Session = Depends(get_db)):
    offer = _org_offer(db, offer_id, user.organization_id)
    if offer.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft offers can enter internal review.")
    offer.status = "internal_review"
    record_audit(db, user, "offer.internal_review", "offer", offer.id, after={"status": offer.status, "comment": request.comment})
    db.commit()
    return _serialize_offer(db, offer)


@router.post("/offer-management/offers/{offer_id}/approve")
def approve_offer(offer_id: int, request: OfferTransitionRequest, user: User = Depends(require_roles(*APPROVAL_ROLES)), db: Session = Depends(get_db)):
    offer = _org_offer(db, offer_id, user.organization_id)
    if offer.status != "internal_review":
        raise HTTPException(status_code=409, detail="Offer must be in internal review before approval.")
    approval = OfferApproval(organization_id=user.organization_id, offer_id=offer.id, approver_id=user.id, status="approved", comment=request.comment)
    db.add(approval)
    offer.status = "approved"
    offer.approved_by_id = user.id
    offer.approved_at = _now()
    record_audit(db, user, "offer.approved", "offer", offer.id, after={"status": offer.status, "approved_by_id": user.id})
    db.commit()
    return _serialize_offer(db, offer)


@router.post("/offer-management/offers/{offer_id}/send")
def send_offer_v2(offer_id: int, background_tasks: BackgroundTasks, user: User = Depends(require_roles(*WRITE_ROLES)), db: Session = Depends(get_db)):
    offer = _org_offer(db, offer_id, user.organization_id)
    application = db.get(Application, offer.application_id)
    if application is None or application.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Application not found")
    if offer.status != "approved":
        raise HTTPException(status_code=409, detail="Offer must be approved before it can be sent.")
    offer.status = "sent"
    offer.sent_at = _now()
    subject = f"Offer from Blupace Tech: {offer.position_title}"
    body = f"Hello {application.candidate.first_name},\\n\\nYour offer for {offer.position_title} is ready in your secure candidate portal. Annual CTC: {offer.annual_ctc or 'As specified'} {offer.currency}.\\n\\nPlease review and respond using your candidate portal."
    email_id = queue_application_email(db, application, subject, body)
    record_audit(db, user, "offer.sent", "offer", offer.id, after={"status": offer.status, "revision": offer.revision})
    db.commit()
    background_tasks.add_task(deliver_outbox_email, email_id)
    return _serialize_offer(db, offer)


@router.post("/offer-management/offers/{offer_id}/revise")
def revise_offer(offer_id: int, request: OfferPatchRequest, user: User = Depends(require_roles(*WRITE_ROLES)), db: Session = Depends(get_db)):
    offer = _org_offer(db, offer_id, user.organization_id)
    if offer.status not in {"approved", "sent", "viewed"}:
        raise HTTPException(status_code=409, detail="Use the normal edit action for draft/internal review offers.")
    if offer.status in {"sent", "viewed"}:
        offer.status = "draft"
        offer.approved_by_id = None
        offer.approved_at = None
    before = _offer_data(offer)
    changes = request.model_dump(exclude_unset=True, exclude={"reason"})
    for key, value in changes.items():
        setattr(offer, key, value)
    offer.revision = int(offer.revision or 1) + 1
    after = _offer_data(offer)
    db.add(OfferRevision(organization_id=user.organization_id, offer_id=offer.id, revision=offer.revision, actor_id=user.id, reason=request.reason or "Offer revision", before_data=before, after_data=after))
    record_audit(db, user, "offer.revised", "offer", offer.id, before=before, after=after)
    db.commit()
    return _serialize_offer(db, offer)


@router.get("/offer-management/offers/{offer_id}/letter", response_class=HTMLResponse)
def generate_offer_letter(offer_id: int, user: User = Depends(require_roles(*READ_ROLES)), db: Session = Depends(get_db)):
    offer = _org_offer(db, offer_id, user.organization_id)
    application = db.get(Application, offer.application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return HTMLResponse(_offer_letter_html(application, offer), headers={"Content-Disposition": f'inline; filename="offer-{offer.id}-rev-{offer.revision}.html"'})


@router.post("/offer-management/offers/{offer_id}/expire")
def expire_offer(offer_id: int, user: User = Depends(require_roles(*WRITE_ROLES)), db: Session = Depends(get_db)):
    offer = _org_offer(db, offer_id, user.organization_id)
    if offer.status not in {"sent", "viewed"}:
        raise HTTPException(status_code=409, detail="Only sent or viewed offers can expire.")
    offer.status = "expired"
    offer.responded_at = _now()
    record_audit(db, user, "offer.expired", "offer", offer.id, after={"status": offer.status})
    db.commit()
    return _serialize_offer(db, offer)


@router.get("/public/application/{token}/offer-letter", response_class=HTMLResponse)
def public_offer_letter(token: str, db: Session = Depends(get_db)):
    try:
        application_id = decode_candidate_portal_token(token)
    except Exception as error:
        raise HTTPException(status_code=401, detail="This candidate portal link is invalid or expired.") from error
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    offer = db.scalar(select(Offer).where(Offer.application_id == application.id))
    if offer is None:
        raise HTTPException(status_code=404, detail="No offer is available")
    if offer.status == "sent":
        offer.status = "viewed"
        offer.viewed_at = _now()
        db.commit()
    return HTMLResponse(_offer_letter_html(application, offer), headers={"Content-Disposition": f'inline; filename="offer-{offer.id}.html"'})


@router.post("/public/application/{token}/offer-response")
def public_offer_response_v2(token: str, request: OfferResponseRequest, http_request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        application_id = decode_candidate_portal_token(token)
    except Exception as error:
        raise HTTPException(status_code=401, detail="This candidate portal link is invalid or expired.") from error
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    offer = db.scalar(select(Offer).where(Offer.application_id == application.id))
    if offer is None:
        raise HTTPException(status_code=404, detail="No offer is available for this application")
    if offer.expires_at and offer.expires_at < _now() and offer.status in {"sent", "viewed"}:
        offer.status = "expired"
        offer.responded_at = _now()
    if offer.status in {"accepted", "declined", "expired"}:
        return {"status": offer.status, "message": f"The offer is already marked {offer.status}."}
    if offer.status not in {"sent", "viewed"}:
        raise HTTPException(status_code=409, detail="This offer is not currently open for a candidate response.")
    offer.status = request.status
    offer.responded_at = _now()
    record = OfferAcceptanceRecord(
        organization_id=application.organization_id,
        offer_id=offer.id,
        application_id=application.id,
        action=request.status,
        acknowledgement=request.acknowledgement or ("Candidate " + request.status + " the offer through the secure candidate portal."),
        accepted_at=offer.responded_at,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
    )
    db.add(record)
    record_audit(db, None, "offer.responded", "offer", offer.id, after={"status": offer.status, "acceptance_record_id": record.id}) if False else None
    subject = f"Offer {request.status}: {offer.position_title}"
    body = f"Hello {application.candidate.first_name},\\n\\nYour offer response has been recorded as {request.status}.\\n\\nBlupace Tech Recruiting"
    email_id = queue_application_email(db, application, subject, body)
    db.commit()
    background_tasks.add_task(deliver_outbox_email, email_id)
    return {"status": offer.status, "message": f"Offer response recorded as {request.status}.", "acceptance_record_id": record.id}


@router.get("/offer-management/offers/{offer_id}/acceptance")
def offer_acceptance(offer_id: int, user: User = Depends(require_roles(*READ_ROLES)), db: Session = Depends(get_db)):
    offer = _org_offer(db, offer_id, user.organization_id)
    return [{"id": row.id, "action": row.action, "acknowledgement": row.acknowledgement, "accepted_at": row.accepted_at, "ip_address": row.ip_address, "user_agent": row.user_agent} for row in db.scalars(select(OfferAcceptanceRecord).where(OfferAcceptanceRecord.offer_id == offer.id).order_by(OfferAcceptanceRecord.accepted_at.desc())).all()]
