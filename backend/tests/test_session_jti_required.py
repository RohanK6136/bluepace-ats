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



class StubRefreshDatabase(StubDatabase):
    def __init__(self, update_rowcount):
        self.user = SimpleNamespace(
            id=7,
            organization_id=11,
            role=SimpleNamespace(value="admin"),
            is_active=True,
        )
        self.session = SimpleNamespace(
            id=44,
            user_id=7,
            jti="refresh-session-jti",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            revoked_at=None,
        )
        self.update_rowcount = update_rowcount
        self.statement = None
        self.commit_calls = 0
        self.rollback_calls = 0
        self.added = []

    def get(self, model, record_id):
        return self.user if record_id == self.user.id else None

    def scalar(self, statement):
        return self.session

    def execute(self, statement):
        self.statement = statement
        if self.update_rowcount == 1:
            # Simulate the one worker that wins the atomic conditional update.
            self.session.revoked_at = datetime.now(timezone.utc)
        return SimpleNamespace(rowcount=self.update_rowcount)

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1

    def add(self, value):
        self.added.append(value)


def encode_refreshable_token():
    payload = {
        "sub": "7",
        "org": 11,
        "role": "admin",
        "jti": "refresh-session-jti",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def test_concurrent_refresh_loser_is_rejected_without_issuing_another_token():
    from app.security import refresh_access_token

    db = StubRefreshDatabase(update_rowcount=0)

    with pytest.raises(HTTPException) as error:
        refresh_access_token(encode_refreshable_token(), db)

    assert error.value.status_code == 401
    assert db.rollback_calls == 1
    assert db.commit_calls == 0
    assert db.added == []


def test_refresh_uses_conditional_update_and_issues_replacement_session():
    from sqlalchemy.dialects import sqlite

    from app.models import AuthSession
    from app.security import refresh_access_token

    db = StubRefreshDatabase(update_rowcount=1)
    replacement = refresh_access_token(encode_refreshable_token(), db)

    assert isinstance(replacement, str)
    assert replacement
    assert db.commit_calls == 2
    assert db.rollback_calls == 0
    assert len(db.added) == 1
    assert isinstance(db.added[0], AuthSession)
    assert db.added[0].jti != "refresh-session-jti"

    sql = str(db.statement.compile(dialect=sqlite.dialect()))
    assert "revoked_at IS NULL" in sql
    assert "expires_at >" in sql
