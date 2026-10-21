"""Outgoing email transport intentionally disabled for BluePace ATS."""

from app.database import SessionLocal
from app.models import Email

DELIVERY_DISABLED_MESSAGE = "Outgoing email delivery is disabled for this ATS."


def deliver_outbox_email(email_id: int) -> None:
    """Never call an external email provider; neutralize any legacy outbox item."""
    with SessionLocal() as db:
        email_record = db.get(Email, email_id)
        if email_record is None or email_record.status == "sent":
            return

        email_record.status = "disabled"
        email_record.sent_at = None
        email_record.error_message = DELIVERY_DISABLED_MESSAGE
        db.commit()



def disable_pending_email_records() -> int:
    """Mark all unsent legacy outbox records disabled without contacting a provider."""
    with SessionLocal() as db:
        changed = db.query(Email).filter(
            Email.status.in_(("draft", "pending", "queued", "failed"))
        ).update(
            {
                Email.status: "disabled",
                Email.sent_at: None,
                Email.error_message: DELIVERY_DISABLED_MESSAGE,
            },
            synchronize_session=False,
        )
        if changed:
            db.commit()
        return int(changed)
