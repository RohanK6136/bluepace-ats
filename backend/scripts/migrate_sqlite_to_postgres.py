#!/usr/bin/env python3
"""Preflight/migrate a verified SQLite snapshot to an empty PostgreSQL database.

The default mode is read-only. Actual writes require both --apply and
--confirm-empty-target. The source SQLite snapshot is never changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import date, datetime, time, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text, update, bindparam
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.database import Base
from app import models as _models  # noqa: F401


BATCH_SIZE = 500


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_connection(path: Path) -> sqlite3.Connection:
    uri_path = path.resolve().as_posix().replace("?", "%3F").replace("#", "%23")
    return sqlite3.connect("file:" + uri_path + "?mode=ro", uri=True, timeout=30)


def _verify_snapshot(source: Path, manifest_path: Path) -> dict[str, Any]:
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError("Source snapshot is missing or empty")
    if not manifest_path.is_file():
        raise ValueError("A matching snapshot manifest is required")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Snapshot manifest is not valid JSON") from error
    if manifest.get("format_version") != 1 or manifest.get("backup_file") != source.name:
        raise ValueError("Snapshot manifest version or filename does not match")
    if manifest.get("integrity_check") != "ok":
        raise ValueError("Snapshot manifest does not record a successful integrity check")
    if int(manifest.get("foreign_key_violations", -1)) != 0:
        raise ValueError("Snapshot has foreign-key violations; investigate before migration")
    if source.stat().st_size != int(manifest.get("backup_size_bytes", -1)):
        raise ValueError("Snapshot size does not match manifest")
    if _sha256(source) != manifest.get("sha256"):
        raise ValueError("Snapshot SHA-256 does not match manifest")

    with _sqlite_connection(source) as connection:
        if [str(row[0]) for row in connection.execute("PRAGMA integrity_check")] != ["ok"]:
            raise ValueError("SQLite integrity_check failed")
        violations = list(connection.execute("PRAGMA foreign_key_check"))
        if violations:
            raise ValueError("SQLite foreign_key_check failed")
        counts = {}
        names = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        for (name,) in names:
            escaped = '"' + name.replace('"', '""') + '"'
            counts[name] = int(connection.execute("SELECT COUNT(*) FROM " + escaped).fetchone()[0])
    if counts != manifest.get("tables"):
        raise ValueError("Snapshot row counts do not match manifest")
    return manifest


def _normalise_target_url(url: str) -> str:
    url = url.strip()
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _source_engine(path: Path) -> Engine:
    return create_engine("sqlite:///" + path.as_posix(), connect_args={"check_same_thread": False})


def _count(connection, table: Table) -> int:
    return int(connection.execute(select(func.count()).select_from(table)).scalar_one())


def _canonical_value(value: Any, *, vector_value: bool = False) -> Any:
    """Normalise SQLAlchemy/driver values before comparing row checksums."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if vector_value and isinstance(value, (int, float)):
        return {"vector_float": format(float(value), ".7g")}
    if isinstance(value, int):
        return value
    if isinstance(value, Enum):
        return _canonical_value(value.value, vector_value=vector_value)
    if isinstance(value, datetime):
        normalised = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return {"datetime_utc": normalised.isoformat(timespec="microseconds")}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    if isinstance(value, time):
        normalised = value.isoformat(timespec="microseconds")
        return {"time": normalised}
    if isinstance(value, Decimal):
        return {"decimal": format(value.normalize(), "f")}
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if hasattr(value, "tolist"):
        return _canonical_value(value.tolist(), vector_value=vector_value)
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item, vector_value=vector_value)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item, vector_value=vector_value) for item in value]
    if isinstance(value, float):
        if vector_value:
            # pgvector stores float32 values; compare at precision supported by that storage.
            return {"vector_float": format(value, ".7g")}
        return value
    return str(value)


def _table_checksum(
    connection,
    table: Table,
    columns: list[str],
    primary_key_names: list[str],
    vector_columns: set[str],
) -> str:
    digest = hashlib.sha256()
    statement = select(*(table.c[name] for name in columns)).order_by(
        *(table.c[name] for name in primary_key_names)
    )
    for row in connection.execute(statement).mappings():
        canonical_row = {
            name: _canonical_value(row[name], vector_value=name in vector_columns)
            for name in columns
        }
        payload = json.dumps(
            canonical_row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        digest.update(payload)
        digest.update(b"\n")
    return digest.hexdigest()


def _validate_source(source_engine: Engine) -> dict[str, Table]:
    source_inspector = inspect(source_engine)
    source_names = {
        name for name in source_inspector.get_table_names()
        if not name.startswith("sqlite_")
    }
    model_names = set(Base.metadata.tables)
    reflected: dict[str, Table] = {}
    unknown_populated: list[str] = []
    unmapped_values: list[str] = []
    missing_required: list[str] = []

    with source_engine.connect() as connection:
        for name in sorted(source_names):
            source_table = Table(name, MetaData(), autoload_with=source_engine)
            reflected[name] = source_table
            count = _count(connection, source_table)
            if name not in model_names:
                if count:
                    unknown_populated.append(name + " (" + str(count) + " rows)")
                continue

            target_table = Base.metadata.tables[name]
            source_columns = set(source_table.c.keys())
            target_columns = set(target_table.c.keys())
            if count:
                if len(target_table.primary_key.columns) != 1:
                    missing_required.append(name + " (only single-column primary keys are supported)")
                for primary_key in target_table.primary_key.columns:
                    if primary_key.name not in source_columns:
                        missing_required.append(name + "." + primary_key.name + " (primary key)")
            for column_name in sorted(source_columns - target_columns):
                column = source_table.c[column_name]
                if int(connection.execute(
                    select(func.count()).select_from(source_table).where(column.is_not(None))
                ).scalar_one()):
                    unmapped_values.append(name + "." + column_name)

            if count:
                for target_column in target_table.columns:
                    if target_column.name in source_columns or target_column.primary_key:
                        continue
                    if target_column.nullable or target_column.default is not None or target_column.server_default is not None:
                        continue
                    missing_required.append(name + "." + target_column.name)

    if unknown_populated:
        raise ValueError("Populated source tables have no model mapping: " + ", ".join(unknown_populated))
    if unmapped_values:
        raise ValueError("Source has non-null data in unmapped columns: " + ", ".join(unmapped_values))
    if missing_required:
        raise ValueError("Source is missing required destination columns: " + ", ".join(missing_required))
    return reflected


def _assert_empty_postgres_target(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        raise ValueError("Destination must use PostgreSQL")
    inspector = inspect(engine)
    tables = inspector.get_table_names(schema="public")
    if tables:
        with engine.connect() as connection:
            populated = []
            for name in tables:
                table = Table(name, MetaData(), schema="public", autoload_with=engine)
                count = _count(connection, table)
                if count:
                    populated.append(name + " (" + str(count) + " rows)")
        if populated:
            raise ValueError("Destination has existing rows; refusing to merge: " + ", ".join(populated))
        raise ValueError("Destination already has public tables; use a fresh, empty PostgreSQL database")


def _topological_order(table_names: set[str]) -> list[str]:
    dependencies: dict[str, set[str]] = {name: set() for name in table_names}
    for name in table_names:
        table = Base.metadata.tables[name]
        for constraint in table.foreign_key_constraints:
            columns = list(constraint.columns)
            if not columns:
                continue
            # Nullable FKs are populated as NULL and restored after copying the rows.
            if all(table.c[column.name].nullable for column in columns):
                continue
            parent = constraint.referred_table.name
            if parent == name:
                raise ValueError("Non-nullable self-reference is unsupported in table " + name)
            if parent in table_names:
                dependencies[name].add(parent)

    ordered: list[str] = []
    remaining = set(table_names)
    while remaining:
        ready = sorted(name for name in remaining if not (dependencies[name] & remaining))
        if not ready:
            raise ValueError("Non-nullable foreign-key cycle: " + ", ".join(sorted(remaining)))
        ordered.extend(ready)
        remaining.difference_update(ready)
    return ordered


def _reset_sequences(connection, table_names: set[str]) -> None:
    for name in sorted(table_names):
        table = Base.metadata.tables[name]
        primary_keys = list(table.primary_key.columns)
        if len(primary_keys) != 1:
            raise ValueError("Single-column primary key required for safe sequence reset: " + name)
        primary_key = primary_keys[0]
        maximum = connection.execute(select(func.max(primary_key)).select_from(table)).scalar_one()
        if maximum is None:
            continue
        sequence_name = connection.execute(
            text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
            {"table_name": "public." + name, "column_name": primary_key.name},
        ).scalar_one_or_none()
        if sequence_name:
            connection.execute(
                text("SELECT setval(CAST(:sequence_name AS regclass), :last_value, true)"),
                {"sequence_name": sequence_name, "last_value": int(maximum)},
            )


def _copy_rows(source_engine: Engine, target_engine: Engine, source_tables: dict[str, Table]) -> tuple[dict[str, int], dict[str, str]]:
    with source_engine.connect() as connection:
        source_counts = {
            name: _count(connection, table)
            for name, table in source_tables.items()
        }
    populated = {name for name, count in source_counts.items() if count > 0}
    order = _topological_order(populated)
    deferred: list[tuple[str, Any, str, Any]] = []

    with source_engine.connect() as source_connection:
        with target_engine.begin() as target_connection:
            for name in order:
                source_table = source_tables[name]
                target_table = Base.metadata.tables[name]
                source_columns = set(source_table.c.keys())
                shared = sorted(source_columns & set(target_table.c.keys()))
                primary_keys = list(target_table.primary_key.columns)
                if len(primary_keys) != 1:
                    raise ValueError("Single-column primary key required for migration: " + name)
                pk_name = primary_keys[0].name
                nullable_fk_columns = {
                    column.name
                    for constraint in target_table.foreign_key_constraints
                    for column in constraint.columns
                    if all(target_table.c[fk_column.name].nullable for fk_column in constraint.columns)
                }

                result = source_connection.execute(select(source_table))
                while True:
                    rows = result.mappings().fetchmany(BATCH_SIZE)
                    if not rows:
                        break
                    batch = []
                    for row in rows:
                        values = {column: row[column] for column in shared}
                        if values.get(pk_name) is None:
                            raise ValueError("Missing primary key in table " + name)
                        for column_name in nullable_fk_columns:
                            if values.get(column_name) is not None:
                                deferred.append((name, values[pk_name], column_name, values[column_name]))
                                values[column_name] = None
                        batch.append(values)
                    if batch:
                        target_connection.execute(target_table.insert(), batch)

            grouped: dict[tuple[str, str], list[tuple[Any, Any]]] = {}
            for table_name, pk_value, column_name, fk_value in deferred:
                grouped.setdefault((table_name, column_name), []).append((pk_value, fk_value))
            for (table_name, column_name), values in grouped.items():
                table = Base.metadata.tables[table_name]
                pk_name = next(iter(table.primary_key.columns)).name
                statement = update(table).where(
                    table.c[pk_name] == bindparam("_migration_pk")
                ).values({column_name: bindparam("_migration_fk")})
                parameters = [
                    {"_migration_pk": pk_value, "_migration_fk": fk_value}
                    for pk_value, fk_value in values
                ]
                result = target_connection.execute(statement, parameters)
                if result.rowcount != len(parameters):
                    raise RuntimeError("Could not restore all nullable foreign keys in " + table_name)

            _reset_sequences(target_connection, populated)
            destination_counts = {
                name: _count(target_connection, Base.metadata.tables[name])
                for name in source_tables
                if name in Base.metadata.tables
            }
            mismatch = {
                name: {"source": source_counts[name], "destination": destination_counts[name]}
                for name in destination_counts
                if source_counts[name] != destination_counts[name]
            }
            if mismatch:
                raise RuntimeError("Row-count validation failed; transaction rolled back")

            table_checksums: dict[str, str] = {}
            for name, source_table in source_tables.items():
                if name not in Base.metadata.tables or source_counts[name] == 0:
                    continue
                target_table = Base.metadata.tables[name]
                primary_keys = [column.name for column in target_table.primary_key.columns]
                shared_columns = sorted(set(source_table.c.keys()) & set(target_table.c.keys()))
                vector_columns = {
                    column_name
                    for column_name in shared_columns
                    if isinstance(target_table.c[column_name].type, Vector)
                }
                source_checksum = _table_checksum(
                    source_connection, source_table, shared_columns, primary_keys, vector_columns
                )
                target_checksum = _table_checksum(
                    target_connection, target_table, shared_columns, primary_keys, vector_columns
                )
                if source_checksum != target_checksum:
                    raise RuntimeError("Content checksum validation failed in table " + name + "; transaction rolled back")
                table_checksums[name] = source_checksum
    return (
        {name: int(value) for name, value in source_counts.items() if name in Base.metadata.tables},
        table_checksums,
    )


def migrate_snapshot(
    source_path: str | Path,
    manifest_path: str | Path,
    target_url: str,
    *,
    apply: bool = False,
    confirm_empty_target: bool = False,
) -> dict[str, Any]:
    source = Path(source_path).expanduser().resolve()
    manifest_file = Path(manifest_path).expanduser().resolve()
    manifest = _verify_snapshot(source, manifest_file)
    if apply and not confirm_empty_target:
        raise ValueError("--apply requires --confirm-empty-target")
    if not target_url.strip():
        raise ValueError("Target connection URL is required")

    source_engine = _source_engine(source)
    target_engine = create_engine(_normalise_target_url(target_url), pool_pre_ping=True)
    try:
        source_tables = _validate_source(source_engine)
        _assert_empty_postgres_target(target_engine)
        with target_engine.connect() as connection:
            vector_available = connection.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector')")
            ).scalar_one()
        if not vector_available:
            raise ValueError("Destination does not provide the pgvector extension")

        with source_engine.connect() as connection:
            source_counts = {
                name: _count(connection, table)
                for name, table in source_tables.items()
            }
        report: dict[str, Any] = {
            "mode": "apply" if apply else "preflight_only",
            "source_snapshot": source.name,
            "source_sha256": manifest["sha256"],
            "source_rows": sum(source_counts.values()),
            "source_tables": len(source_counts),
            "populated_tables": sorted(name for name, count in source_counts.items() if count),
            "target_dialect": target_engine.dialect.name,
            "target_modified": False,
        }
        if not apply:
            return report

        with target_engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(bind=target_engine)
        copied_counts, table_checksums = _copy_rows(source_engine, target_engine, source_tables)
        report["target_modified"] = True
        report["table_counts_match"] = True
        report["table_checksums_match"] = True
        report["migrated_tables"] = len(copied_counts)
        report["destination_rows"] = sum(copied_counts.values())
        report["table_counts"] = copied_counts
        report["table_sha256"] = table_checksums
        return report
    finally:
        source_engine.dispose()
        target_engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Preflight or migrate a verified SQLite snapshot to empty PostgreSQL.")
    parser.add_argument("--source", required=True, help="Immutable .sqlite3 snapshot file")
    parser.add_argument("--manifest", required=True, help="Matching .manifest.json file")
    parser.add_argument("--target-url-env", default="MIGRATION_TARGET_DATABASE_URL")
    parser.add_argument("--apply", action="store_true", help="Perform the migration; default is preflight-only")
    parser.add_argument("--confirm-empty-target", action="store_true", help="Required with --apply")
    args = parser.parse_args()
    target_url = os.getenv(args.target_url_env, "")
    try:
        result = migrate_snapshot(
            args.source,
            args.manifest,
            target_url,
            apply=args.apply,
            confirm_empty_target=args.confirm_empty_target,
        )
    except (OSError, ValueError, RuntimeError, sqlite3.Error, SQLAlchemyError) as error:
        print("Migration failed (" + type(error).__name__ + "). Review the source snapshot and target database.", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
