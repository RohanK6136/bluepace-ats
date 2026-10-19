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
