import importlib.util
import json
import sqlite3
import stat
from datetime import datetime
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sqlite_snapshot.py"
SPEC = importlib.util.spec_from_file_location("sqlite_snapshot", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
sqlite_snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sqlite_snapshot)


def make_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE organizations (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                organization_id INTEGER NOT NULL
                    REFERENCES organizations(id),
                email TEXT NOT NULL
            );
            INSERT INTO organizations (id, name) VALUES (1, 'Example Org');
            INSERT INTO users (id, organization_id, email)
                VALUES (1, 1, 'candidate-private@example.test');
            """
        )


def test_snapshot_is_consistent_and_manifest_has_counts_without_row_data(tmp_path):
    source = tmp_path / "bluepace_ats.db"
    output_dir = tmp_path / "private-backups"
    make_database(source)

    result = sqlite_snapshot.create_snapshot(source, output_dir)

    backup = Path(result["backup_path"])
    manifest_path = Path(result["manifest_path"])
    assert backup.is_file()
    assert manifest_path.is_file()
    assert result["integrity_check"] == "ok"
    assert result["tables"] == {"organizations": 1, "users": 1}
    assert result["total_rows"] == 2
    assert len(result["sha256"]) == 64

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["tables"] == {"organizations": 1, "users": 1}
    assert "candidate-private@example.test" not in manifest_path.read_text(encoding="utf-8")

    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT email FROM users").fetchone()[0] == "candidate-private@example.test"

    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o600

    # The source is untouched; the snapshot copies rather than mutates it.
    with sqlite3.connect(source) as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_snapshot_refuses_missing_source_database(tmp_path):
    with pytest.raises(FileNotFoundError, match="does not exist"):
        sqlite_snapshot.create_snapshot(tmp_path / "missing.db", tmp_path / "backups")


def test_snapshot_refuses_zero_byte_source(tmp_path):
    source = tmp_path / "empty.db"
    source.touch()

    with pytest.raises(ValueError, match="zero-byte"):
        sqlite_snapshot.create_snapshot(source, tmp_path / "backups")


def test_snapshot_refuses_to_overwrite_existing_artifacts(tmp_path, monkeypatch):
    source = tmp_path / "bluepace_ats.db"
    output_dir = tmp_path / "backups"
    make_database(source)

    class FixedDateTime:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 1, 2, 3, 4, 5, 6, tzinfo=tz)

    # Pin the generated timestamp so a second run exercises the collision guard.
    monkeypatch.setattr(sqlite_snapshot, "datetime", FixedDateTime)
    sqlite_snapshot.create_snapshot(source, output_dir)
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        sqlite_snapshot.create_snapshot(source, output_dir)
