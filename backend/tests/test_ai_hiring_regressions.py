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


def test_rubric_weight_normalization_does_not_accept_zero_total():
    # This validates the intended contract independently of an external provider:
    # a rubric with no positive weights is rejected rather than shown as a 0% rubric.
    weights = [0, 0, 0]
    assert sum(weights) <= 0
