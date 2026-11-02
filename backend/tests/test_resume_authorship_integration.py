from app.features.resume_authorship.integration import attach_resume_text_review, build_resume_text_review


def sample_resume() -> str:
    return "\n".join(
        f"Experience item {index}: built and maintained reliable Python services for internal teams."
        for index in range(12)
    )


def test_candidate_profile_integration_persists_only_derived_report():
    source_profile = {"skills": ["Python"], "years_of_experience": 4}
    updated, review = attach_resume_text_review(source_profile, sample_resume(), "resume_lab")

    assert source_profile == {"skills": ["Python"], "years_of_experience": 4}
    assert updated["skills"] == ["Python"]
    assert updated["resume_text_quality_review"] == review
    assert review["assessment"] == "undetermined"
    assert review["decision_support_only"] is True
    assert review["not_used_for_matching"] is True
    assert review["source"] == "resume_lab"
    assert review["reviewed_at"]
    assert "raw_text" not in updated
    assert sample_resume() not in str(updated)


def test_short_text_remains_insufficient_without_authorship_verdict():
    review = build_resume_text_review("Python developer with project experience.", "public_portal")

    assert review["assessment"] == "undetermined"
    assert review["status"] == "insufficient_evidence"
    assert review["confidence"] == "not_assessed"
    assert review["source"] == "public_portal"


def test_over_limit_text_is_not_partially_classified():
    review = build_resume_text_review("x" * 60_001, "zoho_recruit")

    assert review["assessment"] == "undetermined"
    assert review["status"] == "insufficient_evidence"
    assert review["confidence"] == "not_assessed"
    assert review["signals"][0]["code"] == "text_sample_too_large"
