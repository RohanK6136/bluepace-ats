from app.models import CandidateDocument
from app.services.candidate_documents import (
    record_candidate_document,
    should_delete_resume_source,
)


class FakeSession:
    def __init__(self, existing=None):
        self.existing = existing
        self.added = []

    def scalar(self, _statement):
        return self.existing

    def add(self, value):
        self.added.append(value)


def test_record_candidate_document_creates_a_version_record():
    db = FakeSession()

    document = record_candidate_document(
        db,
        organization_id=4,
        candidate_id=19,
        application_id=27,
        name="candidate-cv.pdf",
        storage_reference="b2://4/19/cv-v1.pdf",
        content_type="application/pdf",
        size_bytes=1234,
    )

    assert isinstance(document, CandidateDocument)
    assert db.added == [document]
    assert document.organization_id == 4
    assert document.candidate_id == 19
    assert document.application_id == 27
    assert document.storage_key == "b2://4/19/cv-v1.pdf"
    assert document.size_bytes == 1234


def test_record_candidate_document_does_not_duplicate_same_storage_reference():
    existing = CandidateDocument(
        organization_id=4,
        candidate_id=19,
        name="candidate-cv.pdf",
        storage_key="b2://4/19/cv-v1.pdf",
        content_type="application/pdf",
        size_bytes=1234,
    )
    db = FakeSession(existing=existing)

    document = record_candidate_document(
        db,
        organization_id=4,
        candidate_id=19,
        application_id=27,
        name="candidate-cv.pdf",
        storage_reference="b2://4/19/cv-v1.pdf",
        content_type="application/pdf",
        size_bytes=1234,
    )

    assert document is existing
    assert existing.application_id == 27
    assert db.added == []


def test_intake_file_is_not_deleted_when_current_candidate_cv_points_to_it():
    assert should_delete_resume_source(
        "local://org/resume.pdf",
        current_resume_references={"local://org/resume.pdf"},
    ) is False


def test_intake_file_is_not_deleted_when_cv_history_points_to_it():
    assert should_delete_resume_source(
        "b2://org/candidate/old.pdf",
        document_references={"b2://org/candidate/old.pdf"},
    ) is False


def test_unreferenced_bulk_intake_file_can_be_cleaned_after_promotion():
    assert should_delete_resume_source(
        "b2://org/resume_queue/batch/intake.pdf",
        current_resume_references={"b2://org/candidate/new.pdf"},
        document_references={"b2://org/candidate/new.pdf"},
    ) is True


def test_empty_storage_reference_is_never_deleted():
    assert should_delete_resume_source("") is False
