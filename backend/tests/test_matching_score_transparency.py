from types import SimpleNamespace

from app.services.matching import CandidateMatcher, MATCH_WEIGHTS


def test_candidate_score_exposes_a_reproducible_weighted_breakdown():
    matcher = CandidateMatcher()
    matcher.embedding_client = None

    job = SimpleNamespace(
        title="Python Engineer",
        description="Build Python services and SQL data pipelines. Tableau preferred.",
        location="Remote",
        work_mode="remote",
        required_skills=["Python", "SQL"],
        minimum_experience_years=2,
        fresher_allowed=False,
        jd_analysis={
            "required_skills": ["Python", "SQL"],
            "preferred_skills": ["Tableau"],
            "minimum_experience_years": 2,
            "education": "Bachelor degree",
            "location": "Remote",
            "work_mode": "remote",
            "fresher_allowed": False,
        },
        embedding=None,
    )
    candidate = SimpleNamespace(
        first_name="Asha",
        last_name="Rao",
        resume_data={
            "skills": ["Python", "Tableau"],
            "experience": [{"title": "Developer", "duration": "2 years"}],
            "education": [{"degree": "Bachelor of Science"}],
            "projects": [{"title": "Python reporting project"}],
            "extraction_evidence": [
                {"field": "skills", "confidence": 0.95, "source_lines": [6]}
            ],
        },
        embedding=None,
        cv_summary=["Experience and skills parsed from the supplied resume."],
    )

    result = matcher.score_candidate(job, candidate)

    breakdown = result["score_breakdown"]
    weights = result["score_weights"]
    weighted_total = round(sum(breakdown[key] * weight for key, weight in weights.items()))

    assert abs(sum(weights.values()) - 1.0) < 1e-9
    assert set(weights).issubset(breakdown)
    assert result["model_score"] == weighted_total
    assert result["decision_support_only"] is True
    assert result["skill_gaps"] == ["SQL"]
    assert result["match_evidence"]["required_skills"][0]["skill"] == "Python"
    assert result["match_evidence"]["required_skills"][0]["sources"][0]["source_lines"] == [6]
    assert MATCH_WEIGHTS == weights


def test_score_breakdown_and_weights_use_percentages_and_fractional_weights():
    assert all(0 <= weight <= 1 for weight in MATCH_WEIGHTS.values())
    assert abs(sum(MATCH_WEIGHTS.values()) - 1.0) < 1e-9
