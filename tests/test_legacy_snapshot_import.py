import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio

from deepchoice.server.legacy_import import import_legacy_snapshots
from deepchoice.persistence import connect_database, run_migrations
from deepchoice.persistence.repository import SQLiteTaskRunRepository


NOW = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)


class FakeRepository:
    def __init__(self):
        self.imports = []
        self.failures = []
        self.by_source = {}

    async def import_legacy_task(self, source_path, content_sha256, task, run, *, imported_at=None):
        source_digest = content_sha256
        now = imported_at
        previous = self.by_source.get(source_path)
        if previous == source_digest:
            return False
        if previous is not None:
            raise ValueError("source conflict")
        if task.task_id in {item[0].task_id for item in self.imports}:
            raise ValueError("task conflict")
        self.by_source[source_path] = source_digest
        self.imports.append((task, run, source_path, source_digest, now))
        return True

    async def record_legacy_import_failure(self, path, digest, error_code, *, imported_at=None):
        now = imported_at
        self.failures.append((path, digest, error_code, now))


def _snapshot(query="compare FastAPI and Flask"):
    return {"task": {"query": query, "report_format": "what_why_how"}, "report": "secret"}


def _write(root: Path, task_id: str, name: str, value):
    directory = root / task_id
    directory.mkdir(exist_ok=True)
    path = directory / name
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(json.dumps(value), encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_imports_success_and_failed_snapshots(tmp_path):
    _write(tmp_path, "success-1", "research_snapshot.json", _snapshot())
    _write(tmp_path, "failed-1", "research_snapshot_failed.json", _snapshot("bad input"))
    repo = FakeRepository()

    summary = await import_legacy_snapshots(tmp_path, repo, clock=lambda: NOW)

    assert summary == summary.__class__(scanned=2, imported=2, skipped=0, errors=0)
    assert {item[0].status.value for item in repo.imports} == {"completed", "failed"}
    failed = next(item for item in repo.imports if item[1].status.value == "failed")
    assert failed[1].error_id == "LEGACY_SNAPSHOT_FAILED"
    assert all(item[0].created_at.tzinfo is not None for item in repo.imports)


@pytest.mark.asyncio
async def test_success_file_wins_and_repeated_import_is_noop(tmp_path):
    directory = tmp_path / "task-1"
    directory.mkdir()
    _write(tmp_path, "task-1", "research_snapshot.json", _snapshot("success"))
    (directory / "research_snapshot_failed.json").write_text(
        json.dumps(_snapshot("failed")), encoding="utf-8"
    )
    repo = FakeRepository()

    first = await import_legacy_snapshots(tmp_path, repo, clock=lambda: NOW)
    second = await import_legacy_snapshots(tmp_path, repo, clock=lambda: NOW)

    assert first.imported == 1
    assert second.skipped == 1
    assert len(repo.imports) == 1
    assert repo.imports[0][0].request.query == "success"


@pytest.mark.asyncio
async def test_invalid_files_are_isolated_and_errors_are_safe(tmp_path):
    path = _write(tmp_path, "bad-json", "research_snapshot.json", b'{"task":')
    _write(tmp_path, "bad-request", "research_snapshot.json", {"task": {"query": ""}})
    _write(tmp_path, "good", "research_snapshot.json", _snapshot("good"))
    repo = FakeRepository()

    summary = await import_legacy_snapshots(tmp_path, repo, clock=lambda: NOW)

    assert summary.scanned == 3
    assert summary.imported == 1
    assert summary.errors == 2
    assert len(repo.failures) == 2
    expected_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert any(item[1] == expected_digest for item in repo.failures)
    assert all("task" not in item[2] for item in repo.failures)
    assert all("secret" not in item[2] for item in repo.failures)


@pytest.mark.asyncio
async def test_oversized_snapshot_is_hashed_but_not_parsed(tmp_path):
    path = _write(
        tmp_path,
        "too-large",
        "research_snapshot.json",
        _snapshot("a query longer than the test import limit"),
    )
    repo = FakeRepository()

    summary = await import_legacy_snapshots(
        tmp_path,
        repo,
        clock=lambda: NOW,
        max_snapshot_bytes=16,
    )

    assert summary == summary.__class__(scanned=1, imported=0, skipped=0, errors=1)
    assert repo.imports == []
    assert repo.failures == [
        (
            "too-large/research_snapshot.json",
            hashlib.sha256(path.read_bytes()).hexdigest(),
            "LEGACY_SNAPSHOT_TOO_LARGE",
            datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
        )
    ]


@pytest.mark.asyncio
async def test_unreadable_snapshot_root_isolated_from_startup(tmp_path, monkeypatch):
    original_iterdir = Path.iterdir

    def fail_for_root(path: Path):
        if path == tmp_path:
            raise OSError("not readable")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", fail_for_root)
    summary = await import_legacy_snapshots(tmp_path, FakeRepository(), clock=lambda: NOW)
    assert summary == summary.__class__(scanned=0, imported=0, skipped=0, errors=1)


@pytest.mark.asyncio
async def test_changed_content_does_not_overwrite_existing_source(tmp_path):
    path = _write(tmp_path, "task-1", "research_snapshot.json", _snapshot("first"))
    repo = FakeRepository()
    await import_legacy_snapshots(tmp_path, repo, clock=lambda: NOW)
    path.write_text(json.dumps(_snapshot("changed")), encoding="utf-8")

    summary = await import_legacy_snapshots(tmp_path, repo, clock=lambda: NOW)

    assert summary.errors == 1
    assert len(repo.imports) == 1
    assert repo.imports[0][0].request.query == "first"


@pytest_asyncio.fixture
async def sqlite_repository(tmp_path):
    connection = await connect_database(tmp_path / "deepchoice.db")
    await run_migrations(connection)
    try:
        yield SQLiteTaskRunRepository(connection)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_real_sqlite_import_is_idempotent_and_detects_changed_source(
    tmp_path, sqlite_repository
):
    path = _write(tmp_path, "sqlite-task", "research_snapshot.json", _snapshot("first"))

    first = await import_legacy_snapshots(tmp_path, sqlite_repository, clock=lambda: NOW)
    second = await import_legacy_snapshots(tmp_path, sqlite_repository, clock=lambda: NOW)
    path.write_text(json.dumps(_snapshot("changed")), encoding="utf-8")
    third = await import_legacy_snapshots(tmp_path, sqlite_repository, clock=lambda: NOW)

    assert first.imported == 1 and first.errors == 0
    assert second.skipped == 1 and second.imported == 0
    assert third.errors == 1 and third.imported == 0
    loaded = await sqlite_repository.get_task("sqlite-task")
    assert loaded is not None
    assert loaded.task.request.query == "first"
