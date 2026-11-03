from __future__ import annotations

from local_ai_server import app


def test_local_ai_service_exposes_jd_and_applicant_match_routes() -> None:
    # OpenAPI resolves nested FastAPI routers; newer FastAPI versions may keep
    # included routers as lazy route entries with no direct .path attribute.
    paths = set(app.openapi()["paths"])

    assert "/healthz" in paths
    assert "/v1/models" in paths
    assert "/v1/models/{profile_id}/health" in paths
    assert "/v1/jd/generate" in paths
    assert "/v1/jd/standardize" in paths
    assert "/v1/match/rubrics" in paths
    assert "/v1/match/analyze" in paths
    assert "/v1/assistant" in paths


def test_local_ai_service_cors_allows_supported_bluepace_frontends() -> None:
    cors = next(middleware for middleware in app.user_middleware if middleware.cls.__name__ == "CORSMiddleware")
    origins = cors.kwargs["allow_origins"]

    assert "https://bluepace-ats-frontend.vercel.app" in origins
    assert "https://bluepace-ats-frontend.onrender.com" in origins
    assert "http://localhost:5173" in origins
