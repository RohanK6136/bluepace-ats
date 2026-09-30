import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as api
from app.database import Base, get_db


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

    api.app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(api, "initialize_database", lambda: None)
    with TestClient(api.app) as test_client:
        yield test_client
    api.app.dependency_overrides.clear()
    engine.dispose()


def register_and_login(client, email="owner@example.com", organization="Acme Recruiting"):
    response = client.post(
        "/auth/register",
        json={
            "organization_name": organization,
            "full_name": "Org Owner",
            "email": email,
            "password": "a-long-test-password",
        },
    )
    assert response.status_code == 201
    response = client.post(
        "/auth/token",
        data={"username": email, "password": "a-long-test-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_job_crud_requires_auth_and_round_trips(client):
    assert client.get("/jobs").status_code == 401
    headers = register_and_login(client)
    payload = {"title": "Senior Engineer", "description": "Build reliable systems"}

    created = client.post("/jobs", json=payload, headers=headers)
    assert created.status_code == 201
    job_id = created.json()["id"]
    assert client.get("/jobs", headers=headers).json()[0]["title"] == "Senior Engineer"
    assert client.get(f"/jobs/{job_id}", headers=headers).status_code == 200

    updated = client.patch(f"/jobs/{job_id}", json={"status": "open"}, headers=headers)
    assert updated.status_code == 200
    assert updated.json()["status"] == "open"
    assert client.delete(f"/jobs/{job_id}", headers=headers).status_code == 204
    assert client.get(f"/jobs/{job_id}", headers=headers).status_code == 404


def test_candidate_crud_is_organization_scoped(client):
    first_org_headers = register_and_login(client)
    created = client.post(
        "/candidates",
        json={"first_name": "Casey", "last_name": "Ng", "email": "CASEY@example.com"},
        headers=first_org_headers,
    )
    assert created.status_code == 201
    candidate_id = created.json()["id"]
    assert created.json()["email"] == "casey@example.com"

    second_org_headers = register_and_login(
        client, "other-owner@example.com", "Other Recruiting"
    )
    assert client.get(f"/candidates/{candidate_id}", headers=second_org_headers).status_code == 404
    assert client.get("/candidates", headers=second_org_headers).json() == []

    updated = client.patch(
        f"/candidates/{candidate_id}",
        json={"phone": "+1 555 0100"},
        headers=first_org_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["phone"] == "+1 555 0100"
    assert client.delete(f"/candidates/{candidate_id}", headers=first_org_headers).status_code == 204


def test_interviewer_can_read_but_cannot_write(client):
    admin_headers = register_and_login(client)
    created_user = client.post(
        "/users",
        json={
            "full_name": "Interview Panelist",
            "email": "interviewer@example.com",
            "password": "another-test-password",
            "role": "interviewer",
        },
        headers=admin_headers,
    )
    assert created_user.status_code == 201
    token = client.post(
        "/auth/token",
        data={"username": "interviewer@example.com", "password": "another-test-password"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/jobs", headers=headers).status_code == 200
    assert client.post(
        "/jobs",
        json={"title": "Restricted", "description": "Read only"},
        headers=headers,
    ).status_code == 403


def test_duplicate_candidate_email_returns_conflict(client):
    headers = register_and_login(client)
    payload = {"first_name": "Taylor", "last_name": "Lee", "email": "taylor@example.com"}
    assert client.post("/candidates", json=payload, headers=headers).status_code == 201
    assert client.post("/candidates", json=payload, headers=headers).status_code == 409