from app.services.match_explanation import build_match_explanation


def test_match_explanation_is_compact_and_neutral():
    result = build_match_explanation(
        candidate_name="Asha Rao",
        job_title="Python Backend Engineer",
        match_score=82,
        matched_required=["Python", "FastAPI"],
        matched_preferred=["PostgreSQL"],
        skill_gaps=["Kubernetes"],
        experience_years=2.5,
        required_experience_years=3,
        evidence=[{"type": "experience", "title": "Backend Engineer", "details": "Built FastAPI services."}],
    )

    assert result["review_signal"] == "Strong evidence"
    assert result["decision_support_only"] is True
    assert "Required skills evidenced" in result["strengths"][0]
    assert result["gaps"] == ["Kubernetes"]
    assert result["review_flags"]
    assert len(result["evidence"]) == 1
    assert "recommend" not in result["summary"].lower()


def test_match_explanation_handles_missing_evidence():
    result = build_match_explanation(
        candidate_name="Sam",
        job_title="Data Engineer",
        match_score=25,
    )

    assert result["review_signal"] == "Limited evidence"
    assert result["strengths"] == []
    assert result["gaps"] == []
    assert result["review_flags"]
    assert result["decision_support_only"] is True
