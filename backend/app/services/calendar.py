import base64
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import SessionLocal
from app.models import CalendarConnection, CalendarEventSync, Interview, InterviewParticipant, User


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_API = "https://www.googleapis.com/calendar/v3"
MICROSOFT_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MICROSOFT_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MICROSOFT_API = "https://graph.microsoft.com/v1.0"

GOOGLE_SCOPES = "openid email profile https://www.googleapis.com/auth/calendar.events"
MICROSOFT_SCOPES = "openid profile email offline_access Calendars.ReadWrite"


class CalendarIntegrationError(RuntimeError):
    pass


def _public_backend_origin() -> str:
    return os.getenv("BACKEND_PUBLIC_ORIGIN", "https://bluepace-ats-11.onrender.com").rstrip("/")


def redirect_uri(provider: str) -> str:
    configured = os.getenv(f"{provider.upper()}_CALENDAR_REDIRECT_URI", "").strip()
    return configured or f"{_public_backend_origin()}/calendar/oauth/{provider}/callback"


def _client_credentials(provider: str) -> tuple[str, str]:
    prefix = provider.upper()
    client_id = os.getenv(f"{prefix}_CALENDAR_CLIENT_ID", "").strip()
    client_secret = os.getenv(f"{prefix}_CALENDAR_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise CalendarIntegrationError(f"{provider.title()} Calendar OAuth is not configured on the server.")
    return client_id, client_secret


def _fernet() -> Fernet:
    raw = os.getenv("CALENDAR_TOKEN_ENCRYPTION_KEY", "").strip()
    if raw:
        try:
            return Fernet(raw.encode())
        except Exception as exc:
            raise CalendarIntegrationError("CALENDAR_TOKEN_ENCRYPTION_KEY is invalid.") from exc
    secret = os.getenv("JWT_SECRET", "local-development-only-change-me").encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def encrypt_token(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().encrypt(value.encode()).decode()


def decrypt_token(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise CalendarIntegrationError("Stored calendar credentials cannot be decrypted.") from exc


def _post_form(url: str, data: dict) -> dict:
    payload = urllib.parse.urlencode(data).encode()
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise CalendarIntegrationError(f"Calendar provider rejected the request: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise CalendarIntegrationError(f"Calendar provider is unreachable: {exc}") from exc


def _api_request(url: str, access_token: str, method: str = "GET", payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise CalendarIntegrationError(f"Calendar API error {exc.code}: {detail[:700]}") from exc
    except urllib.error.URLError as exc:
        raise CalendarIntegrationError(f"Calendar API is unreachable: {exc}") from exc


def exchange_code(provider: str, code: str) -> dict:
    client_id, client_secret = _client_credentials(provider)
    if provider == "google":
        data = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri(provider),
            "grant_type": "authorization_code",
        }
        return _post_form(GOOGLE_TOKEN_URL, data)
    if provider == "microsoft":
        data = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri(provider),
            "grant_type": "authorization_code",
            "scope": MICROSOFT_SCOPES,
        }
        return _post_form(MICROSOFT_TOKEN_URL, data)
    raise CalendarIntegrationError("Unsupported calendar provider.")


def refresh_connection(db: Session, connection: CalendarConnection) -> str:
    access = decrypt_token(connection.access_token_encrypted)
    if connection.expires_at and connection.expires_at > datetime.now(timezone.utc) + timedelta(minutes=2):
        return access or ""
    refresh = decrypt_token(connection.refresh_token_encrypted)
    if not refresh:
        if access:
            return access
        raise CalendarIntegrationError("Calendar connection has no refresh token; reconnect the account.")

    client_id, client_secret = _client_credentials(connection.provider)
    if connection.provider == "google":
        token_data = _post_form(
            GOOGLE_TOKEN_URL,
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
        )
    else:
        token_data = _post_form(
            MICROSOFT_TOKEN_URL,
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
                "scope": MICROSOFT_SCOPES,
            },
        )
    new_access = token_data.get("access_token")
    if not new_access:
        raise CalendarIntegrationError("Calendar refresh did not return an access token.")
    connection.access_token_encrypted = encrypt_token(new_access) or ""
    if token_data.get("refresh_token"):
        connection.refresh_token_encrypted = encrypt_token(token_data["refresh_token"])
    connection.expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(token_data.get("expires_in", 3600)))
    connection.last_error = None
    db.commit()
    return new_access


def _connection_identity(provider: str, access_token: str) -> tuple[str | None, str | None, str | None]:
    if provider == "google":
        payload = _api_request("https://www.googleapis.com/oauth2/v3/userinfo", access_token)
        return payload.get("sub"), payload.get("email"), payload.get("name")
    payload = _api_request(
        MICROSOFT_API + "/me?$select=id,displayName,mail,userPrincipalName",
        access_token,
    )
    return payload.get("id"), payload.get("mail") or payload.get("userPrincipalName"), payload.get("displayName")


def save_oauth_connection(db: Session, user_id: int, organization_id: int, provider: str, token_data: dict) -> CalendarConnection:
    access = token_data.get("access_token")
    if not access:
        raise CalendarIntegrationError("OAuth exchange did not return an access token.")
    identity, email, name = _connection_identity(provider, access)
    existing = db.scalar(
        select(CalendarConnection).where(
            CalendarConnection.user_id == user_id,
            CalendarConnection.provider == provider,
        )
    )
    is_first = existing is None
    connection = existing or CalendarConnection(
        organization_id=organization_id,
        user_id=user_id,
        provider=provider,
        access_token_encrypted="",
    )
    connection.organization_id = organization_id
    connection.provider_account_id = identity
    connection.account_email = email
    connection.display_name = name
    connection.access_token_encrypted = encrypt_token(access) or ""
    if token_data.get("refresh_token"):
        connection.refresh_token_encrypted = encrypt_token(token_data["refresh_token"])
    connection.expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(token_data.get("expires_in", 3600)))
    connection.scopes = token_data.get("scope") or (GOOGLE_SCOPES if provider == "google" else MICROSOFT_SCOPES)
    connection.is_active = True
    connection.last_error = None
    if is_first:
        connection.is_default = True
        db.add(connection)
    db.commit()
    db.refresh(connection)
    return connection


def _attendees(db: Session, interview: Interview, candidate_email: str | None) -> list[dict]:
    ids = set(db.scalars(select(InterviewParticipant.user_id).where(InterviewParticipant.interview_id == interview.id)).all())
    ids.add(interview.interviewer_id)
    users = db.scalars(select(User).where(User.id.in_(ids), User.is_active.is_(True))).all() if ids else []
    result = [{"email": u.email, "name": u.full_name} for u in users if u.email]
    if candidate_email:
        result.append({"email": candidate_email, "name": "Candidate"})
    seen = set()
    return [item for item in result if not (item["email"].casefold() in seen or seen.add(item["email"].casefold()))]


def _event_payload(interview: Interview, application, provider: str, attendees: list[dict], generate_meeting: bool) -> dict:
    starts = interview.starts_at
    if starts.tzinfo is None:
        starts = starts.replace(tzinfo=timezone.utc)
    ends = starts + timedelta(minutes=interview.duration_minutes)
    summary = f"{interview.round_name} — {application.job.title}"
    description = (
        f"BluePace ATS interview for {application.candidate.first_name} {application.candidate.last_name}. "
        f"Round {interview.round_number} ({interview.round_type})."
    )
    if provider == "google":
        payload = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": starts.isoformat()},
            "end": {"dateTime": ends.isoformat()},
            "attendees": attendees,
            "guestsCanModify": False,
            "guestsCanSeeOtherGuests": True,
        }
        if interview.location:
            payload["location"] = interview.location
        if interview.meeting_url:
            payload["conferenceData"] = {"entryPoints": [{"entryPointType": "video", "uri": interview.meeting_url}]}
        elif generate_meeting and interview.mode == "online":
            payload["conferenceData"] = {
                "createRequest": {
                    "requestId": uuid4().hex,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
        return payload

    payload = {
        "subject": summary,
        "body": {"contentType": "HTML", "content": description},
        "start": {"dateTime": starts.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": ends.isoformat(), "timeZone": "UTC"},
        "attendees": [
            {"emailAddress": {"address": item["email"], "name": item["name"]}, "type": "required"}
            for item in attendees
        ],
    }
    if interview.location:
        payload["location"] = {"displayName": interview.location}
    if not interview.meeting_url and generate_meeting and interview.mode == "online":
        payload["isOnlineMeeting"] = True
        payload["onlineMeetingProvider"] = "teamsForBusiness"
    return payload


def _extract_join_url(provider: str, response: dict) -> str | None:
    if provider == "google":
        for point in (response.get("conferenceData") or {}).get("entryPoints") or []:
            if point.get("entryPointType") == "video" and point.get("uri"):
                return point["uri"]
        return None
    return ((response.get("onlineMeeting") or {}).get("joinUrl") or None)


def _set_connection_error(db: Session, connection: CalendarConnection, message: str):
    connection.last_error = message[:1000]
    db.commit()


def create_calendar_event(db: Session, connection: CalendarConnection, interview: Interview, application) -> CalendarEventSync | None:
    access = refresh_connection(db, connection)
    attendees = _attendees(db, interview, application.candidate.email)
    payload = _event_payload(interview, application, connection.provider, attendees, generate_meeting=True)
    if connection.provider == "google":
        url = f"{GOOGLE_API}/calendars/primary/events?conferenceDataVersion=1&sendUpdates=all"
    else:
        url = f"{MICROSOFT_API}/me/events"
    response = _api_request(url, access, "POST", payload)
    event_id = response.get("id")
    if not event_id:
        raise CalendarIntegrationError("Calendar provider did not return an event id.")
    sync = db.scalar(select(CalendarEventSync).where(CalendarEventSync.interview_id == interview.id, CalendarEventSync.connection_id == connection.id))
    if sync is None:
        sync = CalendarEventSync(
            organization_id=interview_application_org(interview, application),
            interview_id=interview.id,
            connection_id=connection.id,
            provider_event_id=event_id,
        )
        db.add(sync)
    sync.provider_event_id = event_id
    sync.join_url = _extract_join_url(connection.provider, response) or interview.meeting_url
    sync.status = "active"
    sync.last_error = None
    sync.last_synced_at = datetime.now(timezone.utc)
    if sync.join_url and not interview.meeting_url:
        interview.meeting_url = sync.join_url
    db.commit()
    return sync


def interview_application_org(interview: Interview, application) -> int:
    return int(application.organization_id)


def update_calendar_event(db: Session, sync: CalendarEventSync, connection: CalendarConnection, interview: Interview, application) -> None:
    access = refresh_connection(db, connection)
    attendees = _attendees(db, interview, application.candidate.email)
    payload = _event_payload(interview, application, connection.provider, attendees, generate_meeting=False)
    if connection.provider == "google":
        url = f"{GOOGLE_API}/calendars/primary/events/{urllib.parse.quote(sync.provider_event_id, safe='')}?conferenceDataVersion=1&sendUpdates=all"
    else:
        url = f"{MICROSOFT_API}/me/events/{urllib.parse.quote(sync.provider_event_id, safe='')}"
        payload.pop("isOnlineMeeting", None)
        payload.pop("onlineMeetingProvider", None)
    _api_request(url, access, "PATCH", payload)
    sync.status = "active"
    sync.last_error = None
    sync.last_synced_at = datetime.now(timezone.utc)
    db.commit()


def delete_calendar_event(db: Session, sync: CalendarEventSync, connection: CalendarConnection) -> None:
    access = refresh_connection(db, connection)
    if connection.provider == "google":
        url = f"{GOOGLE_API}/calendars/primary/events/{urllib.parse.quote(sync.provider_event_id, safe='')}?sendUpdates=all"
    else:
        url = f"{MICROSOFT_API}/me/events/{urllib.parse.quote(sync.provider_event_id, safe='')}"
    try:
        _api_request(url, access, "DELETE")
    except CalendarIntegrationError as exc:
        if "error 404" not in str(exc):
            raise
    sync.status = "deleted"
    sync.last_synced_at = datetime.now(timezone.utc)
    sync.last_error = None
    db.commit()


def _default_connection(db: Session, user_id: int, provider: str | None = None) -> CalendarConnection | None:
    stmt = select(CalendarConnection).where(CalendarConnection.user_id == user_id, CalendarConnection.is_active.is_(True))
    if provider:
        stmt = stmt.where(CalendarConnection.provider == provider)
    else:
        stmt = stmt.where(CalendarConnection.is_default.is_(True))
    return db.scalar(stmt.order_by(CalendarConnection.id.asc()).limit(1))


def sync_interview_calendar(interview_id: int, organization_id: int, user_id: int, action: str = "upsert") -> dict:
    db = SessionLocal()
    try:
        interview = db.scalar(
            select(Interview)
            .where(Interview.id == interview_id)
        )
        if interview is None:
            return {"status": "missing"}
        application = db.scalar(
            select(__import__("app.models", fromlist=["Application"]).Application)
            .where(
                __import__("app.models", fromlist=["Application"]).Application.id == interview.application_id,
                __import__("app.models", fromlist=["Application"]).Application.organization_id == organization_id,
            )
            .options(selectinload(__import__("app.models", fromlist=["Application"]).Application.job), selectinload(__import__("app.models", fromlist=["Application"]).Application.candidate)),
        )
        if application is None:
            return {"status": "missing_application"}
        connection = _default_connection(db, user_id)
        if connection is None:
            return {"status": "not_connected"}
        try:
            if action == "delete":
                sync = db.scalar(select(CalendarEventSync).where(CalendarEventSync.interview_id == interview.id, CalendarEventSync.connection_id == connection.id, CalendarEventSync.status != "deleted"))
                if sync:
                    delete_calendar_event(db, sync, connection)
            else:
                sync = db.scalar(select(CalendarEventSync).where(CalendarEventSync.interview_id == interview.id, CalendarEventSync.connection_id == connection.id, CalendarEventSync.status != "deleted"))
                if sync:
                    update_calendar_event(db, sync, connection, interview, application)
                else:
                    create_calendar_event(db, connection, interview, application)
            return {"status": "synced", "provider": connection.provider}
        except CalendarIntegrationError as exc:
            _set_connection_error(db, connection, str(exc))
            return {"status": "error", "provider": connection.provider, "error": str(exc)}
    finally:
        db.close()


def connection_payload(connection: CalendarConnection) -> dict:
    return {
        "id": connection.id,
        "provider": connection.provider,
        "account_email": connection.account_email,
        "display_name": connection.display_name,
        "is_default": connection.is_default,
        "is_active": connection.is_active,
        "last_error": connection.last_error,
    }
