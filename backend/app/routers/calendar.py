import os
import urllib.parse

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.database import get_db
from app.models import CalendarConnection, Role, User
from app.security import JWT_ALGORITHM, JWT_SECRET, require_roles
from app.services.calendar import (
    GOOGLE_AUTH_URL,
    GOOGLE_SCOPES,
    MICROSOFT_AUTH_URL,
    MICROSOFT_SCOPES,
    CalendarIntegrationError,
    connection_payload,
    exchange_code,
    redirect_uri,
    save_oauth_connection,
)
from sqlalchemy import select
from sqlalchemy.orm import Session


router = APIRouter(prefix="/calendar", tags=["calendar"])
READ_ROLES = (Role.admin, Role.recruiter, Role.hiring_manager, Role.interviewer)
WRITE_ROLES = (Role.admin, Role.recruiter)


def _frontend_origin() -> str:
    return os.getenv("FRONTEND_PUBLIC_ORIGIN", "https://bluepace-ats-frontend.onrender.com").rstrip("/")


def _state(user: User, provider: str) -> str:
    from datetime import datetime, timedelta, timezone
    return jwt.encode(
        {
            "kind": "calendar_oauth",
            "sub": str(user.id),
            "org": user.organization_id,
            "provider": provider,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def _decode_state(value: str, provider: str) -> tuple[int, int]:
    try:
        payload = jwt.decode(value, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("kind") != "calendar_oauth" or payload.get("provider") != provider:
            raise ValueError("invalid state")
        return int(payload["sub"]), int(payload["org"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired calendar OAuth state.") from exc


@router.get("/connections")
def list_calendar_connections(
    user: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(CalendarConnection)
        .where(CalendarConnection.user_id == user.id, CalendarConnection.organization_id == user.organization_id)
        .order_by(CalendarConnection.provider.asc())
    ).all()
    return [connection_payload(row) for row in rows]


@router.get("/oauth/{provider}/start")
def start_calendar_oauth(
    provider: str,
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    if provider not in {"google", "microsoft"}:
        raise HTTPException(status_code=400, detail="Provider must be google or microsoft.")
    try:
        from app.services.calendar import _client_credentials
        client_id, _ = _client_credentials(provider)
    except CalendarIntegrationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    state = _state(user, provider)
    if provider == "google":
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri(provider),
            "response_type": "code",
            "scope": GOOGLE_SCOPES,
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
        url = GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)
    else:
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri(provider),
            "response_type": "code",
            "response_mode": "query",
            "scope": MICROSOFT_SCOPES,
            "prompt": "select_account",
            "state": state,
        }
        url = MICROSOFT_AUTH_URL + "?" + urllib.parse.urlencode(params)
    return {"authorization_url": url, "provider": provider}


@router.get("/oauth/{provider}/callback")
def calendar_oauth_callback(
    provider: str,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if provider not in {"google", "microsoft"}:
        return RedirectResponse(_frontend_origin() + "?calendar=error&message=Unsupported%20provider")
    if error:
        return RedirectResponse(_frontend_origin() + "?calendar=error&message=" + urllib.parse.quote(error))
    if not code or not state:
        return RedirectResponse(_frontend_origin() + "?calendar=error&message=Missing%20OAuth%20code")
    try:
        user_id, organization_id = _decode_state(state, provider)
        user = db.get(User, user_id)
        if user is None or not user.is_active or user.organization_id != organization_id:
            raise HTTPException(status_code=403, detail="Calendar OAuth user is no longer active.")
        token_data = exchange_code(provider, code)
        save_oauth_connection(db, user.id, user.organization_id, provider, token_data)
    except (HTTPException, CalendarIntegrationError) as exc:
        message = exc.detail if isinstance(exc, HTTPException) else str(exc)
        return RedirectResponse(_frontend_origin() + "?calendar=error&message=" + urllib.parse.quote(message[:300]))
    return RedirectResponse(_frontend_origin() + "?calendar=connected&provider=" + urllib.parse.quote(provider))


@router.patch("/connections/{connection_id}/default")
def set_default_calendar(
    connection_id: int,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    connection = db.scalar(
        select(CalendarConnection).where(
            CalendarConnection.id == connection_id,
            CalendarConnection.user_id == user.id,
            CalendarConnection.organization_id == user.organization_id,
            CalendarConnection.is_active.is_(True),
        )
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Calendar connection not found.")
    db.query(CalendarConnection).filter(
        CalendarConnection.user_id == user.id,
        CalendarConnection.organization_id == user.organization_id,
    ).update({"is_default": False}, synchronize_session=False)
    connection.is_default = True
    db.commit()
    db.refresh(connection)
    return connection_payload(connection)


@router.delete("/connections/{connection_id}")
def disconnect_calendar(
    connection_id: int,
    user: User = Depends(require_roles(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    connection = db.scalar(
        select(CalendarConnection).where(
            CalendarConnection.id == connection_id,
            CalendarConnection.user_id == user.id,
            CalendarConnection.organization_id == user.organization_id,
        )
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Calendar connection not found.")
    was_default = connection.is_default
    connection.is_active = False
    connection.is_default = False
    if was_default:
        replacement = db.scalar(
            select(CalendarConnection)
            .where(
                CalendarConnection.user_id == user.id,
                CalendarConnection.organization_id == user.organization_id,
                CalendarConnection.id != connection.id,
                CalendarConnection.is_active.is_(True),
            )
            .order_by(CalendarConnection.id.asc())
            .limit(1)
        )
        if replacement:
            replacement.is_default = True
    db.commit()
    return {"status": "disconnected", "provider": connection.provider}
