from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.main as main


def sample_resume_text() -> str:
    return "\n".join(
        f"Experience item {index}: built and maintained reliable Python services for internal teams."
        for index in range(12)
    )


class FakeCandidateSession:
    def __init__(self):
        self.committed = False

    def commit(self):
        self.committed = True


def test_candidate_review_api_stores_only_advisory_metadata(monkeypatch):
    candidate = SimpleNamespace(
        id=71,
        organization_id=42,
        resume_data={"skills": ["Python"], "years_of_experience": 4},
    )
    user = SimpleNamespace(organization_id=42)
    session = FakeCandidateSession()
    audit = {}

    def get_org_record(_db, _model, candidate_id, organization_id):
        assert candidate_id == 71
        assert organization_id == 42
        return candidate

    def audit_record(_db, _user, action, entity_type, entity_id, **kwargs):
        audit.update(action=action, entity_type=entity_type, entity_id=entity_id, **kwargs)

    monkeypatch.setattr(main, "_get_org_record", get_org_record)
    monkeypatch.setattr(main, "record_audit", audit_record)

    result = main.create_candidate_resume_text_review(
        71,
        main.CandidateResumeTextReviewRequest(text=sample_resume_text(), source="zoho_recruit"),
        user=user,
        db=session,
    )

    review = result["review"]
    assert session.committed is True
    assert result["candidate_id"] == 71
    assert result["decision_support_only"] is True
    assert result["not_used_for_matching"] is True
    assert review["assessment"] == "undetermined"
    assert review["source"] == "zoho_recruit"
    assert candidate.resume_data["skills"] == ["Python"]
    assert candidate.resume_data["resume_text_quality_review"] == review
    assert sample_resume_text() not in str(candidate.resume_data)
    assert sample_resume_text() not in str(audit)
    assert audit["action"] == "candidate.resume_text_quality_reviewed"
    assert "signal_codes" in audit["after"]
    assert audit["after"]["not_used_for_matching"] is True


def test_candidate_review_endpoint_scopes_candidate_to_requesting_org(monkeypatch):
    candidate = SimpleNamespace(id=71, organization_id=42, resume_data={})
    requested_organizations = []

    def get_org_record(_db, _model, candidate_id, organization_id):
        requested_organizations.append((candidate_id, organization_id))
        raise HTTPException(status_code=404, detail="Candidate not found")

    monkeypatch.setattr(main, "_get_org_record", get_org_record)
    with pytest.raises(HTTPException) as error:
        main.create_candidate_resume_text_review(
            71,
            main.CandidateResumeTextReviewRequest(text=sample_resume_text()),
            user=SimpleNamespace(organization_id=99),
            db=FakeCandidateSession(),
        )
    assert error.value.status_code == 404
    assert requested_organizations == [(71, 99)]
