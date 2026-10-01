import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Role, User

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET and os.getenv("APP_ENV", "development") not in {"development", "test"}:
    raise RuntimeError("JWT_SECRET must be configured outside development and test environments")
JWT_SECRET = JWT_SECRET or "local-development-only-change-me"
JWT_ALGORITHM = "HS256"
TOKEN_LIFETIME_MINUTES = 30
password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def create_access_token(user: User) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_LIFETIME_MINUTES)
    return jwt.encode(
        {"sub": str(user.id), "org": user.organization_id, "role": user.role.value, "exp": expires_at},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


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
    return user


def require_roles(*roles: Role):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return dependency