from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import require_api_key
from app.features.resume_authorship.routes import router


app = FastAPI()
app.include_router(router)
app.dependency_overrides[require_api_key] = lambda: None
client = TestClient(app)


def test_assessment_endpoint_returns_undetermined_advisory_result():
    text = "\n".join(
        f"Experience item {i}: designed and maintained production software services."
        for i in range(12)
    )
    response = client.post("/v1/resume-authorship/assess", json={"text": text})
    assert response.status_code == 200
    payload = response.json()
    assert payload["assessment"] == "undetermined"
    assert payload["confidence"] == "not_assessed"
    assert payload["human_review_required"] is True


def test_assessment_endpoint_rejects_too_little_text():
    response = client.post("/v1/resume-authorship/assess", json={"text": "short"})
    assert response.status_code == 422


def test_assessment_endpoint_rejects_unexpected_fields():
    response = client.post(
        "/v1/resume-authorship/assess",
        json={"text": "x" * 120, "candidate_id": "must-not-be-accepted"},
    )
    assert response.status_code == 422
