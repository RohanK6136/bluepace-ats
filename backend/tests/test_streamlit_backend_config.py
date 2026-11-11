from streamlit_app.backend_config import default_api_url_from_environment, normalize_api_url


def test_normalize_api_url_trims_whitespace_and_trailing_slashes():
    assert normalize_api_url("  https://api.example.com/  ") == "https://api.example.com"


def test_normalize_api_url_allows_local_http_development():
    assert normalize_api_url("http://localhost:8000/") == "http://localhost:8000"
    assert normalize_api_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000"
    assert normalize_api_url("http://[::1]:8000") == "http://[::1]:8000"


def test_normalize_api_url_rejects_remote_http_and_non_web_schemes():
    assert normalize_api_url("http://api.example.com") == ""
    assert normalize_api_url("ftp://api.example.com") == ""
    assert normalize_api_url("javascript:alert(1)") == ""


def test_normalize_api_url_rejects_retired_railway_hosts():
    for value in (
        "https://railway.app",
        "https://bluepace-ats-production.up.railway.app",
        "https://private.railway.internal",
    ):
        assert normalize_api_url(value) == ""


def test_normalize_api_url_rejects_credentials_query_and_fragment():
    assert normalize_api_url("https://user:pass@api.example.com") == ""
    assert normalize_api_url("https://api.example.com?token=secret") == ""
    assert normalize_api_url("https://api.example.com#fragment") == ""
    assert normalize_api_url("https://api.example.com:bad-port") == ""


def test_default_api_url_from_environment_applies_same_policy():
    assert default_api_url_from_environment({"ATS_API_URL": "https://api.example.com/"}) == "https://api.example.com"
    assert default_api_url_from_environment({"ATS_API_URL": "https://bluepace-ats-production.up.railway.app"}) == ""
    assert default_api_url_from_environment({}) == ""
