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
            name="morgan-cv-v1.pdf",
            storage_key="local://org/candidate/morgan-v1.pdf",
            content_type="application/pdf",
            size_bytes=5,
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        document_id = document.id

    monkeypatch.setattr(
        private_storage,
        "read_bytes",
        lambda reference: b"%PDF-" if reference == "local://org/candidate/morgan-v1.pdf" else b"",
    )

    listed = client.get(f"/candidates/{candidate_id}/documents", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == document_id
    assert listed.json()[0]["name"] == "morgan-cv-v1.pdf"
    assert listed.json()[0]["content_type"] == "application/pdf"
    assert listed.json()[0]["size_bytes"] == 5
    assert listed.json()[0]["application_id"] is None
    assert listed.json()[0]["created_at"] is not None
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
