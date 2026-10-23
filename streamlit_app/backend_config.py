"""Validate explicit backend URLs for the Streamlit companion.

This module deliberately has no Streamlit dependency so URL policy can be tested
without booting the UI.
"""
from collections.abc import Mapping
import os
from urllib.parse import urlsplit

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def normalize_api_url(value: str | None) -> str:
    """Return a safe API base URL, or an empty string when invalid/retired."""
    candidate = (value or "").strip().rstrip("/")
    if not candidate:
        return ""

    try:
        parsed = urlsplit(candidate)
        # Accessing .port validates malformed ports as well.
        _ = parsed.port
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return ""

    if (
        not host
        or parsed.scheme not in {"https", "http"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return ""

    # The public API must use HTTPS. HTTP is permitted only for local development.
    if parsed.scheme == "http" and host not in _LOOPBACK_HOSTS:
        return ""

    # Do not send credentials or requests to the retired backend host, even if
    # an operator accidentally pastes it into the editable text field.
    if host == "railway.app" or host.endswith(".railway.app") or host.endswith(".railway.internal"):
        return ""

    return candidate


def default_api_url_from_environment(environ: Mapping[str, str] | None = None) -> str:
    """Read ATS_API_URL and apply the same validation used by the UI input."""
    source = environ if environ is not None else os.environ
    return normalize_api_url(source.get("ATS_API_URL", ""))
