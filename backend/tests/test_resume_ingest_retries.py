from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Import the API module so all ORM models are registered on Base.metadata.
from app.main import app, _recover_stale_resume_jobs  # noqa: F401
from app.database import Base
from app.models import ResumeProcessingJob
from app.services.extractor import DocumentExtractionError
from app.services import queue_tasks


@pytest.fixture
def resume_job_store(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(queue_tasks, "SessionLocal", test_session)

    with test_session() as db:
        job = ResumeProcessingJob(
            batch_id="resume-retry-test",
            organization_id=None,
            created_by_id=None,
            filename="resume.pdf",
            storage_path="local://resume_queue/resume-retry-test/resume.pdf",
            content_type="application/pdf",
            size_bytes=100,
            status="queued",
        )
        db.add(job)
        db.commit()
        job_id = job.id

    try:
        yield test_session, job_id
    finally:
        engine.dispose()


def _raise(error):
    raise error


def _read_job(test_session, job_id):
    with test_session() as db:
        return db.scalar(
            select(ResumeProcessingJob).where(ResumeProcessingJob.id == job_id)
        )


def test_transient_resume_ingest_error_is_requeued_for_retry(
    resume_job_store, monkeypatch
):
    test_session, job_id = resume_job_store
    monkeypatch.setattr(
        queue_tasks.private_storage,
        "read_bytes",
        lambda _path: _raise(OSError("temporary storage failure")),
    )

    with pytest.raises(OSError, match="temporary storage failure"):
        queue_tasks.process_resume_ingest_job.run(job_id, dispatcher_attempt=0)

    job = _read_job(test_session, job_id)
    assert job.status == "queued"
    assert job.completed_at is None
    assert "retry scheduled" in job.error_message
    assert "OSError" in job.error_message
    assert "temporary storage failure" not in job.error_message


def test_resume_ingest_exhausted_retry_budget_is_terminal(
    resume_job_store, monkeypatch
):
    test_session, job_id = resume_job_store
    monkeypatch.setattr(
        queue_tasks.private_storage,
        "read_bytes",
        lambda _path: _raise(OSError("storage unavailable")),
    )

    with pytest.raises(OSError, match="storage unavailable"):
        queue_tasks.process_resume_ingest_job.run(job_id, dispatcher_attempt=3)

    job = _read_job(test_session, job_id)
    assert job.status == "failed"
    assert job.completed_at is not None
    assert job.error_message == "storage unavailable"


def test_invalid_document_is_not_retried(
    resume_job_store, monkeypatch
):
    test_session, job_id = resume_job_store
    monkeypatch.setattr(queue_tasks.private_storage, "read_bytes", lambda _path: b"bad document")
    monkeypatch.setattr(
        queue_tasks.extractor_service,
        "extract_to_json",
        lambda *_args: _raise(DocumentExtractionError("The file is not a supported PDF or DOCX document.")),
    )

    with pytest.raises(DocumentExtractionError, match="not a supported"):
        queue_tasks.process_resume_ingest_job.run(job_id, dispatcher_attempt=0)

    job = _read_job(test_session, job_id)
    assert job.status == "failed"
    assert job.completed_at is not None
    assert "not a supported" in job.error_message


def test_stale_processing_jobs_are_requeued_without_touching_recent_jobs(
    resume_job_store,
):
    test_session, existing_job_id = resume_job_store
    now = datetime.now(timezone.utc)

    with test_session() as db:
        existing = db.get(ResumeProcessingJob, existing_job_id)
        existing.status = "processing"
        existing.started_at = now - timedelta(hours=3)
        existing.error_message = "worker interrupted"

        fresh = ResumeProcessingJob(
            batch_id="resume-retry-test",
            organization_id=None,
            created_by_id=None,
            filename="recent.pdf",
            storage_path="local://resume_queue/resume-retry-test/recent.pdf",
            content_type="application/pdf",
            size_bytes=100,
            status="processing",
            started_at=now - timedelta(minutes=5),
        )
        db.add(fresh)
        db.commit()
        fresh_id = fresh.id

        recovered_count = _recover_stale_resume_jobs(
            db, now=now, stale_after_minutes=120
        )

    assert recovered_count == 1

    stale_job = _read_job(test_session, existing_job_id)
    assert stale_job.status == "queued"
    assert stale_job.started_at is None
    assert stale_job.completed_at is None
    assert "interrupted processing" in stale_job.error_message

    fresh_job = _read_job(test_session, fresh_id)
    assert fresh_job.status == "processing"
    assert fresh_job.started_at is not None
