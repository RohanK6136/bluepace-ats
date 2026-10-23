"""Fail-closed validation for BluePace ATS production environment variables.

Run from the backend directory with APP_ENV=production (or staging):
    python -m app.services.production_config

The checker never prints the values of secrets or connection strings.
"""
from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from urllib.parse import urlsplit


PRODUCTION_ENVIRONMENTS = frozenset({"production", "staging"})
DEVELOPMENT_JWT_SECRET = "local-development-only-change-me"
B2_VARIABLES = (
    "B2_ENDPOINT",
    "B2_ACCESS_KEY_ID",
    "B2_SECRET_ACCESS_KEY",
    "B2_BUCKET",
    "B2_REGION",
)


def validate_production_config(
    env: Mapping[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for production/staging env without revealing values."""
    values = os.environ if env is None else env
    errors: list[str] = []
    warnings: list[str] = []

    app_env = values.get("APP_ENV", "").strip().lower()
    if app_env not in PRODUCTION_ENVIRONMENTS:
        errors.append("APP_ENV must be explicitly set to 'production' or 'staging'.")

    database_url = values.get("DATABASE_URL", "").strip()
    if not database_url:
        errors.append("DATABASE_URL is missing.")
    else:
        scheme = urlsplit(database_url).scheme.lower()
        if scheme.startswith("postgresql"):
            pass
        elif scheme.startswith("sqlite"):
            persistent_sqlite = values.get("ALLOW_PERSISTENT_SQLITE", "").strip().lower() == "true"
            if persistent_sqlite:
                warnings.append(
                    "Persistent SQLite is enabled. Confirm a mounted durable volume and a single app replica; PostgreSQL is recommended."
                )
            else:
                errors.append(
                    "DATABASE_URL uses SQLite; configure PostgreSQL or explicitly set ALLOW_PERSISTENT_SQLITE=true for a single-instance durable-volume deployment."
                )
        else:
            errors.append("DATABASE_URL must use a PostgreSQL URL (or explicitly permitted SQLite).")

    jwt_secret = values.get("JWT_SECRET", "").strip()
    if not jwt_secret:
        errors.append("JWT_SECRET is missing.")
    elif jwt_secret == DEVELOPMENT_JWT_SECRET:
        errors.append("JWT_SECRET is set to the known local development fallback.")
    elif len(jwt_secret) < 32:
        errors.append("JWT_SECRET must contain at least 32 characters; generate a strong random secret.")

    origins_raw = values.get("ALLOWED_ORIGINS", "").strip()
    if not origins_raw:
        errors.append("ALLOWED_ORIGINS is missing; set the exact frontend origin(s), comma-separated.")
    else:
        origins = [origin.strip() for origin in origins_raw.split(",") if origin.strip()]
        if not origins:
            errors.append("ALLOWED_ORIGINS must contain at least one valid origin.")
        for origin in origins:
            if origin == "*" or "*" in origin:
                errors.append("ALLOWED_ORIGINS must not contain a wildcard.")
                continue
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"https", "http"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                errors.append("ALLOWED_ORIGINS entries must be bare HTTP(S) origins without paths or credentials.")
                continue
            if app_env == "production" and parsed.scheme != "https":
                errors.append("Production ALLOWED_ORIGINS entries must use HTTPS.")

    configured_b2 = [name for name in B2_VARIABLES if values.get(name, "").strip()]
    if configured_b2 and len(configured_b2) != len(B2_VARIABLES):
        missing = [name for name in B2_VARIABLES if not values.get(name, "").strip()]
        errors.append("Backblaze B2 configuration is incomplete; missing: " + ", ".join(missing) + ".")
    elif not configured_b2:
        warnings.append(
            "Backblaze B2 is not configured. Confirm local resume storage is durable for the deployed runtime before accepting production uploads."
        )

    return errors, warnings


def main() -> int:
    errors, warnings = validate_production_config()
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        print(f"Production configuration check failed ({len(errors)} error(s), {len(warnings)} warning(s)).")
        return 1
    print(f"Production configuration check passed ({len(warnings)} warning(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
