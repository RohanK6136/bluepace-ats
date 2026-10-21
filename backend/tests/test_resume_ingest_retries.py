import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Import the API module so all ORM models are registered on Base.metadata.
from app.main import app  # noqa: F401
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
