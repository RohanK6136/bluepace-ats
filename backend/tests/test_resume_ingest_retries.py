from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Import the API module so all ORM models are registered on Base.metadata.
from app.main import app, _recover_stale_resume_jobs  # noqa: F401
from app.database import Base
from app.models import Candidate, CandidateDocument, Organization, ResumeProcessingJob, User
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



def _seed_candidate_and_attach_job(test_session, job_id, *, current_resume=None, job_storage_path=None):
    with test_session() as db:
        organization = Organization(name="Resume Retention QA")
        db.add(organization)
        db.flush()
        user = User(
            organization_id=organization.id,
            email=f"owner-{job_id}@example.com",
            full_name="Resume QA Owner",
            password_hash="not-used-in-this-test",
        )
        db.add(user)
        db.flush()
        candidate = Candidate(
            organization_id=organization.id,
            created_by_id=user.id,
            first_name="Morgan",
            last_name="Taylor",
            email=f"candidate-{job_id}@example.com",
            resume_storage_key=current_resume,
        )
        db.add(candidate)
        db.flush()
        job = db.get(ResumeProcessingJob, job_id)
        job.organization_id = organization.id
        job.created_by_id = user.id
        job.candidate_id = candidate.id
        if job_storage_path is not None:
            job.storage_path = job_storage_path
        if current_resume:
            db.add(CandidateDocument(
                organization_id=organization.id,
                candidate_id=candidate.id,
                name="previous-resume.pdf",
                storage_key=current_resume,
                content_type="application/pdf",
                size_bytes=50,
            ))
        db.commit()
        return candidate.id, job.storage_path, organization.id


def _patch_successful_resume_extraction(monkeypatch):
    extracted = {
        "name": "Morgan Taylor",
        "email": "morgan@example.com",
        "phone": "123456789",
        "skills": ["Python"],
        "experience": [],
        "education": [],
        "raw_text": "Morgan Taylor\nPython developer",
    }
    monkeypatch.setattr(
        queue_tasks.private_storage,
        "read_bytes",
        lambda _path: b"resume-source-bytes",
    )
    monkeypatch.setattr(
        queue_tasks.extractor_service,
        "extract_to_json",
        lambda *_args: dict(extracted),
    )
    monkeypatch.setattr(queue_tasks, "enrich_extracted_with_slm", lambda value: value)
    monkeypatch.setattr(queue_tasks, "attach_text_quality_review", lambda value, _raw: value)


def test_resume_lab_ingest_promotes_source_to_candidate_history_and_cleans_intake(
    resume_job_store, monkeypatch
):
    test_session, job_id = resume_job_store
    candidate_id, source_path, organization_id = _seed_candidate_and_attach_job(test_session, job_id)
    uploaded = []
    deleted = []

    _patch_successful_resume_extraction(monkeypatch)

    def put_bytes(key, content, content_type):
        uploaded.append((key, content, content_type))
        return f"local://{key}"

    monkeypatch.setattr(queue_tasks.private_storage, "put_bytes", put_bytes)
    monkeypatch.setattr(queue_tasks.private_storage, "delete", lambda path: deleted.append(path))

    result = queue_tasks.process_resume_ingest_job.run(job_id, dispatcher_attempt=0)

    assert result == {"status": "completed", "job_id": job_id}
    assert len(uploaded) == 1
    assert uploaded[0][0].startswith(f"{organization_id}/{candidate_id}/resume-ingest-{job_id}")
    assert uploaded[0][1] == b"resume-source-bytes"
    assert deleted == [source_path]

    with test_session() as db:
        candidate = db.get(Candidate, candidate_id)
        documents = db.query(CandidateDocument).filter_by(candidate_id=candidate_id).all()
        job = db.get(ResumeProcessingJob, job_id)
        assert candidate.resume_storage_key == f"local://{uploaded[0][0]}"
        assert len(documents) == 1
        assert documents[0].storage_key == candidate.resume_storage_key
        assert documents[0].name == "resume.pdf"
        assert job.status == "completed"


def test_public_application_ingest_keeps_candidate_source_file(
    resume_job_store, monkeypatch
):
    test_session, job_id = resume_job_store
    public_path = "local://candidate/current-public-application.pdf"
    candidate_id, source_path, _organization_id = _seed_candidate_and_attach_job(
        test_session,
        job_id,
        current_resume=public_path,
        job_storage_path=public_path,
    )
    uploaded = []
    deleted = []

    _patch_successful_resume_extraction(monkeypatch)
    monkeypatch.setattr(
        queue_tasks.private_storage,
        "put_bytes",
        lambda *args: uploaded.append(args),
    )
    monkeypatch.setattr(queue_tasks.private_storage, "delete", lambda path: deleted.append(path))

    result = queue_tasks.process_resume_ingest_job.run(job_id, dispatcher_attempt=0)

    assert result == {"status": "completed", "job_id": job_id}
    assert uploaded == []
    assert deleted == []

    with test_session() as db:
        candidate = db.get(Candidate, candidate_id)
        documents = db.query(CandidateDocument).filter_by(candidate_id=candidate_id).all()
        assert candidate.resume_storage_key == public_path
        assert len(documents) == 1
        assert documents[0].storage_key == public_path


def test_delayed_bulk_ingest_does_not_replace_existing_candidate_cv(
    resume_job_store, monkeypatch
):
    test_session, job_id = resume_job_store
    current_resume = "local://candidate/newer-direct-upload.pdf"
    candidate_id, source_path, _organization_id = _seed_candidate_and_attach_job(
        test_session,
        job_id,
        current_resume=current_resume,
    )
    uploaded = []
    deleted = []

    _patch_successful_resume_extraction(monkeypatch)

    def put_bytes(key, content, content_type):
        uploaded.append((key, content, content_type))
        return f"local://{key}"

    monkeypatch.setattr(queue_tasks.private_storage, "put_bytes", put_bytes)
    monkeypatch.setattr(queue_tasks.private_storage, "delete", lambda path: deleted.append(path))

    result = queue_tasks.process_resume_ingest_job.run(job_id, dispatcher_attempt=0)

    assert result == {"status": "completed", "job_id": job_id}
    assert len(uploaded) == 1
    assert deleted == [source_path]

    with test_session() as db:
        candidate = db.get(Candidate, candidate_id)
        documents = db.query(CandidateDocument).filter_by(candidate_id=candidate_id).all()
        assert candidate.resume_storage_key == current_resume
        assert {document.storage_key for document in documents} == {
            current_resume,
            f"local://{uploaded[0][0]}",
        }


def _seed_resume_lab_job(test_session, job_id):
    with test_session() as db:
        organization = Organization(name="Resume Lab QA")
        db.add(organization)
        db.flush()
        user = User(
            organization_id=organization.id,
            email=f"resume-lab-owner-{job_id}@example.com",
            full_name="Resume Lab QA Owner",
            password_hash="not-used-in-this-test",
        )
        db.add(user)
        db.flush()
        job = db.get(ResumeProcessingJob, job_id)
        job.organization_id = organization.id
        job.created_by_id = user.id
        db.commit()
        return organization.id, job.storage_path


def test_resume_lab_worker_creates_candidate_and_retains_uploaded_cv(
    resume_job_store, monkeypatch
):
    test_session, job_id = resume_job_store
    organization_id, source_path = _seed_resume_lab_job(test_session, job_id)
    uploaded = []
    deleted = []

    _patch_successful_resume_extraction(monkeypatch)

    def put_bytes(key, content, content_type):
        uploaded.append((key, content, content_type))
        return f"local://{key}"

    monkeypatch.setattr(queue_tasks.private_storage, "put_bytes", put_bytes)
    monkeypatch.setattr(queue_tasks.private_storage, "delete", lambda path: deleted.append(path))

    result = queue_tasks.process_resume_ingest_job.run(job_id, dispatcher_attempt=0)

    assert result == {"status": "completed", "job_id": job_id}
    assert len(uploaded) == 1
    assert uploaded[0][0].startswith(f"{organization_id}/")
    assert uploaded[0][0].endswith(f"/resume-ingest-{job_id}.pdf")
    assert deleted == [source_path]

    with test_session() as db:
        candidate = db.query(Candidate).filter_by(
            organization_id=organization_id,
            email="morgan@example.com",
        ).one()
        document = db.query(CandidateDocument).filter_by(
            organization_id=organization_id,
            candidate_id=candidate.id,
        ).one()
        job = db.get(ResumeProcessingJob, job_id)
        assert job.candidate_id == candidate.id
        assert candidate.resume_storage_key == f"local://{uploaded[0][0]}"
        assert document.storage_key == candidate.resume_storage_key
        assert document.name == "resume.pdf"
