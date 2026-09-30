import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

from app.database import SessionLocal
from app.models import Email


def deliver_outbox_email(email_id: int):
    with SessionLocal() as db:
        email_record = db.get(Email, email_id)
        if email_record is None:
            return

        smtp_host = os.getenv("SMTP_HOST")
        if not smtp_host:
            email_record.status = "failed"
            email_record.error_message = "SMTP_HOST is not configured"
            db.commit()
            return

        message = EmailMessage()
        message["From"] = os.getenv("SMTP_FROM", os.getenv("SMTP_USER", ""))
        message["To"] = email_record.recipient
        message["Subject"] = email_record.subject
        message.set_content(email_record.body)

        try:
            port = int(os.getenv("SMTP_PORT", "587"))
            with smtplib.SMTP(smtp_host, port, timeout=10) as client:
                client.starttls()
                username = os.getenv("SMTP_USER")
                password = os.getenv("SMTP_PASSWORD")
                if username and password:
                    client.login(username, password)
                client.send_message(message)
            email_record.status = "sent"
            email_record.sent_at = datetime.now(timezone.utc)
            email_record.error_message = None
        except (OSError, smtplib.SMTPException, ValueError) as error:
            email_record.status = "failed"
            email_record.error_message = str(error)[:2000]
        db.commit()