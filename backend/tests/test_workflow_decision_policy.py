from types import SimpleNamespace

import pytest

from app.routers.next_features import _apply_automation_action
from app.services.workflow import queue_application_email


class RecordingSession:
    def __init__(self):
        self.added = []

    def add(self, value):
        self.added.append(value)


@pytest.mark.parametrize("target_stage", ["Offer", "Hired", "Rejected"])
def test_automation_cannot_make_hiring_decisions(target_stage):
    db = RecordingSession()
    application = SimpleNamespace(
        id=44,
        organization_id=9,
        stage_id=2,
        candidate=SimpleNamespace(needs_review=False),
    )
    rule = SimpleNamespace(
        id=12,
        created_by_id=5,
        action_type="move_stage",
        action_value=target_stage,
    )

    result = _apply_automation_action(db, application, rule, "Interview")

    assert result == []
    assert application.stage_id == 2
    assert application.candidate.needs_review is True
    assert len(db.added) == 1
    audit = db.added[0]
    assert audit.action == "automation.stage_move_blocked"
    assert audit.entity_type == "application"
    assert audit.entity_id == application.id
    assert audit.after_data == {
        "requested_stage": target_stage,
        "rule_id": rule.id,
        "reason": "human_approval_required",
    }


def test_application_email_queue_is_optional_and_inert():
    # Email delivery is intentionally disabled. Workflow actions must not
    # require SMTP credentials or create an email-outbox record.
    db = RecordingSession()
    application = SimpleNamespace(id=44)

    queued_id = queue_application_email(
        db,
        application,
        "Application update",
        "Your application has moved to screening.",
    )

    assert queued_id == 0
    assert db.added == []
