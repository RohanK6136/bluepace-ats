from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException

from app.security import JWT_ALGORITHM, JWT_SECRET, get_current_user


class StubDatabase:
    def __init__(self, user_id=7, session=None):
        self.user_id = user_id
        self.session = session
        self.scalar_calls = 0

    def get(self, model, record_id):
        if record_id != self.user_id:
            return None
        return SimpleNamespace(id=self.user_id, is_active=True)

    def scalar(self, statement):
        self.scalar_calls += 1
        return self.session


def encode_access_token(payload):
    complete_payload = {
        "sub": "7",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        **payload,
    }
    return jwt.encode(complete_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def test_access_token_without_jti_is_rejected_even_if_signature_is_valid():
    token = encode_access_token({})
    db = StubDatabase()

    with pytest.raises(HTTPException) as error:
        get_current_user(token=token, db=db)

    assert error.value.status_code == 401
    assert db.scalar_calls == 0


def test_access_token_with_jti_but_no_persisted_session_is_rejected():
    token = encode_access_token({"jti": "unknown-session-id"})
    db = StubDatabase(session=None)

    with pytest.raises(HTTPException) as error:
        get_current_user(token=token, db=db)

    assert error.value.status_code == 401
    assert db.scalar_calls == 1


def test_access_token_with_active_persisted_session_remains_valid():
    token = encode_access_token({"jti": "valid-session-id"})
    session = SimpleNamespace(
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        revoked_at=None,
    )
    db = StubDatabase(session=session)

    user = get_current_user(token=token, db=db)

    assert user.id == 7
    assert db.scalar_calls == 1
