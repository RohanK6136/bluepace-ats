"""Secure, read-only Zoho Recruit import for BluePace ATS."""
import asyncio
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode
from urllib.request import Request, urlopen

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import DateTime, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column
import hmac

from app.database import Base, SessionLocal, get_db
from app.models import Candidate, Job, Organization, Role, User
from app.security import get_current_user

router = APIRouter(prefix="/integrations/zoho", tags=["Zoho Recruit"])
ACCOUNTS = {
    "com": "https://accounts.zoho.com", "in": "https://accounts.zoho.in",
    "eu": "https://accounts.zoho.eu", "com.au": "https://accounts.zoho.com.au",
    "jp": "https://accounts.zoho.jp", "ca": "https://accounts.zohocloud.ca",
    "com.cn": "https://accounts.zoho.com.cn", "sa": "https://accounts.zoho.sa",
}
DEFAULT_API = "https://recruit.zoho.in/recruit/v2"


class ZohoSyncRecord(Base):
    __tablename__ = "zoho_sync_records"
    __table_args__ = (UniqueConstraint("organization_id", "module", "zoho_id", name="uq_zoho_sync_external"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    module: Mapped[str] = mapped_column(String(40))
    zoho_id: Mapped[str] = mapped_column(String(100))
    local_id: Mapped[int] = mapped_column(Integer)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ZohoSyncRun(Base):
    """Durable, payload-free history for manual, webhook and scheduled reconciliations."""
    __tablename__ = "zoho_sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
    status: Mapped[str] = mapped_column(String(20), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    candidates_synced: Mapped[int] = mapped_column(Integer, default=0)
    jobs_synced: Mapped[int] = mapped_column(Integer, default=0)
    error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)


def _sync_interval_minutes() -> int:
    try:
        configured = int(os.getenv("ZOHO_SYNC_INTERVAL_MINUTES", "15"))
    except (TypeError, ValueError):
        configured = 15
    return min(1440, max(5, configured))


def _sync_run_payload(run: ZohoSyncRun | None) -> dict | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "trigger": run.trigger,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "candidates_synced": run.candidates_synced or 0,
        "jobs_synced": run.jobs_synced or 0,
        # Store only a class name, never exception messages, tokens or record data.
        "error_type": run.error_type,
    }


def _execute_sync(db: Session, org: Organization, actor: User, trigger: str) -> dict:
    """Run reconciliation and persist an audit outcome without personal payload data."""
    run = ZohoSyncRun(
        organization_id=org.id,
        trigger=trigger,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    run_id = run.id

    try:
        result = sync_zoho_for_organization(db, org, actor)
        stored_run = db.get(ZohoSyncRun, run_id)
        if stored_run is not None:
            stored_run.status = "success"
            stored_run.candidates_synced = int(result.get("candidates_synced", 0))
            stored_run.jobs_synced = int(result.get("jobs_synced", 0))
            stored_run.completed_at = datetime.now(timezone.utc)
            stored_run.error_type = None
            db.commit()
        return {**result, "run_id": run_id, "trigger": trigger, "status": "success"}
    except Exception as exc:
        db.rollback()
        stored_run = db.get(ZohoSyncRun, run_id)
        if stored_run is not None:
            stored_run.status = "failed"
            stored_run.completed_at = datetime.now(timezone.utc)
            stored_run.error_type = type(exc).__name__[:100]
            db.commit()
        raise


def _settings():
    required = ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN")
    if not all(os.getenv(k, "").strip() for k in required):
        raise HTTPException(503, "Zoho Recruit integration is not configured on the backend.")
    domain = os.getenv("ZOHO_ACCOUNTS_DOMAIN", "in").strip().lower()
    api_base = os.getenv("ZOHO_RECRUIT_API_BASE", DEFAULT_API).strip().rstrip("/")
    if domain not in ACCOUNTS:
        raise HTTPException(500, "ZOHO_ACCOUNTS_DOMAIN is invalid.")
    from urllib.parse import urlparse
    parsed = urlparse(api_base)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host.endswith(".zohoapis.com") or host.endswith(".zohoapis.in") or host.endswith(".zohoapis.eu") or host.endswith(".zohoapis.com.au") or host.endswith(".zohoapis.jp") or host.endswith(".zohoapis.ca") or host.endswith(".zohoapis.com.cn") or host.endswith(".zohoapis.sa") or host == "recruit.zoho.in" or host == "recruit.zoho.com"):
        raise HTTPException(500, "ZOHO_RECRUIT_API_BASE must be an approved HTTPS Zoho Recruit API host.")
    return ACCOUNTS[domain], api_base


def _http_json(url: str, data: bytes | None = None, headers: dict | None = None) -> dict:
    request = Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urlopen(request, timeout=25) as response:
            import json
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise HTTPException(502, "Zoho rejected the integration credentials or module permissions.") from exc
        if exc.code == 429:
            raise HTTPException(503, "Zoho API rate limit reached; the next scheduled sync will retry.") from exc
        raise HTTPException(502, f"Zoho API request failed with HTTP {exc.code}.") from exc
    except (URLError, TimeoutError, ValueError) as exc:
        raise HTTPException(502, "Could not reach Zoho Recruit or parse its response.") from exc


def _access_token():
    accounts, api_base = _settings()
    body = urlencode({
        "refresh_token": os.environ["ZOHO_REFRESH_TOKEN"],
        "client_id": os.environ["ZOHO_CLIENT_ID"],
        "client_secret": os.environ["ZOHO_CLIENT_SECRET"],
        "grant_type": "refresh_token",
    }).encode()
    payload = _http_json(f"{accounts}/oauth/v2/token", body, {"Content-Type": "application/x-www-form-urlencoded"})
    token = payload.get("access_token")
    if not token:
        raise HTTPException(502, "Zoho token refresh failed. Check credentials and Zoho data centre.")
    api_domain = payload.get("api_domain")
    if api_domain and str(api_domain).startswith("https://") and "zoho" in str(api_domain).lower():
        api_base = str(api_domain).rstrip("/") + "/recruit/v2"
    return token, api_base


def _text(value) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("display_value") or "").strip()
    return str(value or "").strip()


def _records(token: str, api_base: str, module: str) -> list[dict]:
    records = []
    for page in range(1, 101):
        payload = _http_json(f"{api_base}/{module}?page={page}&per_page=200", headers={"Authorization": f"Zoho-oauthtoken {token}"})
        if payload.get("code") not in (None, "SUCCESS") and payload.get("status") != "success":
            raise HTTPException(502, f"Zoho returned an error while reading {module}.")
        batch = payload.get("data") or []
        if not isinstance(batch, list):
            raise HTTPException(502, f"Unexpected Zoho response for {module}.")
        records.extend(item for item in batch if isinstance(item, dict))
        if not (payload.get("info") or {}).get("more_records") or not batch:
            break
    return records


def _sync_module(db: Session, org: Organization, actor: User, token: str, api_base: str, module: str) -> int:
    synced = 0
    for item in _records(token, api_base, module):
        external_id = _text(item.get("id"))
        if not external_id:
            continue
        mapping = db.scalar(select(ZohoSyncRecord).where(
            ZohoSyncRecord.organization_id == org.id,
            ZohoSyncRecord.module == module,
            ZohoSyncRecord.zoho_id == external_id,
        ))
        if module == "Candidates":
            first, last = _text(item.get("First_Name")) or "Unknown", _text(item.get("Last_Name")) or "Candidate"
            email = _text(item.get("Email")).lower()
            if not email or "@" not in email:
                continue
            local = db.get(Candidate, mapping.local_id) if mapping else db.scalar(select(Candidate).where(Candidate.organization_id == org.id, Candidate.email == email))
            if local is not None and local.organization_id != org.id:
                continue
            if local is None:
                local = Candidate(organization_id=org.id, created_by_id=actor.id, first_name=first[:100], last_name=last[:100], email=email[:320])
                db.add(local)
            local.first_name, local.last_name, local.email = first[:100], last[:100], email[:320]
            local.phone = _text(item.get("Phone")) or _text(item.get("Mobile")) or None
            local.linkedin_url = _text(item.get("LinkedIn_Profile")) or _text(item.get("LinkedIn")) or None
            local.source = "Zoho Recruit"
        else:
            title = _text(item.get("Posting_Title")) or _text(item.get("Job_Opening_Name")) or _text(item.get("Name"))
            if not title:
                continue
            local = db.get(Job, mapping.local_id) if mapping else None
            if local is not None and local.organization_id != org.id:
                continue
            if local is None:
                local = Job(organization_id=org.id, created_by_id=actor.id, title=title[:200], description=_text(item.get("Job_Description")) or _text(item.get("Description")) or "Imported from Zoho Recruit.")
                db.add(local)
            local.title = title[:200]
            local.description = (_text(item.get("Job_Description")) or _text(item.get("Description")) or local.description or "Imported from Zoho Recruit.")[:50000]
            local.department = _text(item.get("Department")) or None
            local.location = _text(item.get("City")) or _text(item.get("Location")) or None
            status = (_text(item.get("Job_Opening_Status")) or "draft").lower()
            local.status = "open" if status in {"open", "in-progress", "in progress", "published"} else ("closed" if status in {"closed", "filled", "cancelled"} else "draft")
            local.employment_type = _text(item.get("Employment_Type")) or None
        db.flush()
        if mapping is None:
            db.add(ZohoSyncRecord(organization_id=org.id, module=module, zoho_id=external_id, local_id=local.id))
        else:
            mapping.local_id, mapping.synced_at = local.id, datetime.now(timezone.utc)
        db.commit()
        synced += 1
    return synced


def sync_zoho_for_organization(db: Session, org: Organization, actor: User) -> dict:
    token, api_base = _access_token()
    candidates = _sync_module(db, org, actor, token, api_base, "Candidates")
    jobs = _sync_module(db, org, actor, token, api_base, "JobOpenings")
    return {"candidates_synced": candidates, "jobs_synced": jobs, "completed_at": datetime.now(timezone.utc).isoformat()}


def _authorized_user(user=Depends(get_current_user)):
    if not user or not user.is_active or user.role not in (Role.admin, Role.recruiter):
        raise HTTPException(403, "Admin or recruiter access is required.")
    return user


@router.get("/status")
def zoho_status(db: Session = Depends(get_db), user: User = Depends(_authorized_user)):
    latest = db.scalar(
        select(ZohoSyncRun)
        .where(ZohoSyncRun.organization_id == user.organization_id)
        .order_by(ZohoSyncRun.started_at.desc(), ZohoSyncRun.id.desc())
        .limit(1)
    )
    return {
        "provider": "Zoho Recruit", "direction": "Zoho Recruit -> BluePace ATS",
        "automatic_sync_enabled": os.getenv("ZOHO_SYNC_ENABLED", "").strip().lower() == "true",
        "configured": all(os.getenv(k, "").strip() for k in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN")),
        "webhook_configured": bool(os.getenv("ZOHO_WEBHOOK_SECRET", "").strip()),
        "webhook_url": "/integrations/zoho/webhook",
        "reconciliation_interval_minutes": _sync_interval_minutes(),
        "last_sync": _sync_run_payload(latest),
        "credential_values_returned": False,
    }


@router.get("/history")
def zoho_sync_history(
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(_authorized_user),
):
    """List recent sync outcomes for the signed-in user's organization only."""
    runs = db.scalars(
        select(ZohoSyncRun)
        .where(ZohoSyncRun.organization_id == user.organization_id)
        .order_by(ZohoSyncRun.started_at.desc(), ZohoSyncRun.id.desc())
        .limit(limit)
    ).all()
    return {"runs": [_sync_run_payload(run) for run in runs], "count": len(runs)}


def _run_background_sync(organization_id: int) -> None:
    """Run an authenticated full reconciliation after a validated Zoho event."""
    with SessionLocal() as db:
        org = db.get(Organization, organization_id)
        if org is None:
            return
        actor = db.scalar(select(User).where(
            User.organization_id == org.id,
            User.is_active.is_(True),
            User.role == Role.admin,
        ).order_by(User.id.asc()))
        if actor is None:
            return
        try:
            result = _execute_sync(db, org, actor, "webhook")
            print(
                f"[zoho-webhook-sync] organization_id={org.id} "
                f"run_id={result['run_id']} status={result['status']} "
                f"candidates={result['candidates_synced']} jobs={result['jobs_synced']}",
                flush=True,
            )
        except Exception as exc:
            db.rollback()
            print(f"[zoho-webhook-sync] failed={type(exc).__name__}", flush=True)


@router.post("/webhook", status_code=202)
async def zoho_webhook(request: Request, background_tasks: BackgroundTasks):
    """Accept Zoho workflow notifications; never trust webhook fields as record data.

    Configure Zoho to send `webhook_token` as a custom parameter. The event triggers
    a server-to-server reconciliation, which fetches canonical records via OAuth.
    """
    secret = os.getenv("ZOHO_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise HTTPException(503, "Zoho webhook receiver is not configured.")
    raw_body = await request.body()
    payload = {}
    if raw_body:
        try:
            import json
            payload = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            try:
                form_values = parse_qs(raw_body.decode("utf-8"), keep_blank_values=True)
                payload = {key: values[-1] for key, values in form_values.items() if values}
            except UnicodeDecodeError as exc:
                raise HTTPException(400, "Webhook body must be JSON or URL-encoded parameters.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "Webhook body must contain a JSON object or URL-encoded parameters.")
    supplied = str(payload.get("webhook_token") or request.query_params.get("webhook_token") or request.headers.get("x-zoho-webhook-token") or "")
    if not supplied or not hmac.compare_digest(supplied, secret):
        raise HTTPException(401, "Invalid webhook authentication.")
    if os.getenv("ZOHO_SYNC_ENABLED", "").strip().lower() != "true":
        raise HTTPException(503, "Zoho automatic sync is disabled.")
    try:
        organization_id = int(os.getenv("ZOHO_ORGANIZATION_ID", ""))
    except ValueError as exc:
        raise HTTPException(503, "Zoho webhook organization is not configured.") from exc
    # Do not log or persist potentially sensitive payload fields. The event is
    # only a wake-up signal; canonical records are re-read through the OAuth API.
    background_tasks.add_task(_run_background_sync, organization_id)
    return {"accepted": True, "mode": "reconcile", "message": "Zoho event accepted; canonical records will be reconciled."}


@router.post("/sync")
def trigger_sync(db: Session = Depends(get_db), user: User = Depends(_authorized_user)):
    org = db.get(Organization, user.organization_id)
    if org is None:
        raise HTTPException(400, "User organization was not found.")
    return _execute_sync(db, org, user, "manual")


async def automatic_sync_loop():
    while True:
        interval = _sync_interval_minutes() * 60
        try:
            if os.getenv("ZOHO_SYNC_ENABLED", "").strip().lower() == "true":
                if all(os.getenv(k, "").strip() for k in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN", "ZOHO_ORGANIZATION_ID")):
                    with SessionLocal() as db:
                        try:
                            org = db.get(Organization, int(os.environ["ZOHO_ORGANIZATION_ID"]))
                            if org is not None:
                                actor = db.scalar(select(User).where(User.organization_id == org.id, User.is_active.is_(True), User.role == Role.admin).order_by(User.id.asc()))
                                if actor is not None:
                                    result = _execute_sync(db, org, actor, "scheduled")
                                    print(f"[zoho-sync] organization_id={org.id} run_id={result['run_id']} candidates={result['candidates_synced']} jobs={result['jobs_synced']}", flush=True)
                        except Exception as exc:
                            db.rollback()
                            print(f"[zoho-sync] scheduled sync failed={type(exc).__name__}", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[zoho-sync] loop failed={type(exc).__name__}", flush=True)
        await asyncio.sleep(interval)


_task = None

@router.on_event("startup")
async def _start_zoho_sync():
    global _task
    _task = asyncio.create_task(automatic_sync_loop())

@router.on_event("shutdown")
async def _stop_zoho_sync():
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
