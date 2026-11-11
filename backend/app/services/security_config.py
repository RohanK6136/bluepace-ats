"""JWT secret resolution rules shared by app startup and tests."""

from __future__ import annotations

DEVELOPMENT_JWT_SECRET = "local-development-only-change-me"
NON_PRODUCTION_ENVIRONMENTS = frozenset({"development", "dev", "test"})


def requires_explicit_secret(app_env: str, railway_environment_name: str = "") -> bool:
    """Treat a named non-development Railway environment as production-like."""
    normalized_app_env = (app_env or "development").strip().lower()
    normalized_railway_env = (railway_environment_name or "").strip().lower()
    if normalized_railway_env:
        return normalized_railway_env not in NON_PRODUCTION_ENVIRONMENTS
    return normalized_app_env not in NON_PRODUCTION_ENVIRONMENTS


def resolve_jwt_secret(
    configured_secret: str | None,
    app_env: str,
    railway_environment_name: str = "",
) -> tuple[str, bool]:
    """Return (secret, fallback_used), rejecting missing secrets outside dev/test."""
    secret = (configured_secret or "").strip()
    if not secret and requires_explicit_secret(app_env, railway_environment_name):
        raise RuntimeError(
            "JWT_SECRET must be configured outside development and test environments"
        )
    if secret:
        return secret, False
    return DEVELOPMENT_JWT_SECRET, True


def resolve_candidate_portal_secret(
    configured_secret: str | None,
    recruiter_secret: str,
    app_env: str,
    railway_environment_name: str = "",
) -> tuple[str, bool]:
    """Use a distinct candidate-link signing key in production."""
    secret = (configured_secret or "").strip()
    if not secret and requires_explicit_secret(app_env, railway_environment_name):
        raise RuntimeError(
            "CANDIDATE_PORTAL_JWT_SECRET must be configured outside development and test environments"
        )
    if secret:
        return secret, False
    return recruiter_secret or DEVELOPMENT_JWT_SECRET, True
