import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.runtime_config import is_production_runtime


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _run_import(module: str, overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("APP_ENV", None)
    env.pop("DATABASE_URL", None)
    env.pop("JWT_SECRET", None)
    env.update(
        {
            "RAILWAY_ENVIRONMENT": "production",
            "PYTHON_DOTENV_DISABLED": "true",
            "PYTHONPATH": str(BACKEND_DIR),
        }
    )
    env.update(overrides)
    return subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )


def test_railway_production_is_detected_without_app_env(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")

    assert is_production_runtime() is True


def test_test_environment_remains_non_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)

    assert is_production_runtime() is False


def test_database_fails_closed_on_sqlite_in_railway_production():
    result = _run_import(
        "app.database",
        {"DATABASE_URL": "sqlite:///./should-not-start.db"},
    )

    assert result.returncode != 0
    assert "DATABASE_URL must point to PostgreSQL" in result.stderr


@pytest.mark.parametrize(
    "jwt_secret",
    ["", "local-development-only-change-me", "too-short"],
)
def test_security_fails_closed_on_missing_or_weak_railway_production_jwt(jwt_secret):
    result = _run_import(
        "app.security",
        {
            "DATABASE_URL": "postgresql+psycopg://test:test@127.0.0.1:5432/test",
            "JWT_SECRET": jwt_secret,
        },
    )

    assert result.returncode != 0
    assert "JWT_SECRET must be a non-default secret of at least 32 bytes in production" in result.stderr
