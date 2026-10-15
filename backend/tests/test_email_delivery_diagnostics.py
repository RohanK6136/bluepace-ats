from io import BytesIO
from urllib.error import HTTPError

from app.services.email_notifications import _delivery_error_message


def make_http_error(status_code: int, payload: bytes = b""):
    return HTTPError(
        url="https://api.brevo.com/v3/smtp/email",
        code=status_code,
        msg="Provider error",
        hdrs=None,
        fp=BytesIO(payload),
    )


def test_brevo_401_gives_actionable_api_key_guidance():
    error = make_http_error(401, b'{"message":"Key not found"}')

    detail = _delivery_error_message(error, "brevo")

    assert "HTTP 401" in detail
    assert "BREVO_API_KEY" in detail
    assert "active Brevo REST API key" in detail
    assert "Key not found" in detail


def test_brevo_403_points_to_sender_and_account_permissions():
    detail = _delivery_error_message(make_http_error(403), "brevo")

    assert "HTTP 403" in detail
    assert "sender verification" in detail


def test_provider_error_message_does_not_log_credentials():
    secret = "never-print-this-secret"
    error = make_http_error(401, b'{"message":"Key not found"}')

    detail = _delivery_error_message(error, "brevo")

    assert secret not in detail
