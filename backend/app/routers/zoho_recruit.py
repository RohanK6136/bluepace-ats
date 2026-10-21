"""Secure, read-only Zoho Recruit import for BluePace ATS."""
import asyncio
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import DateTime, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

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
def zoho_status(user: User = Depends(_authorized_user)):
    return {
        "provider": "Zoho Recruit", "direction": "Zoho Recruit -> BluePace ATS",
        "automatic_sync_enabled": os.getenv("ZOHO_SYNC_ENABLED", "").strip().lower() == "true",
        "configured": all(os.getenv(k, "").strip() for k in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN")),
        "interval_minutes": max(5, int(os.getenv("ZOHO_SYNC_INTERVAL_MINUTES", "15"))),
        "credential_values_returned": False,
    }


@router.post("/sync")
def trigger_sync(db: Session = Depends(get_db), user: User = Depends(_authorized_user)):
    org = db.get(Organization, user.organization_id)
    if org is None:
        raise HTTPException(400, "User organization was not found.")
    return sync_zoho_for_organization(db, org, user)


async def automatic_sync_loop():
    while True:
        interval = max(5, int(os.getenv("ZOHO_SYNC_INTERVAL_MINUTES", "15"))) * 60
        try:
            if os.getenv("ZOHO_SYNC_ENABLED", "").strip().lower() == "true":
                if all(os.getenv(k, "").strip() for k in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN")):
                    with SessionLocal() as db:
                        for org in db.scalars(select(Organization)).all():
                            actor = db.scalar(select(User).where(User.organization_id == org.id, User.is_active.is_(True), User.role == Role.admin).order_by(User.id.asc()))
                            if actor is None:
                                continue
                            try:
                                result = sync_zoho_for_organization(db, org, actor)
                                print(f"[zoho-sync] organization_id={org.id} candidates={result['candidates_synced']} jobs={result['jobs_synced']}", flush=True)
                            except Exception as exc:
                                db.rollback()
                                print(f"[zoho-sync] organization_id={org.id} failed={type(exc).__name__}", flush=True)
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
