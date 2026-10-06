import base64
import json
import os
import smtplib
import urllib.error
import urllib.request
import traceback
from datetime import datetime, timezone
from email.message import EmailMessage

from app.database import SessionLocal
from app.models import Email


def _mark_sent(email_record):
    email_record.status = "sent"
    email_record.sent_at = datetime.now(timezone.utc)
    email_record.error_message = None


def _send_via_brevo(email_record, api_key, sender):
    payload = {
        "sender": {
            "email": sender,
        },
        "to": [
            {
                "email": email_record.recipient,
            }
        ],
        "subject": email_record.subject,
        "textContent": email_record.body,
    }

    if email_record.attachment_content and email_record.attachment_filename:
        payload["attachment"] = [
            {
                "name": email_record.attachment_filename,
                "content": email_record.attachment_content,
            }
        ]

    request = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"Brevo returned HTTP {response.status}")


def _send_via_smtp(email_record, smtp_host, sender):
    message = EmailMessage()
    message["From"] = sender
    message["To"] = email_record.recipient
    message["Subject"] = email_record.subject
    message.set_content(email_record.body)

    if email_record.attachment_content and email_record.attachment_filename:
        try:
            attachment = base64.b64decode(email_record.attachment_content)
        except (ValueError, TypeError):
            attachment = None
        if attachment is not None:
            content_type = email_record.attachment_content_type or "application/octet-stream"
            maintype, subtype = content_type.split("/", 1)
            message.add_attachment(
                attachment,
                maintype=maintype,
                subtype=subtype,
                filename=email_record.attachment_filename,
            )

    port = int(os.getenv("SMTP_PORT", "587"))
    with smtplib.SMTP(smtp_host, port, timeout=10) as client:
        client.starttls()
        username = os.getenv("SMTP_USER")
        password = os.getenv("SMTP_PASSWORD")
        if username and password:
            client.login(username, password)
        client.send_message(message)


def deliver_outbox_email(email_id: int):
    with SessionLocal() as db:
        email_record = db.get(Email, email_id)
        if email_record is None:
            return

        provider = os.getenv("EMAIL_PROVIDER", "").strip().lower()
        brevo_api_key = os.getenv("BREVO_API_KEY", "").strip()
        sender = (
            os.getenv("EMAIL_FROM")
            or os.getenv("SMTP_FROM")
            or os.getenv("SMTP_USER")
            or ""
        ).strip()

        try:
            if provider == "brevo":
                if not brevo_api_key:
                    raise RuntimeError("BREVO_API_KEY is not configured")
                if not sender:
                    raise RuntimeError("EMAIL_FROM is not configured")
                _send_via_brevo(email_record, brevo_api_key, sender)
            else:
                smtp_host = os.getenv("SMTP_HOST", "").strip()
                if not smtp_host:
                    raise RuntimeError(
                        "SMTP_HOST is not configured. Set EMAIL_PROVIDER=brevo for HTTP email delivery."
                    )
                if not sender:
                    raise RuntimeError("SMTP_FROM or SMTP_USER is not configured")
                _send_via_smtp(email_record, smtp_host, sender)

            _mark_sent(email_record)
        except (OSError, smtplib.SMTPException, urllib.error.URLError, ValueError, RuntimeError, json.JSONDecodeError) as error:
            email_record.status = "failed"
            email_record.error_message = str(error)[:2000]
            print(
                f"EMAIL_DELIVERY_FAILED id={email_record.id} recipient={email_record.recipient} "
                f"provider={provider or 'smtp'} error={error}",
                flush=True,
            )
            traceback.print_exc()
        db.commit()
