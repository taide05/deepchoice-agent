from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime

import pytest

from deepchoice.operations.runtime_databases import (
    RuntimeDatabaseOperationError,
    create_paired_backup,
    exercise_restore,
    restore_paired_backup,
    verify_paired_backup,
)


NOW = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)


def _database(path, statement, value):
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(statement)
        connection.execute("INSERT INTO sample(value) VALUES (?)", (value,))
        connection.commit()


def _value(path):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute("SELECT value FROM sample").fetchone()[0]


def test_backup_verify_restore_and_drill_are_paired_and_recoverable(tmp_path):
    product = tmp_path / "live" / "product.db"
    checkpoint = tmp_path / "live" / "checkpoints.db"
    product.parent.mkdir()
    _database(product, "CREATE TABLE sample(value TEXT)", "product-original")
    _database(checkpoint, "CREATE TABLE sample(value TEXT)", "checkpoint-original")

    backup = create_paired_backup(
        product,
        checkpoint,
        tmp_path / "backup",
        maintenance_confirmed=True,
        now=NOW,
    )
    manifest = verify_paired_backup(backup)
    assert manifest["created_at"] == NOW.isoformat()
    assert set(manifest["databases"]) == {"product", "checkpoint"}

    product.unlink()
    checkpoint.unlink()
    restored = restore_paired_backup(
        backup,
        product,
        checkpoint,
        maintenance_confirmed=True,
        now=NOW,
    )
    assert _value(restored.product) == "product-original"
    assert _value(restored.checkpoint) == "checkpoint-original"

    drill = exercise_restore(backup, tmp_path / "drill")
    assert _value(drill.product) == "product-original"
    assert json.loads((drill.product.parent / "restore-drill.json").read_text())["status"] == "passed"


def test_maintenance_confirmation_and_overwrite_are_explicit(tmp_path):
    product = tmp_path / "product.db"
    checkpoint = tmp_path / "checkpoints.db"
    _database(product, "CREATE TABLE sample(value TEXT)", "p")
    _database(checkpoint, "CREATE TABLE sample(value TEXT)", "c")

    with pytest.raises(RuntimeDatabaseOperationError, match="maintenance"):
        create_paired_backup(product, checkpoint, tmp_path / "backup", maintenance_confirmed=False)
    backup = create_paired_backup(
        product, checkpoint, tmp_path / "backup", maintenance_confirmed=True, now=NOW
    )
    product_wal = product.with_name(product.name + "-wal")
    checkpoint_shm = checkpoint.with_name(checkpoint.name + "-shm")
    product_wal.write_bytes(b"old product wal")
    checkpoint_shm.write_bytes(b"old checkpoint shm")
    with pytest.raises(RuntimeDatabaseOperationError, match="target exists"):
        restore_paired_backup(
            backup, product, checkpoint, maintenance_confirmed=True, now=NOW
        )

    restored = restore_paired_backup(
        backup,
        product,
        checkpoint,
        maintenance_confirmed=True,
        replace=True,
        now=NOW,
    )
    assert _value(restored.product) == "p"
    assert (product.parent / "product.db.pre-restore-20260914T090000Z.bak").exists()
    assert (checkpoint.parent / "checkpoints.db.pre-restore-20260914T090000Z.bak").exists()
    assert not product_wal.exists()
    assert not checkpoint_shm.exists()
    assert (product.parent / "product.db-wal.pre-restore-20260914T090000Z.bak").read_bytes() == b"old product wal"
    assert (checkpoint.parent / "checkpoints.db-shm.pre-restore-20260914T090000Z.bak").read_bytes() == b"old checkpoint shm"


def test_verification_rejects_tampered_pair(tmp_path):
    product = tmp_path / "product.db"
    checkpoint = tmp_path / "checkpoints.db"
    _database(product, "CREATE TABLE sample(value TEXT)", "p")
    _database(checkpoint, "CREATE TABLE sample(value TEXT)", "c")
    backup = create_paired_backup(
        product, checkpoint, tmp_path / "backup", maintenance_confirmed=True
    )
    with (backup / "product.db").open("ab") as stream:
        stream.write(b"tampered")

    with pytest.raises(RuntimeDatabaseOperationError, match="checksum mismatch"):
        verify_paired_backup(backup)


def test_failed_second_install_restores_main_databases_and_sidecars(tmp_path, monkeypatch):
    product = tmp_path / "product.db"
    checkpoint = tmp_path / "checkpoints.db"
    _database(product, "CREATE TABLE sample(value TEXT)", "old-product")
    _database(checkpoint, "CREATE TABLE sample(value TEXT)", "old-checkpoint")
    (tmp_path / "product.db-wal").write_bytes(b"product-sidecar")
    (tmp_path / "checkpoints.db-shm").write_bytes(b"checkpoint-sidecar")

    source_product = tmp_path / "source-product.db"
    source_checkpoint = tmp_path / "source-checkpoints.db"
    _database(source_product, "CREATE TABLE sample(value TEXT)", "new-product")
    _database(source_checkpoint, "CREATE TABLE sample(value TEXT)", "new-checkpoint")
    backup = create_paired_backup(
        source_product,
        source_checkpoint,
        tmp_path / "backup",
        maintenance_confirmed=True,
        now=NOW,
    )
    original_replace = __import__("os").replace
    failed = False

    def fail_checkpoint_install(source, destination):
        nonlocal failed
        if not failed and str(source).endswith(".checkpoints.db.20260914T090000Z.restore-tmp"):
            failed = True
            raise OSError("injected second install failure")
        return original_replace(source, destination)

    monkeypatch.setattr("deepchoice.operations.runtime_databases.os.replace", fail_checkpoint_install)
    with pytest.raises(RuntimeDatabaseOperationError, match="paired restore failed"):
        restore_paired_backup(
            backup,
            product,
            checkpoint,
            maintenance_confirmed=True,
            replace=True,
            now=NOW,
        )

    assert (tmp_path / "product.db-wal").read_bytes() == b"product-sidecar"
    assert (tmp_path / "checkpoints.db-shm").read_bytes() == b"checkpoint-sidecar"
    assert _value(product) == "old-product"
    assert _value(checkpoint) == "old-checkpoint"


def test_incomplete_rollback_is_reported_and_safety_file_is_retained(tmp_path, monkeypatch):
    product = tmp_path / "product.db"
    checkpoint = tmp_path / "checkpoints.db"
    _database(product, "CREATE TABLE sample(value TEXT)", "old-product")
    _database(checkpoint, "CREATE TABLE sample(value TEXT)", "old-checkpoint")
    new_product = tmp_path / "new-product.db"
    new_checkpoint = tmp_path / "new-checkpoint.db"
    _database(new_product, "CREATE TABLE sample(value TEXT)", "new-product")
    _database(new_checkpoint, "CREATE TABLE sample(value TEXT)", "new-checkpoint")
    backup = create_paired_backup(
        new_product, new_checkpoint, tmp_path / "backup",
        maintenance_confirmed=True, now=NOW,
    )
    original_replace = __import__("os").replace

    def fail_install_and_product_rollback(source, destination):
        source_text = str(source)
        if source_text.endswith(".checkpoints.db.20260914T090000Z.restore-tmp"):
            raise OSError("injected install failure")
        if "product.db.pre-restore" in source_text and destination == product:
            raise OSError("injected rollback failure")
        return original_replace(source, destination)

    monkeypatch.setattr(
        "deepchoice.operations.runtime_databases.os.replace",
        fail_install_and_product_rollback,
    )
    with pytest.raises(RuntimeDatabaseOperationError, match="rollback is incomplete"):
        restore_paired_backup(
            backup, product, checkpoint, maintenance_confirmed=True,
            replace=True, now=NOW,
        )
    assert (tmp_path / "product.db.pre-restore-20260914T090000Z.bak").exists()
