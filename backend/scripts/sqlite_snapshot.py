#!/usr/bin/env python3
"""Create a consistent, validated, read-only snapshot of a SQLite database.

This utility deliberately does not modify the source database and never uploads
or prints row contents. Keep the snapshot and its manifest outside version
control; ATS records may contain personal and recruiting data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


def _connect_read_only(path: Path) -> sqlite3.Connection:
    uri_path = quote(path.resolve().as_posix(), safe="/:")
    return sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True, timeout=30)


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _snapshot_table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = connection.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return {
        name: int(
            connection.execute(
                f"SELECT COUNT(*) FROM {_quote_identifier(name)}"
            ).fetchone()[0]
        )
        for (name,) in tables
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_snapshot(database_path: str | Path, output_directory: str | Path) -> dict:
    """Back up a SQLite file through SQLite's online-backup API and validate it."""
    source_path = Path(database_path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite database file does not exist: {source_path}")
    if source_path.stat().st_size == 0:
        raise ValueError("Refusing to snapshot a zero-byte database file")

    output_path = Path(output_directory).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = output_path / f"bluepace-ats-{stamp}.sqlite3"
    partial_path = output_path / f".{backup_path.name}.partial"
    manifest_path = backup_path.with_suffix(".manifest.json")
    manifest_partial_path = output_path / f".{manifest_path.name}.partial"

    for path in (backup_path, partial_path, manifest_path, manifest_partial_path):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite existing backup artifact: {path.name}")

    # Create the destination with restrictive permissions before SQLite opens it.
    descriptor = os.open(partial_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        source_connection = _connect_read_only(source_path)
        try:
            destination_connection = sqlite3.connect(str(partial_path), timeout=30)
            try:
                source_connection.backup(destination_connection, pages=256, sleep=0.1)
                integrity_results = [
                    str(row[0])
                    for row in destination_connection.execute("PRAGMA integrity_check")
                ]
                if integrity_results != ["ok"]:
                    raise RuntimeError(
                        "SQLite snapshot failed integrity_check; backup was not published"
                    )
                table_counts = _snapshot_table_counts(destination_connection)
                foreign_key_violations = sum(
                    1
                    for _ in destination_connection.execute("PRAGMA foreign_key_check")
                )
            finally:
                destination_connection.close()
        finally:
            source_connection.close()

        os.chmod(partial_path, 0o600)
        os.replace(partial_path, backup_path)
        metadata = {
            "format_version": 1,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_database_name": source_path.name,
            "backup_file": backup_path.name,
            "backup_size_bytes": backup_path.stat().st_size,
            "sha256": _sha256(backup_path),
            "integrity_check": "ok",
            "foreign_key_violations": foreign_key_violations,
            "tables": table_counts,
            "total_rows": sum(table_counts.values()),
        }
        with manifest_partial_path.open("x", encoding="utf-8") as file_handle:
            json.dump(metadata, file_handle, indent=2, sort_keys=True)
            file_handle.write("\n")
        os.chmod(manifest_partial_path, 0o600)
        os.replace(manifest_partial_path, manifest_path)
        return {"backup_path": str(backup_path), "manifest_path": str(manifest_path), **metadata}
    except Exception:
        partial_path.unlink(missing_ok=True)
        manifest_partial_path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a consistent, read-only SQLite database snapshot."
    )
    parser.add_argument(
        "--database",
        required=True,
        help="Path to the SQLite database file (for Railway's current image, typically /app/bluepace_ats.db).",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for the private backup and JSON manifest; transfer them off the container before redeploying.",
    )
    args = parser.parse_args()
    try:
        result = create_snapshot(args.database, args.output_dir)
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as error:
        print(f"Backup failed: {error}", file=sys.stderr)
        return 1
    # Only metadata is printed; row contents and credentials are never emitted.
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
