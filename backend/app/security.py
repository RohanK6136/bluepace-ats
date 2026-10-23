import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuthSession, Role, User
from app.services.security_config import resolve_candidate_portal_secret, resolve_jwt_secret

APP_ENV = os.getenv("APP_ENV", "development")
RAILWAY_ENVIRONMENT_NAME = os.getenv("RAILWAY_ENVIRONMENT_NAME", "").strip()
JWT_SECRET, USING_DEVELOPMENT_JWT_FALLBACK = resolve_jwt_secret(
    os.getenv("JWT_SECRET"),
    APP_ENV,
    RAILWAY_ENVIRONMENT_NAME,
)
CANDIDATE_PORTAL_JWT_SECRET, USING_CANDIDATE_PORTAL_JWT_FALLBACK = (
    resolve_candidate_portal_secret(
        os.getenv("CANDIDATE_PORTAL_JWT_SECRET"),
        JWT_SECRET,
        APP_ENV,
        RAILWAY_ENVIRONMENT_NAME,
    )
)
if USING_DEVELOPMENT_JWT_FALLBACK:
    print(
        "[security] WARNING: the development-only recruiter JWT fallback is active. "
        "Use explicit signing keys in production.",
        flush=True,
    )
if USING_CANDIDATE_PORTAL_JWT_FALLBACK and RAILWAY_ENVIRONMENT_NAME.lower() == "production":
    # Normally blocked by resolve_candidate_portal_secret; retain a guarded
    # diagnostic if platform environment metadata changes unexpectedly.
    print(
        "[security] WARNING: candidate portal signing is using a fallback key.",
        flush=True,
    )
JWT_ALGORITHM = "HS256"
TOKEN_LIFETIME_MINUTES = 7 * 24 * 60
TOKEN_REFRESH_GRACE_MINUTES = 60
password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def create_access_token(user: User, db: Session | None = None, ip_address: str | None = None, user_agent: str | None = None) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_LIFETIME_MINUTES)
    jti = uuid4().hex
    token = jwt.encode(
        {"sub": str(user.id), "org": user.organization_id, "role": user.role.value, "jti": jti, "exp": expires_at},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    if db is not None:
        db.add(
            AuthSession(
                user_id=user.id,
                jti=jti,
                expires_at=expires_at,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        db.commit()
    return token


def create_candidate_portal_token(application_id: int) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    return jwt.encode(
        {"application_id": int(application_id), "kind": "candidate_portal", "exp": expires_at},
        CANDIDATE_PORTAL_JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def decode_candidate_portal_token(token: str) -> int:
    payload = jwt.decode(token, CANDIDATE_PORTAL_JWT_SECRET, algorithms=[JWT_ALGORITHM])
    if payload.get("kind") != "candidate_portal" or "application_id" not in payload:
        raise jwt.InvalidTokenError("Invalid candidate portal token")
    return int(payload["application_id"])


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized

    # Every recruiter access token must map to a persisted, non-revoked session.
    # Without this check, a token signed with a predictable fallback secret and
    # lacking a jti would bypass the session lookup entirely.
    jti = payload.get("jti")
    if not isinstance(jti, str) or not jti:
        raise unauthorized

    session = db.scalar(
        select(AuthSession).where(
            AuthSession.jti == jti,
            AuthSession.user_id == user.id,
        )
    )
    now = datetime.now(timezone.utc)
    expires_at = _as_utc(session.expires_at if session is not None else None)
    revoked_at = _as_utc(session.revoked_at if session is not None else None)
    if session is None or revoked_at is not None or expires_at is None or expires_at <= now:
        raise unauthorized
    return user


def require_roles(*roles: Role):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return dependency

def refresh_access_token(token: str, db: Session) -> str:
    """Rotate an access token while its persisted session is still valid.

    A short grace period allows sleeping browser tabs to recover without forcing
    recruiters back through the login screen, while revocation still blocks refresh.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            options={"verify_exp": False},
        )
        user_id = int(payload["sub"])
        jti = str(payload.get("jti") or "")
        expires_at = datetime.fromtimestamp(float(payload["exp"]), tz=timezone.utc)
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError, OverflowError):
        raise unauthorized

    now = datetime.now(timezone.utc)
    if not jti or expires_at + timedelta(minutes=TOKEN_REFRESH_GRACE_MINUTES) <= now:
        raise unauthorized

    user = db.get(User, user_id)
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.jti == jti,
            AuthSession.user_id == user_id,
        )
    )
    if user is None or not user.is_active or session is None:
        raise unauthorized
    session_expires_at = _as_utc(session.expires_at)
    if _as_utc(session.revoked_at) is not None or session_expires_at is None or session_expires_at + timedelta(minutes=TOKEN_REFRESH_GRACE_MINUTES) <= now:
        raise unauthorized

    # Rotate atomically. With concurrent refreshes, two workers may both
    # have read this session before either writes; a conditional UPDATE ensures
    # only the first worker can revoke the still-active row.
    rotation = db.execute(
        update(AuthSession)
        .where(
            AuthSession.id == session.id,
            AuthSession.user_id == user_id,
            AuthSession.jti == jti,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now - timedelta(minutes=TOKEN_REFRESH_GRACE_MINUTES),
        )
        .values(revoked_at=now)
        .execution_options(synchronize_session=False)
    )
    if rotation.rowcount != 1:
        db.rollback()
        raise unauthorized

    db.commit()
    return create_access_token(user, db=db)

def revoke_access_token(token: str, db: Session) -> bool:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        jti = payload.get("jti")
    except jwt.InvalidTokenError:
        return False
    if not jti:
        return False
    session = db.scalar(select(AuthSession).where(AuthSession.jti == str(jti)))
    if session is None:
        return False
    session.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return True
