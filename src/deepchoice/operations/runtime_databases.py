"""Paired backup, verification, restore, and restore-drill helpers.

The product and LangGraph checkpoint databases cannot be snapshotted atomically
as a pair.  Callers must stop the service or enter maintenance mode first and
explicitly confirm that fact.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


MANIFEST_NAME = "runtime-backup-manifest.json"
MANIFEST_VERSION = 1


class RuntimeDatabaseOperationError(RuntimeError):
    """A safe operational error without database contents."""


@dataclass(frozen=True, slots=True)
class RestoredPair:
    product: Path
    checkpoint: Path


def _require_maintenance(confirmed: bool) -> None:
    if confirmed is not True:
        raise RuntimeDatabaseOperationError(
            "stop the service or enter maintenance mode, then pass explicit confirmation"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _quick_check(path: Path) -> None:
    try:
        with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as connection:
            row = connection.execute("PRAGMA quick_check").fetchone()
    except sqlite3.Error as exc:
        raise RuntimeDatabaseOperationError(f"database verification failed: {path.name}") from exc
    if row != ("ok",):
        raise RuntimeDatabaseOperationError(f"database quick_check failed: {path.name}")


def _schema_version(path: Path) -> int | None:
    try:
        with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as connection:
            row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    except sqlite3.Error:
        return None
    return int(row[0]) if row and row[0] is not None else None


def _sqlite_backup(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise RuntimeDatabaseOperationError(f"database does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with closing(sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)) as source_db:
            with closing(sqlite3.connect(destination)) as destination_db:
                source_db.backup(destination_db)
    except sqlite3.Error as exc:
        raise RuntimeDatabaseOperationError(f"database backup failed: {source.name}") from exc
    _quick_check(destination)


def create_paired_backup(
    product_database: str | Path,
    checkpoint_database: str | Path,
    destination: str | Path,
    *,
    maintenance_confirmed: bool,
    now: datetime | None = None,
) -> Path:
    """Create a new, checksummed backup directory for both runtime databases."""

    _require_maintenance(maintenance_confirmed)
    product = Path(product_database).resolve()
    checkpoint = Path(checkpoint_database).resolve()
    target = Path(destination).resolve()
    if target.exists():
        raise RuntimeDatabaseOperationError("backup destination already exists")
    if product == checkpoint:
        raise RuntimeDatabaseOperationError("product and checkpoint databases must be distinct")

    target.mkdir(parents=True)
    try:
        product_copy = target / "product.db"
        checkpoint_copy = target / "checkpoints.db"
        _sqlite_backup(product, product_copy)
        _sqlite_backup(checkpoint, checkpoint_copy)
        created_at = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
        manifest: dict[str, Any] = {
            "manifest_version": MANIFEST_VERSION,
            "created_at": created_at,
            "consistency": "service-stopped-or-maintenance-confirmed",
            "databases": {
                "product": {
                    "file": product_copy.name,
                    "sha256": _sha256(product_copy),
                    "size_bytes": product_copy.stat().st_size,
                    "schema_version": _schema_version(product_copy),
                },
                "checkpoint": {
                    "file": checkpoint_copy.name,
                    "sha256": _sha256(checkpoint_copy),
                    "size_bytes": checkpoint_copy.stat().st_size,
                },
            },
        }
        (target / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return target
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise


def verify_paired_backup(backup_directory: str | Path) -> dict[str, Any]:
    """Validate the manifest, hashes, sizes, and SQLite integrity of a pair."""

    root = Path(backup_directory).resolve()
    try:
        manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeDatabaseOperationError("backup manifest is missing or invalid") from exc
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise RuntimeDatabaseOperationError("unsupported backup manifest version")
    databases = manifest.get("databases")
    if not isinstance(databases, dict) or set(databases) != {"product", "checkpoint"}:
        raise RuntimeDatabaseOperationError("backup manifest does not describe an exact pair")
    for name in ("product", "checkpoint"):
        item = databases.get(name)
        if not isinstance(item, dict) or set(item) < {"file", "sha256", "size_bytes"}:
            raise RuntimeDatabaseOperationError(f"invalid {name} backup metadata")
        candidate = (root / str(item["file"])).resolve()
        if candidate.parent != root or not candidate.is_file():
            raise RuntimeDatabaseOperationError(f"invalid {name} backup path")
        if candidate.stat().st_size != item["size_bytes"] or _sha256(candidate) != item["sha256"]:
            raise RuntimeDatabaseOperationError(f"{name} backup checksum mismatch")
        _quick_check(candidate)
    return manifest


def _unique_safety_path(target: Path, timestamp: str) -> Path:
    candidate = target.with_name(f"{target.name}.pre-restore-{timestamp}.bak")
    if candidate.exists():
        raise RuntimeDatabaseOperationError(f"safety backup already exists: {candidate.name}")
    return candidate


def _database_family(target: Path) -> tuple[Path, Path, Path]:
    return target, Path(f"{target}-wal"), Path(f"{target}-shm")


def restore_paired_backup(
    backup_directory: str | Path,
    product_database: str | Path,
    checkpoint_database: str | Path,
    *,
    maintenance_confirmed: bool,
    replace: bool = False,
    now: datetime | None = None,
) -> RestoredPair:
    """Restore a verified pair, retaining existing targets as safety backups."""

    _require_maintenance(maintenance_confirmed)
    manifest = verify_paired_backup(backup_directory)
    root = Path(backup_directory).resolve()
    product = Path(product_database).resolve()
    checkpoint = Path(checkpoint_database).resolve()
    if product == checkpoint:
        raise RuntimeDatabaseOperationError("product and checkpoint targets must be distinct")
    if root in product.parents or root in checkpoint.parents:
        raise RuntimeDatabaseOperationError("restore targets must be outside the backup directory")
    existing = [
        path
        for target in (product, checkpoint)
        for path in _database_family(target)
        if path.exists()
    ]
    if existing and not replace:
        raise RuntimeDatabaseOperationError("restore target exists; use explicit replace mode")

    for target in (product, checkpoint):
        target.parent.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    safety = {path: _unique_safety_path(path, stamp) for path in existing}
    temporary = {
        product: product.with_name(f".{product.name}.{stamp}.restore-tmp"),
        checkpoint: checkpoint.with_name(f".{checkpoint.name}.{stamp}.restore-tmp"),
    }
    if any(path.exists() for path in temporary.values()):
        raise RuntimeDatabaseOperationError("restore temporary path already exists")

    sources = {
        product: root / manifest["databases"]["product"]["file"],
        checkpoint: root / manifest["databases"]["checkpoint"]["file"],
    }
    moved: list[Path] = []
    installed: list[Path] = []
    try:
        for target, source in sources.items():
            shutil.copy2(source, temporary[target])
            _quick_check(temporary[target])
        for target, retained in safety.items():
            os.replace(target, retained)
            moved.append(target)
        for target in (product, checkpoint):
            os.replace(temporary[target], target)
            installed.append(target)
        return RestoredPair(product=product, checkpoint=checkpoint)
    except Exception as exc:
        rollback_errors: list[str] = []
        for target in installed:
            try:
                target.unlink()
            except OSError:
                rollback_errors.append(target.name)
        for target in reversed(moved):
            try:
                os.replace(safety[target], target)
            except OSError:
                rollback_errors.append(target.name)
        if rollback_errors:
            retained = sorted(
                path.name for path in safety.values() if path.exists()
            )
            retained_text = ", ".join(retained) if retained else "none detected"
            raise RuntimeDatabaseOperationError(
                "paired restore failed and rollback is incomplete; "
                f"safety files retained: {retained_text}"
            ) from exc
        if isinstance(exc, RuntimeDatabaseOperationError):
            raise
        raise RuntimeDatabaseOperationError("paired restore failed; retained files were restored") from exc
    finally:
        for path in temporary.values():
            try:
                path.unlink()
            except OSError:
                pass


def exercise_restore(
    backup_directory: str | Path,
    drill_directory: str | Path,
) -> RestoredPair:
    """Restore into a new directory and verify both databases without touching production."""

    drill = Path(drill_directory).resolve()
    if drill.exists():
        raise RuntimeDatabaseOperationError("restore drill directory already exists")
    drill.mkdir(parents=True)
    try:
        pair = restore_paired_backup(
            backup_directory,
            drill / "product.db",
            drill / "checkpoints.db",
            maintenance_confirmed=True,
        )
        verify_paired_backup(backup_directory)
        _quick_check(pair.product)
        _quick_check(pair.checkpoint)
        (drill / "restore-drill.json").write_text(
            json.dumps(
                {
                    "completed_at": datetime.now(UTC).isoformat(),
                    "product_schema_version": _schema_version(pair.product),
                    "status": "passed",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return pair
    except Exception:
        shutil.rmtree(drill, ignore_errors=True)
        raise
