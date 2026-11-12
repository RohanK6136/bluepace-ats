from __future__ import annotations

import asyncio

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


def test_local_ai_service_cors_allows_only_bluepace_vercel_frontend_previews() -> None:
    import re

    cors = next(middleware for middleware in app.user_middleware if middleware.cls.__name__ == "CORSMiddleware")
    pattern = cors.kwargs["allow_origin_regex"]

    preview_origin = "https://bluepace-ats-frontend-git-fe-336527-sukumarparamountpowers-1576.vercel.app"
    unrelated_origin = "https://another-app-git-fe-336527-sukumarparamountpowers-1576.vercel.app"

    assert re.fullmatch(pattern, preview_origin)
    assert not re.fullmatch(pattern, unrelated_origin)


def test_local_model_catalog_exposes_only_the_started_profile() -> None:
    from types import SimpleNamespace

    from local_ai_server import list_models

    class FakeProfile:
        def __init__(self, profile_id: str):
            self.id = profile_id

        def model_dump(self, mode: str) -> dict[str, str]:
            return {"id": self.id}

    registry = SimpleNamespace(
        default_id="local-ollama",
        statuses=lambda: [FakeProfile("local-qwen"), FakeProfile("local-ollama")],
    )
    payload = asyncio.run(list_models(SimpleNamespace(registry=registry)))

    assert payload == [{"id": "local-ollama"}]
