from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import platform, require_api_key
from app.features.jd_standardizer.routes import router


class FakeSettings:
    MAX_INPUT_CHARS = 5000


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[platform] = lambda: SimpleNamespace(settings=FakeSettings())
    return TestClient(app)


def test_quality_endpoint_returns_explainable_report_without_model_dependency():
    response = make_client().post(
        "/v1/jd/quality",
        json={"text": "Senior Engineer\nResponsibilities\n- Build services.\nRequirements\n- Python."},
    )

    assert response.status_code == 200
    report = response.json()
    assert report["assessment_type"] == "deterministic_text_checks"
    assert report["score"] == sum(item["score"] for item in report["categories"])
    assert report["disclaimer"]
    assert isinstance(report["findings"], list)


def test_quality_endpoint_rejects_blank_text():
    response = make_client().post("/v1/jd/quality", json={"text": "   "})

    assert response.status_code == 422


def test_quality_endpoint_enforces_deployment_input_limit():
    response = make_client().post("/v1/jd/quality", json={"text": "x" * 5001})

    assert response.status_code == 400
    assert "MAX_INPUT_CHARS" in response.json()["detail"]
