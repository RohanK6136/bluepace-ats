"""Request context middleware (pure ASGI, safe for streaming responses).

- accepts or creates an X-Request-ID and returns it on every response
- binds request id + client IP to contextvars so logs and run rows carry them
- one structured access-log line and HTTP metrics per request, labelled by route template (not raw path)
- baseline security headers
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from app.core import metrics
from app.core.ids import new_request_id
from app.core.logging import client_ip, http_request_id, log_event

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_QUIET = {"/healthz", "/readyz", "/metrics"}
_SECURITY_HEADERS = [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"same-origin"),
                     (b"x-frame-options", b"DENY")]


class RequestContextMiddleware:
    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if _SAFE_ID.match(incoming) else new_request_id().replace("req_", "http_")
        scope.setdefault("state", {})["request_id"] = rid  # read by the 500 handler, which runs outside us
        tok_rid = http_request_id.set(rid)
        tok_ip = client_ip.set((scope.get("client") or ("", 0))[0] or None)
        status = 500
        t0 = time.perf_counter()

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [*message.get("headers", []), (b"x-request-id", rid.encode()),
                                      *_SECURITY_HEADERS]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = getattr(scope.get("route"), "path", None) or ("/static" if scope["path"].startswith("/static")
                                                                   else "unmatched")
            elapsed = time.perf_counter() - t0
            method = scope.get("method", "")
            metrics.HTTP_REQUESTS.labels(method, route, str(status)).inc()
            metrics.HTTP_LATENCY.labels(method, route).observe(elapsed)
            log_event("http_request", level=logging.DEBUG if scope["path"] in _QUIET else logging.INFO,
                      method=method, path=scope["path"], route=route, status=status,
                      duration_ms=int(elapsed * 1000))
            http_request_id.reset(tok_rid)
            client_ip.reset(tok_ip)
