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
