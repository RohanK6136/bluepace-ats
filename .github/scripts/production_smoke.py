#!/usr/bin/env python3
"""Zero-dependency smoke checks for the deployed BluePace ATS public endpoints."""

from __future__ import annotations

import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_BASE_URL = os.getenv(
    "API_BASE_URL", "https://bluepace-ats-production.up.railway.app"
).rstrip("/")
FRONTEND_URL = os.getenv(
    "FRONTEND_URL", "https://bluepace-frontend-production.up.railway.app"
).rstrip("/")
TIMEOUT_SECONDS = 15
ATTEMPTS = 3
TRANSIENT_HTTP_STATUSES = {429, 500, 502, 503, 504}


def request(url: str, method: str = "GET", headers: dict[str, str] | None = None):
    """Return status, headers and a small body; retry transient failures."""
    last_error: Exception | None = None
    for attempt in range(ATTEMPTS):
        req = Request(url, method=method, headers=headers or {})
        try:
            with urlopen(req, timeout=TIMEOUT_SECONDS) as response:
                return response.status, response.headers, response.read(8192)
        except HTTPError as error:
            if error.code not in TRANSIENT_HTTP_STATUSES or attempt == ATTEMPTS - 1:
                return error.code, error.headers, error.read(8192)
            last_error = error
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt == ATTEMPTS - 1:
                break
        time.sleep(2 ** attempt)
    raise RuntimeError(f"request failed after {ATTEMPTS} attempts: {url}: {last_error}")


def assert_json_response(url: str, expected: dict[str, str]):
    status, headers, body = request(url)
    if status != 200:
        raise RuntimeError(f"GET {url} returned HTTP {status}: {body[:300].decode('utf-8', 'replace')}")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"GET {url} did not return valid JSON: {error}") from error
    for key, value in expected.items():
        if payload.get(key) != value:
            raise RuntimeError(f"GET {url}: expected JSON field {key}={value!r}, got {payload.get(key)!r}")
    print(f"PASS GET {url} (HTTP 200, JSON response)")
    return headers


def check_health_and_security():
    headers = assert_json_response(
        f"{API_BASE_URL}/healthz",
        {"status": "ok", "service": "bluepace-ats"},
    )
    required = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    }
    missing = [name for name, value in required.items() if headers.get(name) != value]
    hsts = headers.get("Strict-Transport-Security", "")
    if not hsts.lower().startswith("max-age=31536000") or "includesubdomains" not in hsts.lower():
        missing.append("Strict-Transport-Security")
    if missing:
        raise RuntimeError("missing or incorrect security headers: " + ", ".join(missing))
    print("PASS production security headers (including HSTS)")


def check_readiness():
    assert_json_response(f"{API_BASE_URL}/readyz", {"status": "ready"})


def check_cors():
    status, headers, body = request(
        f"{API_BASE_URL}/public/jobs",
        method="OPTIONS",
        headers={
            "Origin": FRONTEND_URL,
            "Access-Control-Request-Method": "GET",
        },
    )
    if status not in {200, 204}:
        raise RuntimeError(f"CORS preflight returned HTTP {status}: {body[:300].decode('utf-8', 'replace')}")
    allow_origin = headers.get("Access-Control-Allow-Origin")
    if allow_origin != FRONTEND_URL:
        raise RuntimeError(f"CORS preflight allowed origin {allow_origin!r}, expected {FRONTEND_URL!r}")
    print(f"PASS CORS preflight for {FRONTEND_URL}")


def check_frontend():
    status, _headers, body = request(FRONTEND_URL)
    if status < 200 or status >= 400:
        raise RuntimeError(
            f"GET {FRONTEND_URL} returned HTTP {status}: {body[:300].decode('utf-8', 'replace')}"
        )
    print(f"PASS frontend reachable (HTTP {status})")


def main() -> int:
    checks = (
        ("API liveness and security headers", check_health_and_security),
        ("API readiness", check_readiness),
        ("Frontend-to-API CORS", check_cors),
        ("Frontend reachability", check_frontend),
    )
    failures = []
    for name, check in checks:
        try:
            check()
        except Exception as error:  # report independent failures rather than hiding later checks
            failures.append(f"{name}: {error}")
            print(f"FAIL {name}: {error}", file=sys.stderr)
    if failures:
        print(f"\nProduction smoke checks failed: {len(failures)}/{len(checks)}", file=sys.stderr)
        return 1
    print(f"\nAll {len(checks)} production smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
