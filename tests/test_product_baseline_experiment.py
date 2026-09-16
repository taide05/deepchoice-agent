from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from benchmarks.product_baseline_experiment import copy_knowledge, tree_hash, serve


def make_knowledge(root: Path):
    chroma = root / "source"
    chroma.mkdir()
    with sqlite3.connect(chroma / "chroma.sqlite3") as connection:
        connection.execute("CREATE TABLE fixture(value TEXT)")
        connection.execute("INSERT INTO fixture VALUES ('seed')")
    learned = root / "learned.json"
    learned.write_text('{"fixture":"https://example.com/docs"}')
    return chroma, learned


def test_snapshot_copy_is_identical_and_source_is_unchanged(tmp_path):
    chroma, learned = make_knowledge(tmp_path)
    before = tree_hash(chroma)
    identity = copy_knowledge(chroma, learned, tmp_path / "snapshot")
    assert identity == tree_hash(tmp_path / "snapshot")
    assert tree_hash(chroma) == before
    assert (tmp_path / "snapshot" / "learned_docs.json").read_bytes() == learned.read_bytes()
    with sqlite3.connect(tmp_path / "snapshot" / "chroma" / "chroma.sqlite3") as connection:
        assert connection.execute("SELECT value FROM fixture").fetchone() == ("seed",)
    with pytest.raises(ValueError, match="fresh"):
        copy_knowledge(chroma, learned, tmp_path / "snapshot")


def test_snapshot_rejects_pending_wal_without_modifying_source(tmp_path):
    chroma, learned = make_knowledge(tmp_path)
    (chroma / "chroma.sqlite3-wal").write_bytes(b"pending")
    with pytest.raises(ValueError, match="pending WAL"):
        copy_knowledge(chroma, learned, tmp_path / "snapshot")
    assert not (tmp_path / "snapshot").exists()


def test_serve_rejects_non_allowlisted_settings_before_native_import(tmp_path):
    (tmp_path / "environment.json").write_text(json.dumps({"notes": {"settings": {"SECRET_KEY": "test"}}}))
    with pytest.raises(ValueError, match="allowlist"):
        serve(tmp_path, "serial-r1", 8011)
