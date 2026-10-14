"""JWT secret resolution rules shared by app startup and tests."""

from __future__ import annotations

DEVELOPMENT_JWT_SECRET = "local-development-only-change-me"
NON_PRODUCTION_ENVIRONMENTS = frozenset({"development", "test"})


def resolve_jwt_secret(
    configured_secret: str | None,
    app_env: str,
) -> tuple[str, bool]:
    """Return (secret, fallback_used); production-like environments must be configured."""
    normalized_env = (app_env or "development").strip().lower()
    if not configured_secret and normalized_env not in NON_PRODUCTION_ENVIRONMENTS:
        raise RuntimeError(
            "JWT_SECRET must be configured outside development and test environments"
        )
    if configured_secret:
        return configured_secret, False
    return DEVELOPMENT_JWT_SECRET, True
