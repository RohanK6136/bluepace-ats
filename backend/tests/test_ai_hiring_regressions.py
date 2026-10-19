"""Regression tests for fractional minimum-experience support.

These cover the API boundary and deterministic job-description parser without
calling an external AI provider or modifying production data.
"""
import app.main as api
from app.schemas import JobCreate, JobUpdate


def test_job_description_parser_keeps_fractional_minimum_experience():
    analysis = api.matching_service.parse_job_description(
        "Backend Engineer",
        "Requirements: minimum of 1.5 years of experience with Python and APIs.",
        use_llm=False,
    )

    assert analysis["minimum_experience_years"] == 1.5


def test_job_description_parser_keeps_fractional_experience_ranges():
    analysis = api.matching_service.parse_job_description(
        "Platform Engineer",
        "Candidates should have 1.5 to 3.5 years experience with Python.",
        use_llm=False,
    )

    assert analysis["minimum_experience_years"] == 1.5
    assert analysis["maximum_experience_years"] == 3.5


def test_analysis_normalization_does_not_truncate_fractional_years():
    normalized = api.matching_service._normalize_analysis(
        {"minimum_experience_years": 2.5},
        {"minimum_experience_years": None},
    )

    assert normalized["minimum_experience_years"] == 2.5


def test_job_create_schema_accepts_fractional_experience():
    job = JobCreate(
        title="Data Engineer",
        description="Build data pipelines.",
        minimum_experience_years=1.5,
    )

    assert job.minimum_experience_years == 1.5


def test_job_update_schema_accepts_fractional_experience():
    update = JobUpdate(minimum_experience_years=0.5)

    assert update.minimum_experience_years == 0.5


def test_invalid_model_output_is_recorded_as_failed_run():
    from types import SimpleNamespace

    import pytest
    from fastapi import HTTPException

    from app.routers.ai_hiring_studio import _mark_run_failed

    class FakeDatabase:
        commits = 0

        def commit(self):
            self.commits += 1

    db = FakeDatabase()
    run = SimpleNamespace(status="success", error_message=None, raw_model_output='{"job_description": ""}')

    with pytest.raises(HTTPException) as error:
        _mark_run_failed(db, run, "Model response did not include a job description. Retry.")

    assert error.value.status_code == 502
    assert run.status == "failed"
    assert run.error_message == "Model response did not include a job description. Retry."
    assert run.raw_model_output == '{"job_description": ""}'
    assert db.commits == 1


def test_rubric_weights_are_normalized_to_100():
    from app.routers.ai_hiring_studio import _normalize_rubric_result

    rubric = _normalize_rubric_result({
        "title": "Platform Engineer",
        "criteria": [
            {"name": "Python", "weight": 2, "required": True},
            {"name": "APIs", "weight": 1, "required": True},
            {"name": "Cloud", "weight": 1, "required": False},
        ],
    })

    assert [item["weight"] for item in rubric["criteria"]] == [50.0, 25.0, 25.0]
    assert rubric["total_weight"] == 100.0


def test_rubric_normalizer_rejects_zero_total_weights():
    import pytest

    from app.routers.ai_hiring_studio import _normalize_rubric_result

    with pytest.raises(ValueError, match="no positive weights"):
        _normalize_rubric_result({
            "criteria": [
                {"name": "Python", "weight": 0},
                {"name": "APIs", "weight": 0},
            ],
        })


def test_rubric_normalizer_rejects_non_object_criteria():
    import pytest

    from app.routers.ai_hiring_studio import _normalize_rubric_result

    with pytest.raises(ValueError, match="no usable rubric criteria"):
        _normalize_rubric_result({"criteria": ["not an object", None]})



def test_default_model_uses_free_openrouter_router(monkeypatch):
    from app.routers.ai_hiring_studio import DEFAULT_MODEL, _model_name

    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    assert DEFAULT_MODEL == "openrouter/free"
    assert _model_name(None) == "openrouter/free"


def test_ai_configuration_status_reports_missing_server_key(monkeypatch):
    from app.routers.ai_hiring_studio import _configuration_status

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    status = _configuration_status()

    assert status["server_key_configured"] is False
    assert status["key_source"] == "not configured"
    assert status["default_model"]


def test_ai_configuration_status_never_returns_server_key(monkeypatch):
    from app.routers.ai_hiring_studio import _configuration_status

    sentinel = "test-secret-must-never-be-returned"
    monkeypatch.setenv("OPENROUTER_API_KEY", sentinel)
    status = _configuration_status()

    assert status["server_key_configured"] is True
    assert status["key_source"] == "server environment"
    assert sentinel not in repr(status)
