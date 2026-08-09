"""Portable, single-file host migrations for NovaGuard.

The regular backup system intentionally creates ZIP archives.  A host move has
a different goal: one human-readable SQL file that can rebuild the SQLite
database and carry the small JSON state files that still live beside it.

Secrets are deliberately excluded.  ``.env``, cookies and rclone credentials
must be configured independently on the destination host.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from .config import BASE_DIR
from .database import DB_PATH, init_database

FORMAT_VERSION = 1
MARKER_TABLE = "__novaguard_host_migration"
FILES_TABLE = "__novaguard_host_files"


class HostMigrationError(RuntimeError):
    """Raised when a host migration cannot be safely created or restored."""


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _integrity(connection: sqlite3.Connection) -> None:
    result = connection.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        raise HostMigrationError(f"SQLite integrity check failed: {result[0] if result else 'no result'}")
    foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise HostMigrationError(f"SQLite foreign key check found {len(foreign_key_errors)} error(s)")


def _data_counts(connection: sqlite3.Connection) -> dict[str, int]:
    excluded = {MARKER_TABLE, FILES_TABLE}
    names = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        if row[0] not in excluded
    ]
    counts = {}
    for name in names:
        quoted_name = name.replace('"', '""')
        counts[name] = connection.execute(f'SELECT COUNT(*) FROM "{quoted_name}"').fetchone()[0]
    return counts


def _auxiliary_files(base_dir: Path) -> list[tuple[str, Path]]:
    """Return state files that are safe and useful to carry inside the SQL."""
    files: list[tuple[str, Path]] = []
    data_dir = base_dir / "data"
    if data_dir.exists():
        for path in sorted(data_dir.glob("*.json")):
            if path.is_file():
                files.append((f"data/{path.name}", path))

    for relative, path in (
        (".update_state.json", base_dir / ".update_state.json"),
        (".github_state.json", base_dir / ".github_state.json"),
    ):
        if path.is_file():
            files.append((relative, path))
    return files


def _safe_auxiliary_target(base_dir: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if relative in {".update_state.json", ".github_state.json"}:
        return base_dir / relative
    if len(path.parts) == 2 and path.parts[0] == "data" and path.suffix == ".json":
        return base_dir / "data" / path.name
    raise HostMigrationError(f"Unsafe auxiliary path in migration: {relative}")


def _prepare_snapshot(source_db: Path, snapshot_db: Path, base_dir: Path) -> int:
    source = sqlite3.connect(source_db)
    target = sqlite3.connect(snapshot_db)
    try:
        source.backup(target)
        _integrity(target)
        target.execute(f'DROP TABLE IF EXISTS "{MARKER_TABLE}"')
        target.execute(f'DROP TABLE IF EXISTS "{FILES_TABLE}"')
        target.execute(
            f'''CREATE TABLE "{MARKER_TABLE}" (
                format_version INTEGER NOT NULL,
                app TEXT NOT NULL,
                exported_at TEXT NOT NULL
            )'''
        )
        target.execute(
            f'''CREATE TABLE "{FILES_TABLE}" (
                path TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                sha256 TEXT NOT NULL
            )'''
        )
        target.execute(
            f'INSERT INTO "{MARKER_TABLE}" (format_version, app, exported_at) VALUES (?, ?, ?)',
            (FORMAT_VERSION, "NovaGuard", datetime.now(UTC).isoformat()),
        )

        count = 0
        for relative, path in _auxiliary_files(base_dir):
            try:
                content = path.read_text(encoding="utf-8")
                json.loads(content)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise HostMigrationError(f"Cannot include {relative}: {error}") from error
            target.execute(
                f'INSERT INTO "{FILES_TABLE}" (path, content, sha256) VALUES (?, ?, ?)',
                (relative, content, _sha256(content)),
            )
            count += 1
        target.commit()
        return count
    finally:
        target.close()
        source.close()


def export_host_sql(
    output_path: str | Path | None = None,
    *,
    base_dir: str | Path = BASE_DIR,
    db_path: str | Path = DB_PATH,
) -> dict:
    """Create a consistent SQL dump containing all portable NovaGuard state."""
    base_dir = Path(base_dir)
    db_path = Path(db_path)
    if db_path == DB_PATH:
        init_database()
    if not db_path.exists():
        raise HostMigrationError(f"Database does not exist: {db_path}")

    output = Path(output_path) if output_path else base_dir / "backups" / f"novaguard-host-{_timestamp()}.sql"
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="novaguard-host-export-") as temp_dir:
        snapshot = Path(temp_dir) / "snapshot.sqlite3"
        auxiliary_count = _prepare_snapshot(db_path, snapshot, base_dir)
        snapshot_connection = sqlite3.connect(snapshot)
        try:
            table_count = len(_data_counts(snapshot_connection))
            dump = "\n".join(snapshot_connection.iterdump()) + "\n"
        finally:
            snapshot_connection.close()

    header = (
        "-- NovaGuard portable host migration\n"
        f"-- Format: {FORMAT_VERSION}\n"
        "-- Contains application data, not .env secrets or credentials.\n"
    )
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(header + dump, encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, output)
    return {
        "path": str(output),
        "size": output.stat().st_size,
        "tables": table_count,
        "auxiliary_files": auxiliary_count,
    }


def _load_and_validate(sql_path: Path, staging_db: Path) -> tuple[dict, list[tuple[str, str]]]:
    try:
        script = sql_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise HostMigrationError(f"Cannot read migration file: {error}") from error

    connection = sqlite3.connect(staging_db)
    try:
        try:
            connection.executescript(script)
        except sqlite3.Error as error:
            raise HostMigrationError(f"Invalid migration SQL: {error}") from error

        marker = connection.execute(
            f'SELECT format_version, app, exported_at FROM "{MARKER_TABLE}" LIMIT 1'
        ).fetchone()
        if not marker or marker[1] != "NovaGuard":
            raise HostMigrationError("This is not a NovaGuard host migration file")
        if marker[0] != FORMAT_VERSION:
            raise HostMigrationError(
                f"Unsupported migration format {marker[0]}; expected {FORMAT_VERSION}"
            )

        files: list[tuple[str, str]] = []
        for relative, content, expected_hash in connection.execute(
            f'SELECT path, content, sha256 FROM "{FILES_TABLE}" ORDER BY path'
        ):
            if _sha256(content) != expected_hash:
                raise HostMigrationError(f"Checksum mismatch for {relative}")
            try:
                json.loads(content)
            except json.JSONDecodeError as error:
                raise HostMigrationError(f"Invalid JSON stored for {relative}: {error}") from error
            files.append((relative, content))

        _integrity(connection)
        row_counts = _data_counts(connection)
        info = {
            "format_version": marker[0],
            "exported_at": marker[2],
            "auxiliary_files": len(files),
            "tables": len(row_counts),
            "rows": sum(row_counts.values()),
            "row_counts": row_counts,
        }
        return info, files
    except sqlite3.Error as error:
        raise HostMigrationError(f"Missing or invalid migration metadata: {error}") from error
    finally:
        connection.close()


def verify_host_sql(sql_path: str | Path) -> dict:
    """Fully load and validate a migration without changing live state."""
    sql_path = Path(sql_path)
    if not sql_path.is_file():
        raise HostMigrationError(f"Migration file does not exist: {sql_path}")
    with tempfile.TemporaryDirectory(prefix="novaguard-host-verify-") as temp_dir:
        info, _ = _load_and_validate(sql_path, Path(temp_dir) / "verify.sqlite3")
    return {**info, "path": str(sql_path), "size": sql_path.stat().st_size, "ok": True}


def _create_pre_import_backup(base_dir: Path, db_path: Path) -> Path | None:
    candidates = _auxiliary_files(base_dir)
    if not db_path.exists() and not candidates:
        return None

    backup_dir = base_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"novaguard-pre-host-import-{_timestamp()}.zip"
    with tempfile.TemporaryDirectory(prefix="novaguard-pre-import-") as temp_dir:
        db_snapshot = Path(temp_dir) / "novaguard.sqlite3"
        if db_path.exists():
            source = sqlite3.connect(db_path)
            target = sqlite3.connect(db_snapshot)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
        with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            if db_snapshot.exists():
                archive.write(db_snapshot, "data/novaguard.sqlite3")
            for relative, path in candidates:
                archive.write(path, relative)
    os.chmod(backup_path, 0o600)
    return backup_path


def import_host_sql(
    sql_path: str | Path,
    *,
    confirm_replace: bool = False,
    base_dir: str | Path = BASE_DIR,
    db_path: str | Path = DB_PATH,
) -> dict:
    """Validate and atomically install a portable host migration."""
    if not confirm_replace:
        raise HostMigrationError("Import refused without --confirm-replace")

    sql_path = Path(sql_path)
    base_dir = Path(base_dir)
    db_path = Path(db_path)
    if not sql_path.is_file():
        raise HostMigrationError(f"Migration file does not exist: {sql_path}")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    staging_db = db_path.with_name(f".{db_path.name}.host-import.tmp")
    if staging_db.exists():
        staging_db.unlink()
    try:
        info, files = _load_and_validate(sql_path, staging_db)
        connection = sqlite3.connect(staging_db)
        try:
            connection.execute(f'DROP TABLE "{FILES_TABLE}"')
            connection.execute(f'DROP TABLE "{MARKER_TABLE}"')
            connection.commit()
            _integrity(connection)
        finally:
            connection.close()

        safety_backup = _create_pre_import_backup(base_dir, db_path)
        for suffix in ("-wal", "-shm"):
            journal = Path(f"{db_path}{suffix}")
            if journal.exists():
                journal.unlink()
        os.chmod(staging_db, 0o600)
        os.replace(staging_db, db_path)

        for relative, content in files:
            target = _safe_auxiliary_target(base_dir, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.host-import.tmp")
            temporary.write_text(content, encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)

        return {
            **info,
            "path": str(sql_path),
            "database": str(db_path),
            "safety_backup": str(safety_backup) if safety_backup else None,
            "ok": True,
        }
    finally:
        if staging_db.exists():
            staging_db.unlink()
