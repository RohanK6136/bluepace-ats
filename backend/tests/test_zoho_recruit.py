import pytest
from fastapi import HTTPException

from app.routers import zoho_recruit


def test_zoho_text_normalizes_lookup_fields():
    assert zoho_recruit._text({"name": "Engineering"}) == "Engineering"
    assert zoho_recruit._text({"display_value": "Remote"}) == "Remote"
    assert zoho_recruit._text(None) == ""
    assert zoho_recruit._text("  recruiter  ") == "recruiter"


def test_zoho_configuration_fails_closed_without_credentials(monkeypatch):
    for key in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(HTTPException) as error:
        zoho_recruit._settings()
    assert error.value.status_code == 503


def test_zoho_configuration_rejects_unknown_accounts_domain(monkeypatch):
    monkeypatch.setenv("ZOHO_CLIENT_ID", "client")
    monkeypatch.setenv("ZOHO_CLIENT_SECRET", "secret")
    monkeypatch.setenv("ZOHO_REFRESH_TOKEN", "refresh")
    monkeypatch.setenv("ZOHO_ACCOUNTS_DOMAIN", "unknown")
    with pytest.raises(HTTPException) as error:
        zoho_recruit._settings()
    assert error.value.status_code == 500


def test_zoho_configuration_rejects_non_https_api_host(monkeypatch):
    monkeypatch.setenv("ZOHO_CLIENT_ID", "client")
    monkeypatch.setenv("ZOHO_CLIENT_SECRET", "secret")
    monkeypatch.setenv("ZOHO_REFRESH_TOKEN", "refresh")
    monkeypatch.setenv("ZOHO_ACCOUNTS_DOMAIN", "in")
    monkeypatch.setenv("ZOHO_RECRUIT_API_BASE", "http://recruit.zoho.in/recruit/v2")
    with pytest.raises(HTTPException) as error:
        zoho_recruit._settings()
    assert error.value.status_code == 500


def test_sync_record_mapping_is_unique_per_org_module_and_zoho_id():
    constraints = [
        constraint for constraint in zoho_recruit.ZohoSyncRecord.__table__.constraints
        if getattr(constraint, "name", None) == "uq_zoho_sync_external"
    ]
    assert len(constraints) == 1


class FakeWebhookRequest:
    def __init__(self, payload=None, query=None, headers=None):
        self.payload = payload if payload is not None else {}
        self.query_params = query or {}
        self.headers = headers or {}

    async def body(self):
        import json
        return json.dumps(self.payload).encode("utf-8")


def test_webhook_rejects_when_secret_not_configured(monkeypatch):
    import asyncio
    from starlette.background import BackgroundTasks
    monkeypatch.delenv("ZOHO_WEBHOOK_SECRET", raising=False)
    with pytest.raises(HTTPException) as error:
        asyncio.run(zoho_recruit.zoho_webhook(FakeWebhookRequest(), BackgroundTasks()))
    assert error.value.status_code == 503


def test_webhook_rejects_invalid_token(monkeypatch):
    import asyncio
    from starlette.background import BackgroundTasks
    monkeypatch.setenv("ZOHO_WEBHOOK_SECRET", "expected-secret")
    with pytest.raises(HTTPException) as error:
        asyncio.run(zoho_recruit.zoho_webhook(FakeWebhookRequest({"webhook_token": "wrong"}), BackgroundTasks()))
    assert error.value.status_code == 401


def test_webhook_queues_reconciliation_only_after_valid_token(monkeypatch):
    import asyncio
    from starlette.background import BackgroundTasks
    monkeypatch.setenv("ZOHO_WEBHOOK_SECRET", "expected-secret")
    monkeypatch.setenv("ZOHO_SYNC_ENABLED", "true")
    monkeypatch.setenv("ZOHO_ORGANIZATION_ID", "42")
    background = BackgroundTasks()
    response = asyncio.run(zoho_recruit.zoho_webhook(
        FakeWebhookRequest({"webhook_token": "expected-secret", "candidate_email": "untrusted@example.com"}),
        background,
    ))
    assert response["accepted"] is True
    assert response["mode"] == "reconcile"
    assert len(background.tasks) == 1
    assert background.tasks[0].args == (42,)


def test_webhook_rejects_when_automatic_sync_disabled(monkeypatch):
    import asyncio
    from starlette.background import BackgroundTasks
    monkeypatch.setenv("ZOHO_WEBHOOK_SECRET", "expected-secret")
    monkeypatch.setenv("ZOHO_SYNC_ENABLED", "false")
    monkeypatch.setenv("ZOHO_ORGANIZATION_ID", "42")
    with pytest.raises(HTTPException) as error:
        asyncio.run(zoho_recruit.zoho_webhook(FakeWebhookRequest({"webhook_token": "expected-secret"}), BackgroundTasks()))
    assert error.value.status_code == 503


def test_sync_interval_is_bounded_and_handles_invalid_environment(monkeypatch):
    monkeypatch.setenv("ZOHO_SYNC_INTERVAL_MINUTES", "not-a-number")
    assert zoho_recruit._sync_interval_minutes() == 15
    monkeypatch.setenv("ZOHO_SYNC_INTERVAL_MINUTES", "2")
    assert zoho_recruit._sync_interval_minutes() == 5
    monkeypatch.setenv("ZOHO_SYNC_INTERVAL_MINUTES", "5000")
    assert zoho_recruit._sync_interval_minutes() == 1440


def test_sync_run_history_table_is_payload_free():
    columns = set(zoho_recruit.ZohoSyncRun.__table__.columns.keys())
    assert {
        "id", "organization_id", "trigger", "status", "started_at",
        "completed_at", "candidates_synced", "jobs_synced", "error_type",
    }.issubset(columns)
    assert not {"payload", "candidate_email", "access_token", "refresh_token"}.intersection(columns)


class FakeSyncRunSession:
    def __init__(self):
        self.rows = {}
        self.next_id = 1

    def add(self, row):
        if isinstance(row, zoho_recruit.ZohoSyncRun):
            row.id = self.next_id
            self.rows[row.id] = row
            self.next_id += 1

    def commit(self):
        pass

    def refresh(self, row):
        pass

    def get(self, model, row_id):
        if model is zoho_recruit.ZohoSyncRun:
            return self.rows.get(row_id)
        return None

    def rollback(self):
        pass


def test_execute_sync_persists_successful_run(monkeypatch):
    db = FakeSyncRunSession()
    org = type("Org", (), {"id": 42})()
    actor = object()
    monkeypatch.setattr(
        zoho_recruit,
        "sync_zoho_for_organization",
        lambda *_: {"candidates_synced": 3, "jobs_synced": 2, "completed_at": "now"},
    )
    result = zoho_recruit._execute_sync(db, org, actor, "manual")
    run = db.rows[result["run_id"]]
    assert result["status"] == "success"
    assert result["trigger"] == "manual"
    assert run.status == "success"
    assert run.candidates_synced == 3
    assert run.jobs_synced == 2
    assert run.completed_at is not None
    assert run.error_type is None


def test_execute_sync_persists_sanitized_failure(monkeypatch):
    db = FakeSyncRunSession()
    org = type("Org", (), {"id": 42})()
    monkeypatch.setattr(
        zoho_recruit,
        "sync_zoho_for_organization",
        lambda *_: (_ for _ in ()).throw(RuntimeError("contains private candidate data")),
    )
    with pytest.raises(RuntimeError):
        zoho_recruit._execute_sync(db, org, object(), "webhook")
    run = db.rows[1]
    assert run.status == "failed"
    assert run.error_type == "RuntimeError"
    assert run.completed_at is not None
    assert not hasattr(run, "error_message")


def test_http_json_uses_urllib_request_not_fastapi_request(monkeypatch):
    from urllib.request import Request as UrllibRequest

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b'{"access_token":"test-token"}'

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(zoho_recruit, "urlopen", fake_urlopen)
    result = zoho_recruit._http_json(
        "https://accounts.zoho.in/oauth/v2/token",
        data=b"grant_type=refresh_token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    request = captured["request"]
    assert isinstance(request, UrllibRequest)
    assert isinstance(zoho_recruit.Request, type)  # FastAPI Request remains reserved for webhook handling.
    assert request.full_url == "https://accounts.zoho.in/oauth/v2/token"
    assert request.get_method() == "POST"
    assert request.data == b"grant_type=refresh_token"
    assert captured["timeout"] == 25
    assert result == {"access_token": "test-token"}
