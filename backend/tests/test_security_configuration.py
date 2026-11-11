import pytest

from app.services.security_config import (
    DEVELOPMENT_JWT_SECRET,
    resolve_candidate_portal_secret,
    resolve_jwt_secret,
)


@pytest.mark.parametrize("app_env", ["development", "test", "DEVELOPMENT", "Test"])
def test_development_and_test_environments_can_use_local_fallback(app_env):
    secret, fallback_used = resolve_jwt_secret(None, app_env)

    assert secret == DEVELOPMENT_JWT_SECRET
    assert fallback_used is True


@pytest.mark.parametrize("app_env", ["production", "staging", "PRODUCTION"])
def test_non_development_environments_require_explicit_jwt_secret(app_env):
    with pytest.raises(RuntimeError, match="JWT_SECRET must be configured"):
        resolve_jwt_secret(None, app_env)


def test_railway_production_requires_explicit_secret_even_if_app_env_is_development():
    with pytest.raises(RuntimeError, match="JWT_SECRET must be configured"):
        resolve_jwt_secret(None, "development", "production")


def test_explicit_secret_is_preserved_and_not_marked_as_fallback():
    secret, fallback_used = resolve_jwt_secret("a-configured-secret-value", "production")

    assert secret == "a-configured-secret-value"
    assert fallback_used is False


def test_empty_secret_is_treated_as_missing_in_production():
    with pytest.raises(RuntimeError, match="JWT_SECRET must be configured"):
        resolve_jwt_secret("", "production")


def test_candidate_portal_secret_is_separate_from_recruiter_secret():
    portal_secret, fallback_used = resolve_candidate_portal_secret(
        "dedicated-portal-secret",
        "recruiter-secret",
        "production",
    )

    assert portal_secret == "dedicated-portal-secret"
    assert fallback_used is False


def test_railway_production_requires_dedicated_candidate_portal_secret():
    with pytest.raises(RuntimeError, match="CANDIDATE_PORTAL_JWT_SECRET must be configured"):
        resolve_candidate_portal_secret(
            None,
            "recruiter-secret",
            "development",
            "production",
        )


def test_candidate_portal_can_share_recruiter_secret_only_in_dev_test():
    portal_secret, fallback_used = resolve_candidate_portal_secret(
        None,
        "local-test-secret",
        "test",
    )

    assert portal_secret == "local-test-secret"
    assert fallback_used is True


def test_candidate_portal_uses_development_fallback_when_both_keys_missing_in_tests():
    portal_secret, fallback_used = resolve_candidate_portal_secret(
        None,
        "",
        "test",
    )

    assert portal_secret == DEVELOPMENT_JWT_SECRET
    assert fallback_used is True
