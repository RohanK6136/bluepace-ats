from fastapi import HTTPException, Response
from starlette.requests import Request

from app.routers.cookie_auth import _require_csrf, _set_session_cookies


def _request(cookie: str = "", csrf_header: str = "") -> Request:
    headers = []
    if cookie:
        headers.append((b"cookie", cookie.encode("latin-1")))
    if csrf_header:
        headers.append((b"x-csrf-token", csrf_header.encode("latin-1")))
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/auth/session/logout",
            "raw_path": b"/auth/session/logout",
            "query_string": b"",
            "headers": headers,
            "server": ("testserver", 443),
            "client": ("127.0.0.1", 12345),
        }
    )


def test_csrf_accepts_matching_double_submit_token():
    _require_csrf(_request("bluepace_csrf=one-time-value", "one-time-value"))


def test_csrf_rejects_missing_or_mismatched_token():
    for request in (
        _request("bluepace_csrf=expected", ""),
        _request("bluepace_csrf=expected", "attacker-controlled"),
        _request("", "provided-without-cookie"),
    ):
        try:
            _require_csrf(request)
        except HTTPException as error:
            assert error.status_code == 403
        else:
            raise AssertionError("CSRF validation should reject missing/mismatched tokens")


def test_session_cookie_is_http_only_and_response_is_not_cacheable():
    response = Response()
    _set_session_cookies(response, "signed-access-token")
    cookies = response.headers.getlist("set-cookie")
    access_cookie = next(cookie for cookie in cookies if cookie.startswith("bluepace_access="))
    csrf_cookie = next(cookie for cookie in cookies if cookie.startswith("bluepace_csrf="))
    assert "httponly" in access_cookie.lower()
    assert "httponly" not in csrf_cookie.lower()
    assert response.headers["cache-control"] == "no-store"
    assert "signed-access-token" not in response.body.decode("utf-8", errors="ignore")
