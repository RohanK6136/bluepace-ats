from datetime import datetime, timezone
from types import SimpleNamespace

from app.routers import merge_center  # noqa: F401
from app.main import _as_utc


def test_interview_time_normalization():
    value = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    assert _as_utc(value).tzinfo == timezone.utc


def test_interviewer_panel_ids_are_unique():
    ids = list(dict.fromkeys([4, 4, 7, 9, 7]))
    assert ids == [4, 7, 9]
