import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Candidate, CandidateDocument
from app.services.private_storage import private_storage


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = test_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("app.main.initialize_database", lambda: None)
    monkeypatch.setattr("app.main.ensure_bootstrap_account", lambda: None)
    monkeypatch.setattr("app.main.disable_pending_email_records", lambda: 0)
    with TestClient(app) as test_client:
        test_client.app.state.test_session = test_session
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


def register_and_login(client, email, organization):
    registered = client.post(
        "/auth/register",
        json={
            "organization_name": organization,
            "full_name": "Test Owner",
            "email": email,
            "password": "a-long-test-password",
        },
    )
    assert registered.status_code == 201
    login = client.post(
        "/auth/token",
        data={"username": email, "password": "a-long-test-password"},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_candidate_cv_history_lists_and_downloads_only_authorized_documents(client, monkeypatch):
    headers = register_and_login(client, "cv-owner@example.com", "CV History Org")
    candidate_response = client.post(
        "/candidates",
        json={
            "first_name": "Morgan",
            "last_name": "Taylor",
            "email": "morgan.cv@example.com",
        },
        headers=headers,
    )
    assert candidate_response.status_code == 201
    candidate_id = candidate_response.json()["id"]

    with client.app.state.test_session() as db:
        candidate = db.get(Candidate, candidate_id)
        document = CandidateDocument(
            organization_id=candidate.organization_id,
            candidate_id=candidate_id,
            name="morgan-cv-v2.pdf",
            storage_key="local://org/candidate/morgan-v2.pdf",
            content_type="application/pdf",
            size_bytes=5,
        )
        previous_document = CandidateDocument(
            organization_id=candidate.organization_id,
            candidate_id=candidate_id,
            name="morgan-cv-v1.pdf",
            storage_key="local://org/candidate/morgan-v1.pdf",
            content_type="application/pdf",
            size_bytes=4,
        )
        candidate.resume_storage_key = "local://org/candidate/morgan-v2.pdf"
        db.add_all([document, previous_document])
        db.commit()
        db.refresh(document)
        db.refresh(previous_document)
        document_id = document.id
        previous_document_id = previous_document.id

    monkeypatch.setattr(
        private_storage,
        "read_bytes",
        lambda reference: b"%PDF-" if reference in {"local://org/candidate/morgan-v1.pdf", "local://org/candidate/morgan-v2.pdf"} else b"",
    )

    listed = client.get(f"/candidates/{candidate_id}/documents", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 2
    listed_by_id = {item["id"]: item for item in listed.json()}
    assert listed_by_id[document_id]["name"] == "morgan-cv-v2.pdf"
    assert listed_by_id[document_id]["content_type"] == "application/pdf"
    assert listed_by_id[document_id]["size_bytes"] == 5
    assert listed_by_id[document_id]["application_id"] is None
    assert listed_by_id[document_id]["is_current"] is True
    assert listed_by_id[document_id]["created_at"] is not None
    assert listed_by_id[previous_document_id]["is_current"] is False
    assert "storage_key" not in listed.text

    downloaded = client.get(
        f"/candidates/{candidate_id}/documents/{document_id}",
        headers=headers,
    )
    assert downloaded.status_code == 200
    assert downloaded.content == b"%PDF-"
    assert downloaded.headers["content-type"].startswith("application/pdf")
    assert "attachment" in downloaded.headers["content-disposition"].lower()
    assert downloaded.headers["cache-control"] == "private, no-store"
    assert downloaded.headers["x-content-type-options"] == "nosniff"


def test_candidate_cv_history_is_not_accessible_across_organizations(client):
    owner_headers = register_and_login(client, "cv-owner2@example.com", "CV Owner Org")
    other_headers = register_and_login(client, "other-owner@example.com", "Other CV Org")
    candidate_response = client.post(
        "/candidates",
        json={
            "first_name": "Alex",
            "last_name": "Recruit",
            "email": "alex.cv@example.com",
        },
        headers=owner_headers,
    )
    assert candidate_response.status_code == 201
    candidate_id = candidate_response.json()["id"]

    with client.app.state.test_session() as db:
        candidate = db.get(Candidate, candidate_id)
        document = CandidateDocument(
            organization_id=candidate.organization_id,
            candidate_id=candidate_id,
            name="private-cv.pdf",
            storage_key="local://org/private-cv.pdf",
            content_type="application/pdf",
            size_bytes=100,
        )
        db.add(document)
        db.commit()
        document_id = document.id

    listed = client.get(f"/candidates/{candidate_id}/documents", headers=other_headers)
    assert listed.status_code == 404

    downloaded = client.get(
        f"/candidates/{candidate_id}/documents/{document_id}",
        headers=other_headers,
    )
    assert downloaded.status_code == 404



def test_candidate_pdf_evidence_preview_highlights_only_stored_current_source_locations(
    client, monkeypatch
):
    headers = register_and_login(
        client, "evidence-owner@example.com", "Evidence Preview Org"
    )
    candidate_response = client.post(
        "/candidates",
        json={
            "first_name": "Aarav",
            "last_name": "Mehta",
            "email": "aarav.evidence@example.com",
        },
        headers=headers,
    )
    assert candidate_response.status_code == 201
    candidate_id = candidate_response.json()["id"]

    source_location = {
        "source_type": "docling_item",
        "page_number": 1,
        "item_label": "paragraph",
        "bbox": {
            "l": 10.0,
            "t": 50.0,
            "r": 200.0,
            "b": 90.0,
            "coord_origin": "TOPLEFT",
        },
        "page_size": {"width": 600.0, "height": 800.0},
    }

    with client.app.state.test_session() as db:
        candidate = db.get(Candidate, candidate_id)
        document = CandidateDocument(
            organization_id=candidate.organization_id,
            candidate_id=candidate_id,
            name="aarav-current.pdf",
            storage_key="local://org/candidate/aarav-current.pdf",
            content_type="application/pdf",
            size_bytes=100,
        )
        candidate.resume_storage_key = document.storage_key
        candidate.resume_data = {
            "extraction_evidence": [
                {"field": "email", "source_locations": [source_location]}
            ]
        }
        db.add(document)
        db.commit()
        db.refresh(document)
        document_id = document.id

    captured = {}

    monkeypatch.setattr(
        private_storage, "read_bytes", lambda _reference: b"%PDF-synthetic"
    )

    def fake_annotate(pdf_bytes, locations):
        captured["pdf_bytes"] = pdf_bytes
        captured["locations"] = locations
        return b"%PDF-highlighted-preview"

    monkeypatch.setattr("app.main.annotate_pdf_with_evidence", fake_annotate)

    response = client.post(
        f"/candidates/{candidate_id}/documents/{document_id}/evidence-preview",
        json={"source_locations": [source_location]},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.content == b"%PDF-highlighted-preview"
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert captured == {
        "pdf_bytes": b"%PDF-synthetic",
        "locations": [source_location],
    }


def test_candidate_pdf_evidence_preview_rejects_forged_or_previous_source_location(
    client, monkeypatch
):
    headers = register_and_login(
        client, "evidence-owner2@example.com", "Evidence Preview Org 2"
    )
    candidate_response = client.post(
        "/candidates",
        json={
            "first_name": "Alex",
            "last_name": "Morgan",
            "email": "alex.evidence@example.com",
        },
        headers=headers,
    )
    assert candidate_response.status_code == 201
    candidate_id = candidate_response.json()["id"]

    current_location = {
        "source_type": "docling_item",
        "page_number": 1,
        "bbox": {
            "l": 10.0,
            "t": 50.0,
            "r": 200.0,
            "b": 90.0,
            "coord_origin": "TOPLEFT",
        },
        "page_size": {"width": 600.0, "height": 800.0},
    }
    previous_location = {**current_location, "page_number": 2}

    with client.app.state.test_session() as db:
        candidate = db.get(Candidate, candidate_id)
        current_document = CandidateDocument(
            organization_id=candidate.organization_id,
            candidate_id=candidate_id,
            name="alex-current.pdf",
            storage_key="local://org/candidate/alex-current.pdf",
            content_type="application/pdf",
            size_bytes=100,
        )
        previous_document = CandidateDocument(
            organization_id=candidate.organization_id,
            candidate_id=candidate_id,
            name="alex-previous.pdf",
            storage_key="local://org/candidate/alex-previous.pdf",
            content_type="application/pdf",
            size_bytes=90,
        )
        candidate.resume_storage_key = current_document.storage_key
        candidate.resume_data = {
            "extraction_evidence": [
                {"field": "email", "source_locations": [current_location]}
            ]
        }
        db.add_all([current_document, previous_document])
        db.commit()
        db.refresh(current_document)
        db.refresh(previous_document)
        current_document_id = current_document.id
        previous_document_id = previous_document.id

    monkeypatch.setattr(
        private_storage, "read_bytes", lambda _reference: b"%PDF-synthetic"
    )
    monkeypatch.setattr(
        "app.main.annotate_pdf_with_evidence",
        lambda *_args: pytest.fail("Forged or outdated locations must not be annotated."),
    )

    forged = client.post(
        f"/candidates/{candidate_id}/documents/{current_document_id}/evidence-preview",
        json={"source_locations": [previous_location]},
        headers=headers,
    )
    assert forged.status_code == 422

    previous_document_response = client.post(
        f"/candidates/{candidate_id}/documents/{previous_document_id}/evidence-preview",
        json={"source_locations": [current_location]},
        headers=headers,
    )
    assert previous_document_response.status_code == 409
