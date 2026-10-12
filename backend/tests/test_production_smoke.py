import importlib.util
import json
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SMOKE_SCRIPT = REPOSITORY_ROOT / ".github" / "scripts" / "production_smoke.py"
SPEC = importlib.util.spec_from_file_location("production_smoke", SMOKE_SCRIPT)
assert SPEC is not None and SPEC.loader is not None
production_smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(production_smoke)


def test_assert_json_response_accepts_expected_payload(monkeypatch):
    headers = {"content-type": "application/json"}
    monkeypatch.setattr(
        production_smoke,
        "request",
        lambda url: (200, headers, b'{"status":"ok","service":"bluepace-ats"}'),
    )

    assert production_smoke.assert_json_response(
        "https://example.test/healthz",
        {"status": "ok", "service": "bluepace-ats"},
    ) is headers


@pytest.mark.parametrize(
    ("status", "body", "message"),
    [
        (503, b"temporarily unavailable", "HTTP 503"),
        (200, b"not-json", "valid JSON"),
        (200, b'{"status":"ok"}', "service"),
    ],
)
def test_assert_json_response_rejects_bad_responses(monkeypatch, status, body, message):
    monkeypatch.setattr(
        production_smoke,
        "request",
        lambda url: (status, {}, body),
    )

    with pytest.raises(RuntimeError, match=message):
        production_smoke.assert_json_response(
            "https://example.test/healthz",
            {"status": "ok", "service": "bluepace-ats"},
        )


def test_health_check_requires_all_security_headers(monkeypatch):
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    }
    monkeypatch.setattr(
        production_smoke,
        "assert_json_response",
        lambda url, expected: headers,
    )

    production_smoke.check_health_and_security()


def test_health_check_rejects_missing_hsts(monkeypatch):
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    }
    monkeypatch.setattr(
        production_smoke,
        "assert_json_response",
        lambda url, expected: headers,
    )

    with pytest.raises(RuntimeError, match="Strict-Transport-Security"):
        production_smoke.check_health_and_security()


def test_cors_check_sends_expected_origin_and_method(monkeypatch):
    calls = []
    monkeypatch.setattr(
        production_smoke,
        "request",
        lambda url, method="GET", headers=None: (
            calls.append((url, method, headers)) or
            (204, {"Access-Control-Allow-Origin": production_smoke.FRONTEND_URL}, b"")
        ),
    )

    production_smoke.check_cors()

    url, method, headers = calls[0]
    assert url.endswith("/public/jobs")
    assert method == "OPTIONS"
    assert headers["Origin"] == production_smoke.FRONTEND_URL
    assert headers["Access-Control-Request-Method"] == "GET"


def test_cors_check_rejects_wrong_allowed_origin(monkeypatch):
    monkeypatch.setattr(
        production_smoke,
        "request",
        lambda url, method="GET", headers=None: (
            200, {"Access-Control-Allow-Origin": "https://unexpected.example"}, b""
        ),
    )

    with pytest.raises(RuntimeError, match="CORS preflight allowed origin"):
        production_smoke.check_cors()


def test_frontend_check_rejects_server_errors(monkeypatch):
    monkeypatch.setattr(
        production_smoke,
        "request",
        lambda url: (503, {}, b"unavailable"),
    )

    with pytest.raises(RuntimeError, match="HTTP 503"):
        production_smoke.check_frontend()
