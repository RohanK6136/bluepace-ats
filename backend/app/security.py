import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuthSession, Role, User

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET and os.getenv("APP_ENV", "development") not in {"development", "test"}:
    raise RuntimeError("JWT_SECRET must be configured outside development and test environments")
JWT_SECRET = JWT_SECRET or "local-development-only-change-me"
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
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def decode_candidate_portal_token(token: str) -> int:
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
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
    jti = payload.get("jti")
    if jti:
        session = db.scalar(
            select(AuthSession).where(
                AuthSession.jti == str(jti),
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

    session.revoked_at = now
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
