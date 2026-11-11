from datetime import datetime, timezone

import jwt
import pytest

import app.security as security


def test_candidate_portal_tokens_use_a_separate_signing_secret(monkeypatch):
    monkeypatch.setattr(security, "JWT_SECRET", "recruiter-session-signing-secret")
    monkeypatch.setattr(security, "CANDIDATE_PORTAL_JWT_SECRET", "candidate-portal-dedicated-secret")

    token = security.create_candidate_portal_token(42)
    payload = jwt.decode(
        token,
        "candidate-portal-dedicated-secret",
        algorithms=[security.JWT_ALGORITHM],
    )

    assert payload["application_id"] == 42
    assert payload["kind"] == "candidate_portal"
    assert security.decode_candidate_portal_token(token) == 42


def test_candidate_portal_token_cannot_be_forged_with_recruiter_secret(monkeypatch):
    monkeypatch.setattr(security, "JWT_SECRET", "recruiter-session-signing-secret")
    monkeypatch.setattr(security, "CANDIDATE_PORTAL_JWT_SECRET", "candidate-portal-dedicated-secret")
    forged_with_recruiter_key = jwt.encode(
        {
            "application_id": 42,
            "kind": "candidate_portal",
            "exp": datetime.now(timezone.utc).timestamp() + 300,
        },
        "recruiter-session-signing-secret",
        algorithm=security.JWT_ALGORITHM,
    )

    with pytest.raises(jwt.InvalidTokenError):
        security.decode_candidate_portal_token(forged_with_recruiter_key)
