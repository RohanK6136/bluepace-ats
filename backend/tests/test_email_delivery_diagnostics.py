from types import SimpleNamespace

from app.services import email_notifications


class FakeSession:
    def __init__(self, record):
        self.record = record
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, model, email_id):
        return self.record if self.record and self.record.id == email_id else None

    def commit(self):
        self.committed = True


def test_pending_legacy_email_is_disabled_without_sending(monkeypatch):
    record = SimpleNamespace(id=7, status="pending", sent_at=None, error_message=None)
    db = FakeSession(record)
    monkeypatch.setattr(email_notifications, "SessionLocal", lambda: db)

    email_notifications.deliver_outbox_email(7)

    assert record.status == "disabled"
    assert record.sent_at is None
    assert "disabled" in record.error_message.lower()
    assert db.committed is True


def test_failed_legacy_email_is_disabled_without_sending(monkeypatch):
    record = SimpleNamespace(id=8, status="failed", sent_at=None, error_message="old provider error")
    db = FakeSession(record)
    monkeypatch.setattr(email_notifications, "SessionLocal", lambda: db)

    email_notifications.deliver_outbox_email(8)

    assert record.status == "disabled"
    assert "disabled" in record.error_message.lower()


def test_historical_sent_email_is_not_rewritten(monkeypatch):
    record = SimpleNamespace(id=9, status="sent", sent_at="historic-time", error_message=None)
    db = FakeSession(record)
    monkeypatch.setattr(email_notifications, "SessionLocal", lambda: db)

    email_notifications.deliver_outbox_email(9)

    assert record.status == "sent"
    assert record.sent_at == "historic-time"
    assert db.committed is False
