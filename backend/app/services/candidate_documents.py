"""Organisation-scoped candidate CV document history helpers."""

from sqlalchemy import select

from app.models import CandidateDocument


def record_candidate_document(
    db,
    *,
    organization_id: int,
    candidate_id: int,
    name: str,
    storage_reference: str,
    content_type: str,
    size_bytes: int,
    application_id: int | None = None,
) -> CandidateDocument:
    """Attach a durable CV object to a candidate exactly once.

    CandidateDocument rows are immutable upload records. A new storage
    reference creates a new chronological version; an existing reference is
    reused instead of creating duplicate history entries.
    """
    existing = db.scalar(
        select(CandidateDocument)
        .where(
            CandidateDocument.organization_id == organization_id,
            CandidateDocument.candidate_id == candidate_id,
            CandidateDocument.storage_key == storage_reference,
        )
        .limit(1)
    )
    if existing is not None:
        if application_id is not None and existing.application_id is None:
            existing.application_id = application_id
        return existing

    document = CandidateDocument(
        organization_id=organization_id,
        candidate_id=candidate_id,
        application_id=application_id,
        name=(name or f"resume-{candidate_id}").strip()[:255],
        storage_key=storage_reference,
        content_type=(content_type or "application/octet-stream")[:200],
        size_bytes=max(0, int(size_bytes)),
    )
    db.add(document)
    return document


def should_delete_resume_source(
    storage_reference: str,
    *,
    current_resume_references=(),
    document_references=(),
) -> bool:
    """Only delete an intake object when no candidate or document points to it."""
    if not storage_reference:
        return False
    return (
        storage_reference not in set(current_resume_references)
        and storage_reference not in set(document_references)
    )
