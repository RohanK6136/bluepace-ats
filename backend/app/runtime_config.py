"""Shared runtime-environment detection for startup/security guards."""

import os


_DEVELOPMENT_ENVIRONMENTS = {"development", "test"}


def is_production_runtime() -> bool:
    """Treat the hosting platform's production environment as production.

    APP_ENV may be omitted by the host, so RAILWAY_ENVIRONMENT=production
    must override the development default in that case.
    """
    app_environment = os.getenv("APP_ENV", "development").strip().lower()
    railway_environment = os.getenv("RAILWAY_ENVIRONMENT", "").strip().lower()
    return (
        app_environment not in _DEVELOPMENT_ENVIRONMENTS
        or railway_environment == "production"
    )
