"""Regression tests for Applicant Match list endpoint limits.

These tests use the real FastAPI router and override only the platform/auth
dependencies, so they exercise FastAPI query validation without requiring a
database or live model provider.
"""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import platform, require_api_key
from app.config import Settings
from app.features.applicant_match import routes as match_routes
from app.features.applicant_match.models import Rubric, RubricDraft, RubricItem
from app.features.applicant_match.routes import router


class EmptyStore:
    def list_runs(self, **_kwargs):
        return []

    def list_rubrics(self, _limit):
        return []


def make_client(platform_override=None) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[platform] = lambda: platform_override or SimpleNamespace(store=EmptyStore())
    return TestClient(app)


def test_jobs_limit_rejects_values_outside_one_to_one_hundred() -> None:
    client = make_client()
    assert client.get("/v1/match/jobs?limit=0").status_code == 422
    assert client.get("/v1/match/jobs?limit=101").status_code == 422


def test_rubrics_limit_rejects_values_outside_one_to_one_hundred() -> None:
    client = make_client()
    assert client.get("/v1/match/rubrics?limit=0").status_code == 422
    assert client.get("/v1/match/rubrics?limit=101").status_code == 422


def test_jobs_and_rubrics_accept_maximum_limit() -> None:
    client = make_client()
    assert client.get("/v1/match/jobs?limit=100").status_code == 200
    assert client.get("/v1/match/rubrics?limit=100").status_code == 200


def test_fast_rubric_draft_does_not_require_a_configured_model_profile(monkeypatch) -> None:
    class JobStore(EmptyStore):
        def get_run(self, run_id):
            if run_id != "jd-fast-1":
                return None
            return {
                "id": run_id,
                "feature": "jd_standardizer",
                "result_json": '{"title":{"text":"Python Developer"},"sections":[{"id":"requirements","items":[{"text":"Python"}]}]}',
            }

    expected = RubricDraft(
        run_id="rubric-fast-1",
        rubric=Rubric(
            title="Python Developer",
            items=[RubricItem(
                id="R01", label="Python", type="skill", group="coding",
                importance="must", aliases=["Python"],
            )],
        ),
        notes=[],
    )

    def fail_if_profile_checked(*_args, **_kwargs):
        raise AssertionError("Fast rules-based rubric drafting must not require a model profile.")

    async def fake_draft(job, options, deps):
        assert job.title == "Python Developer"
        assert options.fast is True
        assert deps.settings is not None
        return expected

    monkeypatch.setattr(match_routes, "ensure_profile", fail_if_profile_checked)
    monkeypatch.setattr(match_routes, "draft_rubric", fake_draft)

    platform_stub = SimpleNamespace(
        store=JobStore(),
        llm=object(),
        settings=Settings(),
        jd=SimpleNamespace(policy=None),
    )
    response = make_client(platform_stub).post("/v1/match/rubrics", json={"jd_run_id": "jd-fast-1"})

    assert response.status_code == 200, response.text
    assert response.json()["rubric"]["items"][0]["label"] == "Python"
