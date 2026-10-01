from app.models import Application, AuditLog, Email, Job, Stage, User

PIPELINE_STAGES = ("Applied", "Screening", "Interview", "Offer", "Hired", "Rejected")
TERMINAL_STAGES = {"Hired": "hired", "Rejected": "rejected"}


def ensure_job_stages(db, job: Job):
    existing = {stage.name: stage for stage in db.query(Stage).filter_by(job_id=job.id).all()}
    for position, name in enumerate(PIPELINE_STAGES, start=1):
        if name not in existing:
            stage = Stage(job_id=job.id, name=name, position=position)
            db.add(stage)
            existing[name] = stage
    db.flush()
    return existing


def record_audit(db, user: User, action: str, entity_type: str, entity_id: int, before=None, after=None):
    db.add(
        AuditLog(
            organization_id=user.organization_id,
            actor_id=user.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_data=before,
            after_data=after,
        )
    )


def queue_application_email(
    db,
    application: Application,
    subject: str,
    body: str,
    *,
    attachment_filename: str | None = None,
    attachment_content: str | None = None,
    attachment_content_type: str | None = None,
) -> int:
    email = Email(
        organization_id=application.organization_id,
        application_id=application.id,
        recipient=application.candidate.email,
        subject=subject,
        body=body,
        status="pending",
        attachment_filename=attachment_filename,
        attachment_content=attachment_content,
        attachment_content_type=attachment_content_type,
    )
    db.add(email)
    db.flush()
    return email.id


def serialize_application(application: Application) -> dict:
    candidate = application.candidate
    resume_data = {
        key: value
        for key, value in (candidate.resume_data or {}).items()
        if key != "raw_text"
    }
    return {
        "id": application.id,
        "job_id": application.job_id,
        "candidate_id": application.candidate_id,
        "job_title": application.job.title,
        "stage_id": application.stage_id,
        "stage_name": application.stage.name if application.stage else None,
        "status": application.status,
        "applied_at": application.applied_at,
        "updated_at": application.updated_at,
        "candidate": {
            "id": candidate.id,
            "first_name": candidate.first_name,
            "last_name": candidate.last_name,
            "email": candidate.email,
            "source": candidate.source,
            "resume_data": resume_data or None,
        },
    }