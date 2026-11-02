from app.features.jd_standardizer.pipeline.quality import assess_jd_quality


GOOD_JD = """Senior Backend Engineer
Location: Hyderabad, India
Work mode: Hybrid
Employment type: Full-time

About the role
Build and operate secure services for customer-facing products.

Responsibilities
- Design and maintain Python services and REST APIs.
- Improve database performance and service reliability.
- Work with product and engineering teams to deliver releases.

Required qualifications
- 4+ years of backend engineering experience.
- Strong Python and FastAPI skills.
- Experience with PostgreSQL and automated testing.

Preferred skills
- Experience with Docker and cloud deployment.
"""


def test_quality_score_is_deterministic_and_uses_expected_weights():
    first = assess_jd_quality(GOOD_JD)
    second = assess_jd_quality(GOOD_JD)

    assert first == second
    assert first["score"] == sum(item["score"] for item in first["categories"])
    assert sum(item["max_score"] for item in first["categories"]) == 100
    assert first["band"] in {"strong", "good", "needs_improvement", "incomplete"}


def test_quality_report_identifies_missing_title_and_context():
    result = assess_jd_quality(
        "We need someone to help with various tasks. Some experience is useful."
    )

    codes = {item["code"] for item in result["findings"]}
    assert "missing_role_title" in codes
    assert "responsibilities_need_detail" in codes
    assert "location_missing" in codes
    assert "work_mode_missing" in codes
    assert "employment_type_missing" in codes


def test_quality_report_recognises_fractional_experience_and_seniority():
    result = assess_jd_quality(
        "Data Engineer\nRequirements\n- 1.5 to 3.5 years of Python experience."
    )

    experience = next(item for item in result["categories"] if item["id"] == "experience")
    assert experience["score"] == 15


def test_quality_report_flags_repeated_content():
    result = assess_jd_quality(
        "Platform Engineer\nResponsibilities\n- Build reliable service platform for teams.\n"
        "- Build reliable service platform for teams."
    )

    assert any(item["code"] == "repeated_content" for item in result["findings"])


def test_quality_report_does_not_treat_optional_preferred_section_as_required():
    result = assess_jd_quality(
        "Engineer\nResponsibilities\n- Build APIs.\n- Maintain services.\n- Review code.\n"
        "Requirements\n- Python experience.\n- REST APIs.\n- SQL knowledge."
    )

    assert any(item["code"] == "preferred_requirements_not_separated" for item in result["findings"])


def test_quality_report_rejects_blank_input():
    import pytest

    with pytest.raises(ValueError, match="required"):
        assess_jd_quality("   ")
