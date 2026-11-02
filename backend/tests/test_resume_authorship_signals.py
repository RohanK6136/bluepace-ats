from app.features.resume_authorship.analysis import assess_resume_text


def test_short_resume_is_insufficient_and_never_claims_authorship():
    result = assess_resume_text("Python developer with project experience.")
    assert result["assessment"] == "undetermined"
    assert result["status"] == "insufficient_evidence"
    assert result["confidence"] == "not_assessed"
    assert result["human_review_required"] is True


def test_repeated_content_is_flagged_as_quality_signal_not_ai_detection():
    repeated = "Delivered Python automation that reduced manual reporting time by 30 percent."
    text = "\n".join(["Professional Experience", repeated, repeated] + [f"Project detail {i}: built and maintained internal tools." for i in range(12)])
    result = assess_resume_text(text)
    assert result["status"] == "review_recommended"
    assert any(signal["code"] == "repeated_content" for signal in result["signals"])
    assert result["assessment"] == "undetermined"
    assert "No AI-authorship probability or binary verdict is produced." in result["limitations"]


def test_clean_long_resume_does_not_receive_authorship_verdict():
    text = "\n".join(f"Experience item {i}: designed and maintained production software services." for i in range(20))
    result = assess_resume_text(text)
    assert result["status"] == "no_text_quality_alerts"
    assert result["assessment"] == "undetermined"


def test_text_size_limit_is_enforced():
    try:
        assess_resume_text("x" * 60_001)
    except ValueError as error:
        assert "60000" in str(error)
    else:
        raise AssertionError("expected size validation")
