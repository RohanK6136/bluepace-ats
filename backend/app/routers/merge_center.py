from difflib import SequenceMatcher
from copy import deepcopy
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (Application, Candidate, CandidateComment, CandidateFollower, CandidateMergeAudit, CandidateTag, Interview, Note, Offer, Role, Scorecard, User)
from app.schemas import CandidateDuplicateRead, CandidateMergeAuditRead, CandidateMergeComparisonRead, CandidateMergeField, CandidateMergeRequest, CandidateSummary
from app.security import require_roles

router = APIRouter(prefix="/merge-center", tags=["candidate-merge"])
READ_ROLES = (Role.admin, Role.recruiter, Role.hiring_manager, Role.interviewer)
WRITE_ROLES = (Role.admin, Role.recruiter, Role.hiring_manager)

def _norm(value):
    return " ".join(str(value or "").strip().casefold().split())

def _phone(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())

def _name_score(a, b):
    return int(round(SequenceMatcher(None, _norm(a), _norm(b)).ratio() * 100))

def _candidate_score(a, b):
    signals = []
    if _norm(a.email) and _norm(a.email) == _norm(b.email): signals.append((100, "email"))
    if _phone(a.phone) and _phone(a.phone) == _phone(b.phone): signals.append((100, "phone"))
    name = _name_score(f"{a.first_name} {a.last_name}", f"{b.first_name} {b.last_name}")
    if name >= 70: signals.append((name, "name"))
    email_local = _norm(a.email).split("@")[0] if "@" in _norm(a.email) else ""
    email_local_b = _norm(b.email).split("@")[0] if "@" in _norm(b.email) else ""
    if email_local and email_local == email_local_b: signals.append((95, "email_name"))
    score = max((value for value, _ in signals), default=0)
    if len(signals) >= 2 and score < 100: score = min(99, score + 8)
    return score, sorted({label for _, label in signals})

def _summary(candidate):
    return CandidateSummary(id=candidate.id, first_name=candidate.first_name, last_name=candidate.last_name, email=candidate.email, source=candidate.source, resume_data=candidate.resume_data)

def _profile(candidate):
    return candidate.resume_data if isinstance(candidate.resume_data, dict) else {}

@router.get("/duplicates", response_model=list[CandidateDuplicateRead])
def duplicate_candidates(user=Depends(require_roles(*READ_ROLES)), db: Session = Depends(get_db)):
    candidates = db.scalars(select(Candidate).where(Candidate.organization_id == user.organization_id, Candidate.archived.is_(False), Candidate.merged_into_id.is_(None)).order_by(Candidate.created_at.desc()).limit(1000)).all()
    results = []
    for index, candidate in enumerate(candidates):
        for other in candidates[index + 1:]:
            score, matched = _candidate_score(candidate, other)
            if score < 70: continue
            results.append({"id": other.id, "first_name": other.first_name, "last_name": other.last_name, "email": other.email, "phone": other.phone, "source": other.source, "similarity_score": score, "matched_by": matched, "_pair": (candidate.id, other.id)})
    results.sort(key=lambda item: (-item["similarity_score"], item["id"]))
    return results[:100]

@router.get("/compare/{survivor_id}/{merged_id}", response_model=CandidateMergeComparisonRead)
def compare_candidates(survivor_id: int, merged_id: int, user=Depends(require_roles(*READ_ROLES)), db: Session = Depends(get_db)):
    if survivor_id == merged_id: raise HTTPException(400, "Choose two different candidates")
    survivor = db.scalar(select(Candidate).where(Candidate.id == survivor_id, Candidate.organization_id == user.organization_id))
    merged = db.scalar(select(Candidate).where(Candidate.id == merged_id, Candidate.organization_id == user.organization_id))
    if not survivor or not merged: raise HTTPException(404, "Candidate not found")
    fields = []
    for field in ("first_name", "last_name", "email", "phone", "linkedin_url", "source", "resume_storage_key", "cv_summary", "tags", "owner_id", "starred", "needs_review", "priority"):
        left, right = getattr(survivor, field), getattr(merged, field)
        recommended = "survivor" if left not in (None, "", []) else "merged"
        fields.append(CandidateMergeField(field=field, survivor_value=left, merged_value=right, recommended=recommended))
    applications = db.scalars(select(Application).where(Application.organization_id == user.organization_id, Application.candidate_id.in_([survivor.id, merged.id]))).all()
    app_ids = [a.id for a in applications]
    notes = db.scalars(select(Note).where(Note.organization_id == user.organization_id, Note.application_id.in_(app_ids))).all() if app_ids else []
    left_profile, right_profile = _profile(survivor), _profile(merged)
    employment = list(left_profile.get("experience") or []) + [x for x in (right_profile.get("experience") or []) if x not in (left_profile.get("experience") or [])]
    projects = list(left_profile.get("projects") or left_profile.get("university_projects") or []) + [x for x in (right_profile.get("projects") or right_profile.get("university_projects") or []) if x not in (left_profile.get("projects") or left_profile.get("university_projects") or [])]
    return CandidateMergeComparisonRead(survivor=_summary(survivor), merged=_summary(merged), fields=fields, employment_history=employment, projects=projects, notes=[{"id": n.id, "application_id": n.application_id, "body": n.body, "author_id": n.author_id, "created_at": n.created_at} for n in notes], applications=[{"id": a.id, "job_id": a.job_id, "job_title": a.job.title if a.job else "", "stage_name": a.stage.name if a.stage else None, "status": a.status, "candidate_id": a.candidate_id, "applied_at": a.applied_at} for a in applications])

@router.post("/merge")
def merge_candidates(request: CandidateMergeRequest, user=Depends(require_roles(*WRITE_ROLES)), db: Session = Depends(get_db)):
    if request.survivor_id == request.merged_id: raise HTTPException(400, "Choose two different candidates")
    survivor = db.scalar(select(Candidate).where(Candidate.id == request.survivor_id, Candidate.organization_id == user.organization_id))
    merged = db.scalar(select(Candidate).where(Candidate.id == request.merged_id, Candidate.organization_id == user.organization_id))
    if not survivor or not merged: raise HTTPException(404, "Candidate not found")
    if merged.archived or merged.merged_into_id: raise HTTPException(409, "Candidate has already been merged")
    allowed = {"first_name", "last_name", "email", "phone", "linkedin_url", "source", "resume_storage_key", "resume_data", "cv_summary", "tags", "owner_id", "starred", "needs_review", "priority"}
    if any(field not in allowed or choice not in {"survivor", "merged"} for field, choice in request.field_choices.items()): raise HTTPException(400, "Invalid merge field selection")
    before_survivor = {field: deepcopy(getattr(survivor, field)) for field in allowed}
    before_merged = {field: deepcopy(getattr(merged, field)) for field in allowed}
    for field, choice in request.field_choices.items():
        setattr(survivor, field, deepcopy(getattr(merged if choice == "merged" else survivor, field)))
    # Preserve both resumes' employment/project evidence regardless of the selected resume source.
    sp, mp = _profile(survivor), _profile(merged)
    combined = deepcopy(sp)
    for key in ("experience", "projects", "university_projects"):
        values = list(sp.get(key) or [])
        for value in mp.get(key) or []:
            if value not in values: values.append(value)
        if values: combined[key] = values
    survivor.resume_data = combined
    if not survivor.tags: survivor.tags = []
    for tag in merged.tags or []:
        if tag not in survivor.tags: survivor.tags.append(tag)
    # Repoint or consolidate application history.
    survivor_apps = db.scalars(select(Application).where(Application.organization_id == user.organization_id, Application.candidate_id == survivor.id)).all()
    survivor_by_job = {a.job_id: a for a in survivor_apps}
    merged_apps = db.scalars(select(Application).where(Application.organization_id == user.organization_id, Application.candidate_id == merged.id)).all()
    moved_apps, collapsed_apps = [], []
    for app in merged_apps:
        target_app = survivor_by_job.get(app.job_id)
        if target_app is None:
            app.candidate_id = survivor.id; survivor_by_job[app.job_id] = app; moved_apps.append(app.id); continue
        source_notes = db.scalars(select(Note).where(Note.application_id == app.id)).all()
        for note in source_notes: note.application_id = target_app.id
        for scorecard in db.scalars(select(Scorecard).where(Scorecard.application_id == app.id)).all(): scorecard.application_id = target_app.id
        for interview in db.scalars(select(Interview).where(Interview.application_id == app.id)).all(): interview.application_id = target_app.id
        source_offer = db.scalar(select(Offer).where(Offer.application_id == app.id))
        target_offer = db.scalar(select(Offer).where(Offer.application_id == target_app.id))
        if source_offer and not target_offer: source_offer.application_id = target_app.id
        app.status = "merged"; collapsed_apps.append({"source_application_id": app.id, "target_application_id": target_app.id})
    for comment in db.scalars(select(CandidateComment).where(CandidateComment.candidate_id == merged.id)).all(): comment.candidate_id = survivor.id
    existing_tags = {t.name.casefold(): t for t in db.scalars(select(CandidateTag).where(CandidateTag.candidate_id == survivor.id)).all()}
    for tag in db.scalars(select(CandidateTag).where(CandidateTag.candidate_id == merged.id)).all():
        if tag.name.casefold() in existing_tags: db.delete(tag)
        else: tag.candidate_id = survivor.id
    existing_followers = {f.user_id for f in db.scalars(select(CandidateFollower).where(CandidateFollower.candidate_id == survivor.id)).all()}
    for follower in db.scalars(select(CandidateFollower).where(CandidateFollower.candidate_id == merged.id)).all():
        if follower.user_id in existing_followers: db.delete(follower)
        else: follower.candidate_id = survivor.id
    merged.merged_into_id = survivor.id; merged.archived = True
    # Free the unique email before applying a source-email choice to the survivor.
    if survivor.email == merged.email:
        merged.email = f"merged-{merged.id}-{survivor.id}@invalid.local"
    db.flush()
    summary = {"moved_applications": moved_apps, "collapsed_applications": collapsed_apps, "employment_items": len(combined.get("experience") or []), "project_items": len(combined.get("projects") or combined.get("university_projects") or []), "notes_merged": len(db.scalars(select(Note).where(Note.application_id.in_([a.id for a in survivor_apps]))).all()) if survivor_apps else 0}
    audit = CandidateMergeAudit(organization_id=user.organization_id, actor_id=user.id, survivor_candidate_id=survivor.id, merged_candidate_id=merged.id, field_choices=request.field_choices, before_survivor=before_survivor, before_merged=before_merged, merge_summary=summary)
    db.add(audit)
    db.commit()
    return {"success": True, "survivor_id": survivor.id, "merged_id": merged.id, "summary": summary, "audit_id": audit.id}

@router.get("/history", response_model=list[CandidateMergeAuditRead])
def merge_history(user=Depends(require_roles(*READ_ROLES)), db: Session = Depends(get_db)):
    rows = db.scalars(select(CandidateMergeAudit).where(CandidateMergeAudit.organization_id == user.organization_id).order_by(CandidateMergeAudit.created_at.desc()).limit(200)).all()
    result = []
    for row in rows:
        actor = db.get(User, row.actor_id)
        result.append(CandidateMergeAuditRead(id=row.id, actor_id=row.actor_id, actor_name=actor.full_name if actor else "Unknown", survivor_candidate_id=row.survivor_candidate_id, merged_candidate_id=row.merged_candidate_id, field_choices=row.field_choices or {}, merge_summary=row.merge_summary or {}, created_at=row.created_at))
    return result

