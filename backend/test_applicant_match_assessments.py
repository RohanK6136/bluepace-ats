from app.routers.ai_hiring_studio import _safe_applicant_match_assessment


def test_safe_applicant_match_assessment_keeps_scores_but_drops_resume_text():
    source = {
        "request_id": "req-1",
        "status": "complete",
        "scores": {
            "match": 82,
            "required_skills": {"pct": 80, "met": 4, "partial": 1, "total": 6},
            "preferred_skills": {"pct": 50, "met": 1, "partial": 0, "total": 2},
            "experience": {"pct": 75, "relevant_years": 3.5, "total_years": 5, "required_years": 4},
            "education": {"pct": 100, "level": "bachelor", "required": "bachelor"},
            "groups": [{"label": "Python", "pct": 90, "met": 1, "partial": 0, "total": 1}],
        },
        "profile": {"name": "Sensitive Candidate Name", "email": "secret@example.invalid"},
        "summary": {"value": "Sensitive Candidate Name has a private history."},
        "evidence": [{
            "label": "Python",
            "status": "met",
            "importance": "must",
            "group": "coding",
            "lines": [{"id": "L1", "text": "SECRET RESUME EXCERPT"}],
            "note": "SECRET NARRATIVE",
        }],
        "gaps": [{"label": "Kubernetes", "status": "not_evidenced", "importance": "nice", "note": "SECRET GAP NARRATIVE"}],
        "flags": ["manual review"],
    }

    result = _safe_applicant_match_assessment(source)
    serialized = str(result)

    assert result["match_score"] == 82
    assert result["scores"]["required_skills"]["met"] == 4
    assert result["evidence"] == [{"label": "Python", "status": "met", "importance": "must", "group": "coding"}]
    assert result["gaps"] == [{"label": "Kubernetes", "status": "not_evidenced", "importance": "nice"}]
    assert result["decision_support_only"] is True
    for private_value in (
        "Sensitive Candidate Name", "secret@example.invalid", "SECRET RESUME EXCERPT",
        "SECRET NARRATIVE", "SECRET GAP NARRATIVE",
    ):
        assert private_value not in serialized


def test_safe_applicant_match_assessment_bounds_untrusted_scores_and_items():
    result = _safe_applicant_match_assessment({
        "scores": {"match": 1000},
        "evidence": [{"label": "Bad score", "status": "not_a_status"}],
        "gaps": [],
        "flags": [],
    })

    assert result["match_score"] is None
    assert result["evidence"] == []
    assert result["status"] == "complete"
