from io import BytesIO

import pytest
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as api
from app.database import Base, get_db, upgrade_phase1_columns
from app.models import Email
from app.services.extractor import extractor_service


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
    monkeypatch.setattr(api, "deliver_outbox_email", lambda _email_id: None)
    with TestClient(api.app) as test_client:
        test_client.app.state.test_session = test_session
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


def test_loopback_vite_origin_is_allowed_by_cors(client):
    response = client.options(
        "/auth/register",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_cors_keeps_configured_deployment_origins():
    origins = api.get_allowed_origins("https://bluepace.example.com, https://preview.example.com")

    assert origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://bluepace.example.com",
        "https://preview.example.com",
    ]


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
    assert any(
        entry["action"] == "candidate.deleted"
        for entry in client.get("/audit-logs?entity_type=candidate", headers=first_org_headers).json()
    )


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


def test_application_starts_applied_and_can_advance(client):
    headers = register_and_login(client)
    job = client.post(
        "/jobs",
        json={"title": "Product Designer", "description": "Design useful tools", "status": "open"},
        headers=headers,
    ).json()
    candidate = client.post(
        "/candidates",
        json={"first_name": "Morgan", "last_name": "Chen", "email": "morgan@example.com"},
        headers=headers,
    ).json()

    created = client.post(
        "/applications",
        json={"job_id": job["id"], "candidate_id": candidate["id"]},
        headers=headers,
    )
    assert created.status_code == 201
    application_id = created.json()["id"]
    assert created.json()["stage_name"] == "Applied"

    moved = client.post(
        f"/applications/{application_id}/stage",
        json={"stage_name": "Screening"},
        headers=headers,
    )
    assert moved.status_code == 200
    assert moved.json()["stage_name"] == "Screening"


def test_resume_fallback_parses_contact_skills_experience_and_education(monkeypatch):
    monkeypatch.setattr(extractor_service, "client", None, raising=False)
    document = Document()
    for paragraph in [
        "Jane Doe",
        "jane@example.com | +1 415 555 0134",
        "Skills: Python, React, PostgreSQL",
        "Experience",
        "Software Engineer | Acme Labs | 2021 - Present",
        "Built and maintained backend services.",
        "Education",
        "B.S. Computer Science | State University | 2017",
    ]:
        document.add_paragraph(paragraph)
    content = BytesIO()
    document.save(content)

    parsed = extractor_service.extract_to_json(content.getvalue(), "jane.docx")

    assert parsed["email"] == "jane@example.com"
    assert {"Python", "React", "PostgreSQL"}.issubset(parsed["skills"])
    assert parsed["experience"][0]["company"] == "Acme Labs"
    assert parsed["education"][0]["university"] == "State University"


def test_pipeline_filters_bulk_actions_csv_and_audit_logs(client):
    headers = register_and_login(client)
    job = client.post(
        "/jobs",
        json={"title": "Platform Engineer", "description": "Build platform", "status": "open"},
        headers=headers,
    ).json()
    candidates = []
    for first_name, email, source, skill in [
        ("Avery", "avery@example.com", "referral", "Python"),
        ("Riley", "riley@example.com", "careers-page", "React"),
    ]:
        response = client.post(
            "/candidates",
            json={
                "first_name": first_name,
                "last_name": "Park",
                "email": email,
                "source": source,
                "resume_data": {"skills": [skill]},
            },
            headers=headers,
        )
        assert response.status_code == 201
        candidates.append(response.json())

    applications = []
    for candidate in candidates:
        response = client.post(
            "/applications",
            json={"job_id": job["id"], "candidate_id": candidate["id"]},
            headers=headers,
        )
        assert response.status_code == 201
        applications.append(response.json())

    filtered = client.get(
        "/applications",
        params={"stage_name": "Applied", "source": "referral", "skill": "Python"},
        headers=headers,
    )
    assert [item["candidate_id"] for item in filtered.json()] == [candidates[0]["id"]]
    applied_date = applications[0]["applied_at"][:10]
    dated = client.get(
        "/applications",
        params={"applied_after": applied_date, "applied_before": applied_date},
        headers=headers,
    )
    assert len(dated.json()) == 2

    moved = client.post(
        "/applications/bulk-stage",
        json={"application_ids": [item["id"] for item in applications], "stage_name": "Interview"},
        headers=headers,
    )
    assert moved.status_code == 200
    assert {item["stage_name"] for item in moved.json()} == {"Interview"}

    exported = client.get("/applications/export.csv?stage_name=Interview", headers=headers)
    assert exported.status_code == 200
    assert "Avery Park" in exported.text and "Riley Park" in exported.text

    rejected = client.post(
        "/applications/bulk-stage",
        json={"application_ids": [applications[0]["id"]], "stage_name": "Rejected"},
        headers=headers,
    )
    assert rejected.status_code == 200
    assert rejected.json()[0]["status"] == "rejected"
    assert client.post(
        f"/applications/{applications[0]['id']}/stage",
        json={"stage_name": "Applied"},
        headers=headers,
    ).status_code == 409

    logs = client.get("/audit-logs?entity_type=application", headers=headers).json()
    assert len(logs) >= 5
    with client.app.state.test_session() as db:
        assert len(db.scalars(select(Email)).all()) >= 5


def test_job_archive_is_audited(client):
    headers = register_and_login(client)
    job = client.post(
        "/jobs",
        json={"title": "Archived Role", "description": "No longer hiring"},
        headers=headers,
    ).json()
    archived = client.post(f"/jobs/{job['id']}/archive", headers=headers)
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert any(
        entry["action"] == "job.archived"
        for entry in client.get("/audit-logs?entity_type=job", headers=headers).json()
    )


def test_phase1_schema_upgrade_adds_columns_to_phase0_database():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE candidates (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE applications (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE emails (id INTEGER PRIMARY KEY)"))

    upgrade_phase1_columns(engine)

    assert "resume_data" in {column["name"] for column in inspect(engine).get_columns("candidates")}
    application_columns = {column["name"]: column for column in inspect(engine).get_columns("applications")}
    assert application_columns["updated_at"]["nullable"] is True
    assert "error_message" in {column["name"] for column in inspect(engine).get_columns("emails")}
    engine.dispose()


def test_candidate_resume_upload_persists_structured_profile(client, monkeypatch, tmp_path):
    monkeypatch.setenv("RESUME_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(extractor_service, "client", None, raising=False)
    headers = register_and_login(client)
    candidate = client.post(
        "/candidates",
        json={"first_name": "Jane", "last_name": "Doe", "email": "jane@example.com"},
        headers=headers,
    ).json()
    document = Document()
    for paragraph in [
        "Jane Doe",
        "jane@example.com",
        "Skills: Python, React",
        "Experience",
        "Software Engineer | Acme Labs | 2021 - Present",
        "Education",
        "B.S. Computer Science | State University | 2017",
    ]:
        document.add_paragraph(paragraph)
    content = BytesIO()
    document.save(content)

    response = client.post(
        f"/candidates/{candidate['id']}/resume",
        files={
            "file": (
                "jane.docx",
                content.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["resume_data"]["experience"][0]["company"] == "Acme Labs"
    assert response.json()["resume_data"]["education"][0]["university"] == "State University"
    assert "raw_text" not in response.json()["resume_data"]
    storage_key = response.json()["resume_storage_key"]
    assert (tmp_path / storage_key).is_file()


def test_csv_export_escapes_spreadsheet_formulas(client):
    headers = register_and_login(client)
    job = client.post(
        "/jobs",
        json={"title": "Data Analyst", "description": "Analyze data", "status": "open"},
        headers=headers,
    ).json()
    candidate = client.post(
        "/candidates",
        json={"first_name": "=SUM(1,1)", "last_name": "Candidate", "email": "formula@example.com"},
        headers=headers,
    ).json()
    assert client.post(
        "/applications",
        json={"job_id": job["id"], "candidate_id": candidate["id"]},
        headers=headers,
    ).status_code == 201

    response = client.get("/applications/export.csv", headers=headers)

    assert response.status_code == 200
    assert "'=SUM(1,1) Candidate" in response.text