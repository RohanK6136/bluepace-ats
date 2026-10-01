from datetime import datetime, timezone
from types import SimpleNamespace

from app.routers import merge_center  # noqa: F401
def test_interviewer_panel_ids_are_unique():
    ids = list(dict.fromkeys([4, 4, 7, 9, 7]))
    assert ids == [4, 7, 9]
