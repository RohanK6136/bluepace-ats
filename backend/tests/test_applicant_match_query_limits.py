"""Regression tests for Applicant Match list endpoint limits.

These tests use the real FastAPI router and override only the platform/auth
dependencies, so they exercise FastAPI query validation without requiring a
database or live model provider.
"""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import platform, require_api_key
from app.features.applicant_match.routes import router


class EmptyStore:
    def list_runs(self, **_kwargs):
        return []

    def list_rubrics(self, _limit):
        return []


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[platform] = lambda: SimpleNamespace(store=EmptyStore())
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
