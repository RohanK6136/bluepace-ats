"""Browser authentication using HttpOnly cookies and double-submit CSRF protection.

The legacy Bearer endpoints remain available for API clients. Browser clients should
use /auth/session/* and never store access tokens in Web Storage.
"""
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuthSession, User
from app.schemas import UserRead
from app.security import (
    TOKEN_LIFETIME_MINUTES,
    create_access_token,
    password_hash,
    refresh_access_token,
    revoke_access_token,
)

router = APIRouter(prefix="/auth/session", tags=["browser-auth"])
APP_ENV = os.getenv("APP_ENV", "development").lower()
RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT_NAME", "").strip().lower()
IS_PRODUCTION = APP_ENV not in {"development", "test"} or RAILWAY_ENV == "production"
COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "true" if IS_PRODUCTION else "false").lower() == "true"
COOKIE_SAMESITE = os.getenv("AUTH_COOKIE_SAMESITE", "none" if COOKIE_SECURE else "lax").lower()
if COOKIE_SAMESITE not in {"lax", "strict", "none"}:
    COOKIE_SAMESITE = "none" if COOKIE_SECURE else "lax"
if COOKIE_SAMESITE == "none" and not COOKIE_SECURE:
    # Browsers reject SameSite=None cookies without Secure.
    COOKIE_SAMESITE = "lax"

ACCESS_COOKIE = "bluepace_access"
CSRF_COOKIE = "bluepace_csrf"


def _set_session_cookies(response: Response, access_token: str) -> None:
    max_age = TOKEN_LIFETIME_MINUTES * 60
    common = {"max_age": max_age, "path": "/", "secure": COOKIE_SECURE, "samesite": COOKIE_SAMESITE}
    response.set_cookie(ACCESS_COOKIE, access_token, httponly=True, **common)
    response.set_cookie(CSRF_COOKIE, secrets.token_urlsafe(32), httponly=False, **common)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/", secure=COOKIE_SECURE, httponly=True, samesite=COOKIE_SAMESITE)
    response.delete_cookie(CSRF_COOKIE, path="/", secure=COOKIE_SECURE, httponly=False, samesite=COOKIE_SAMESITE)
    response.headers["Cache-Control"] = "no-store"


def _require_csrf(request: Request) -> None:
    cookie = request.cookies.get(CSRF_COOKIE, "")
    supplied = request.headers.get("X-CSRF-Token", "")
    if not cookie or not supplied or not hmac.compare_digest(cookie, supplied):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")


@router.post("/login")
def browser_login(
    response: Response,
    credentials: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    email = credentials.username.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    now = datetime.now(timezone.utc)
    if user is not None and user.locked_until is not None and user.locked_until > now:
        raise HTTPException(status_code=429, detail="Account temporarily locked after repeated failed sign-in attempts.")
    valid = bool(user and user.is_active and password_hash.verify(credentials.password, user.password_hash))
    if not valid:
        if user is not None:
            user.failed_login_attempts = int(user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= 5:
                user.locked_until = now + timedelta(minutes=15)
            db.commit()
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    user.failed_login_attempts = 0
    user.locked_until = None
    access_token = create_access_token(user, db=db)
    _set_session_cookies(response, access_token)
    return {"user": UserRead.model_validate(user), "auth_mode": "httpOnly-cookie"}


@router.post("/refresh")
def browser_refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    _require_csrf(request)
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
    rotated = refresh_access_token(token, db)
    _set_session_cookies(response, rotated)
    return {"status": "refreshed", "auth_mode": "httpOnly-cookie"}


@router.post("/logout")
def browser_logout(request: Request, response: Response, db: Session = Depends(get_db)):
    _require_csrf(request)
    token = request.cookies.get(ACCESS_COOKIE)
    revoked = revoke_access_token(token, db) if token else False
    _clear_session_cookies(response)
    return {"status": "signed_out", "revoked": revoked}
