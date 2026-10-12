import importlib.util
import json
import os
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_script(name: str, module_name: str):
    path = SCRIPT_DIR / name
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


snapshot_tool = load_script("sqlite_snapshot.py", "migration_test_sqlite_snapshot")
migration_tool = load_script("migrate_sqlite_to_postgres.py", "migration_test_sqlite_postgres")
from app.database import Base
from app.models import Organization, RagChunk, Role, User


POSTGRES_URL = os.getenv("MIGRATION_TEST_POSTGRES_URL", "")


def make_source_database(path: Path) -> None:
    engine = create_engine("sqlite:///" + path.as_posix())
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(
            Organization.__table__.insert().values(
                id=731, name="Migration Test Organization"
            )
        )
        connection.execute(
            User.__table__.insert().values(
                id=941,
                organization_id=731,
                email="migration-test@example.invalid",
                full_name="Migration Test User",
                password_hash="not-a-real-password-hash",
                role=Role.admin,
                is_active=True,
            )
        )
        connection.execute(
            RagChunk.__table__.insert().values(
                id=1201,
                organization_id=731,
                source_type="candidate",
                source_id=941,
                field="resume_summary",
                content="synthetic migration checksum row",
                embedding=[0.0] * 1535 + [0.123456789],
            )
        )
    engine.dispose()


@pytest.mark.skipif(not POSTGRES_URL, reason="MIGRATION_TEST_POSTGRES_URL not configured")
def test_verified_snapshot_migrates_to_empty_pgvector_postgres(tmp_path):
    source = tmp_path / "migration-source.sqlite3"
    backup_dir = tmp_path / "snapshots"
    make_source_database(source)

    snapshot = snapshot_tool.create_snapshot(source, backup_dir)
    snapshot_path = Path(snapshot["backup_path"])
    manifest_path = Path(snapshot["manifest_path"])

    preflight = migration_tool.migrate_snapshot(
        snapshot_path, manifest_path, POSTGRES_URL, apply=False
    )
    assert preflight["mode"] == "preflight_only"
    assert preflight["target_modified"] is False
    assert preflight["source_rows"] == 3
    assert preflight["populated_tables"] == ["organizations", "rag_chunks", "users"]

    with pytest.raises(ValueError, match="requires --confirm-empty-target"):
        migration_tool.migrate_snapshot(
            snapshot_path, manifest_path, POSTGRES_URL, apply=True
        )

    result = migration_tool.migrate_snapshot(
        snapshot_path,
        manifest_path,
        POSTGRES_URL,
        apply=True,
        confirm_empty_target=True,
    )
    assert result["mode"] == "apply"
    assert result["target_modified"] is True
    assert result["table_counts_match"] is True
    assert result["table_checksums_match"] is True
    assert set(result["table_sha256"]) >= {"organizations", "users"}
    assert all(len(value) == 64 for value in result["table_sha256"].values())
    assert result["destination_rows"] == 3
    assert result["table_counts"]["organizations"] == 1
    assert result["table_counts"]["rag_chunks"] == 1
    assert result["table_counts"]["users"] == 1

    target_engine = create_engine(POSTGRES_URL)
    try:
        with target_engine.connect() as connection:
            assert connection.execute(
                select(Organization.__table__.c.name).where(
                    Organization.__table__.c.id == 731
                )
            ).scalar_one() == "Migration Test Organization"
            assert connection.execute(
                select(User.__table__.c.email).where(User.__table__.c.id == 941)
            ).scalar_one() == "migration-test@example.invalid"
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        target_engine.dispose()

    # Source data remains untouched after a successful migration.
    with sqlite3.connect(source) as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert connection.execute(
            "SELECT email FROM users WHERE id = 941"
        ).fetchone()[0] == "migration-test@example.invalid"

    # A rerun must not merge into a populated target.
    with pytest.raises(ValueError, match="Destination has existing rows"):
        migration_tool.migrate_snapshot(
            snapshot_path,
            manifest_path,
            POSTGRES_URL,
            apply=True,
            confirm_empty_target=True,
        )


def test_snapshot_hash_mismatch_is_rejected_before_target_connection(tmp_path):
    source = tmp_path / "migration-source.sqlite3"
    backup_dir = tmp_path / "snapshots"
    make_source_database(source)
    snapshot = snapshot_tool.create_snapshot(source, backup_dir)
    snapshot_path = Path(snapshot["backup_path"])
    manifest_path = Path(snapshot["manifest_path"])

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256"):
        migration_tool.migrate_snapshot(
            snapshot_path, manifest_path, "postgresql://invalid:invalid@127.0.0.1:1/db"
        )
