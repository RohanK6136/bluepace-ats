import pytest

from app.services.security_config import DEVELOPMENT_JWT_SECRET, resolve_jwt_secret


@pytest.mark.parametrize("app_env", ["development", "test", "DEVELOPMENT", "Test"])
def test_development_and_test_environments_can_use_local_fallback(app_env):
    secret, fallback_used = resolve_jwt_secret(None, app_env)

    assert secret == DEVELOPMENT_JWT_SECRET
    assert fallback_used is True


@pytest.mark.parametrize("app_env", ["production", "staging", "PRODUCTION"])
def test_non_development_environments_require_explicit_jwt_secret(app_env):
    with pytest.raises(RuntimeError, match="JWT_SECRET must be configured"):
        resolve_jwt_secret(None, app_env)


def test_explicit_secret_is_preserved_and_not_marked_as_fallback():
    secret, fallback_used = resolve_jwt_secret("a-configured-secret-value", "production")

    assert secret == "a-configured-secret-value"
    assert fallback_used is False


def test_empty_secret_is_treated_as_missing_in_production():
    with pytest.raises(RuntimeError, match="JWT_SECRET must be configured"):
        resolve_jwt_secret("", "production")
