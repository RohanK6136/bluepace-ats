from app.services.production_config import validate_production_config


def good_environment():
    return {
        "APP_ENV": "production",
        "DATABASE_URL": "postgresql://user:password@example.invalid:5432/bluepace",
        "JWT_SECRET": "x" * 48,
        "ALLOWED_ORIGINS": "https://bluepace-ats-frontend.vercel.app",
        "B2_ENDPOINT": "https://s3.us-west-004.backblazeb2.com",
        "B2_ACCESS_KEY_ID": "test-access-key",
        "B2_SECRET_ACCESS_KEY": "test-secret-key",
        "B2_BUCKET": "bluepace-private",
        "B2_REGION": "us-west-004",
    }


def test_valid_production_configuration_passes_without_echoing_secrets():
    errors, warnings = validate_production_config(good_environment())

    assert errors == []
    assert warnings == []


def test_missing_environment_database_and_jwt_fail_closed():
    errors, _warnings = validate_production_config({})

    assert any("APP_ENV" in item for item in errors)
    assert any("DATABASE_URL" in item for item in errors)
    assert any("JWT_SECRET" in item for item in errors)
    assert any("ALLOWED_ORIGINS" in item for item in errors)


def test_development_fallback_and_short_jwt_secret_are_rejected():
    env = good_environment()
    env["JWT_SECRET"] = "local-development-only-change-me"

    errors, _warnings = validate_production_config(env)

    assert any("development fallback" in item for item in errors)


def test_production_http_origin_and_wildcard_are_rejected():
    env = good_environment()
    env["ALLOWED_ORIGINS"] = "http://example.com, *"

    errors, _warnings = validate_production_config(env)

    assert any("must use HTTPS" in item for item in errors)
    assert any("wildcard" in item for item in errors)


def test_sqlite_requires_explicit_opt_in_and_reports_durability_warning():
    env = good_environment()
    env["DATABASE_URL"] = "sqlite:///./bluepace.db"

    errors, _warnings = validate_production_config(env)
    assert any("uses SQLite" in item for item in errors)

    env["ALLOW_PERSISTENT_SQLITE"] = "true"
    errors, warnings = validate_production_config(env)
    assert not any("DATABASE_URL" in item for item in errors)
    assert any("single app replica" in item for item in warnings)


def test_partial_backblaze_configuration_is_an_error():
    env = good_environment()
    env.pop("B2_BUCKET")

    errors, _warnings = validate_production_config(env)

    assert any("configuration is incomplete" in item for item in errors)


def test_missing_backblaze_configuration_is_a_warning_not_a_crash():
    env = good_environment()
    for name in (
        "B2_ENDPOINT",
        "B2_ACCESS_KEY_ID",
        "B2_SECRET_ACCESS_KEY",
        "B2_BUCKET",
        "B2_REGION",
    ):
        env.pop(name)

    errors, warnings = validate_production_config(env)

    assert errors == []
    assert any("not configured" in item for item in warnings)


def test_staging_allows_http_origins_for_nonproduction_preview_hosts():
    env = good_environment()
    env["APP_ENV"] = "staging"
    env["ALLOWED_ORIGINS"] = "http://staging.example.invalid"

    errors, _warnings = validate_production_config(env)

    assert errors == []
