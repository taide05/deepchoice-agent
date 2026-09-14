"""API/lifespan contracts for the queue-only task surface."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from deepchoice.server import app as app_module
from deepchoice.runtime.lifecycle import RunStatus, TaskStatus


@pytest.fixture(autouse=True)
def isolate_execution_state(tmp_path: Path):
    state = app_module.app.state
    missing = object()
    old = {
        "execution_enabled": getattr(state, "execution_enabled", missing),
        "checkpoint_database_path": getattr(state, "checkpoint_database_path", missing),
        "product_database_path": getattr(state, "product_database_path", missing),
        "legacy_snapshot_root": getattr(state, "legacy_snapshot_root", missing),
    }
    state.execution_enabled = False
    state.checkpoint_database_path = tmp_path / "checkpoints.db"
    state.legacy_snapshot_root = tmp_path / "legacy-snapshots"
    try:
        yield
    finally:
        for name, value in old.items():
            if value is missing:
                delattr(state, name)
            else:
                setattr(state, name, value)


def _payload(query: str = "compare FastAPI and Flask") -> dict[str, object]:
    return {"query": query}


def test_task_api_persists_queue_without_starting_research(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "product.db"
    app_module.app.state.product_database_path = path
    called = False

    async def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("queue API must not start research")

    monkeypatch.setattr(app_module, "_run_research", fail_if_called)
    with TestClient(app_module.app) as client:
        response = client.post("/api/v1/tasks", json=_payload())
        assert response.status_code == 202
        body = response.json()
        assert body["task"]["status"] == "queued"
        assert body["latest_run"]["status"] == "queued"
        assert body["latest_run"]["manifest_id"]
        assert "manifest" not in body["latest_run"]
        assert "thread_id" not in body["latest_run"]
        assert "checkpoint_ns" not in body["latest_run"]
        assert "lease_owner" not in body["latest_run"]
        task_id = body["task"]["task_id"]
        assert client.get(f"/api/v1/tasks/{task_id}").status_code == 200
        listed = client.get("/api/v1/tasks", params={"limit": 1})
        assert listed.status_code == 200
        assert listed.json()["items"][0]["task"]["task_id"] == task_id
    assert called is False

    app_module.app.state.product_database_path = path
    with TestClient(app_module.app) as client:
        assert client.get(f"/api/v1/tasks/{task_id}").status_code == 200


def test_task_api_structured_not_found_and_validation_errors(tmp_path: Path) -> None:
    app_module.app.state.product_database_path = tmp_path / "product.db"
    with TestClient(app_module.app) as client:
        missing = client.get("/api/v1/tasks/missing")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "TASK_NOT_FOUND"

        bad_cursor = client.get("/api/v1/tasks", params={"cursor": "not-a-cursor"})
        assert bad_cursor.status_code == 422
        assert bad_cursor.json()["error"]["code"] == "INVALID_TASK_CURSOR"

        for limit in (0, 101):
            bad_limit = client.get("/api/v1/tasks", params={"limit": limit})
            assert bad_limit.status_code == 422
            assert bad_limit.json()["error"]["code"] == "REQUEST_VALIDATION_FAILED"


def test_task_list_status_filter_and_cursor_are_stable(tmp_path: Path) -> None:
    app_module.app.state.product_database_path = tmp_path / "product.db"
    with TestClient(app_module.app) as client:
        ids = []
        for query in ("one", "two", "three"):
            response = client.post("/api/v1/tasks", json=_payload(query))
            assert response.status_code == 202
            ids.append(response.json()["task"]["task_id"])
        first = client.get("/api/v1/tasks", params={"limit": 2}).json()
        assert len(first["items"]) == 2
        assert first["next_cursor"]
        second = client.get("/api/v1/tasks", params={
            "limit": 2, "cursor": first["next_cursor"], "status": "queued"
        }).json()
        first_ids = {item["task"]["task_id"] for item in first["items"]}
        second_ids = {item["task"]["task_id"] for item in second["items"]}
        assert first_ids.isdisjoint(second_ids)
        assert first_ids | second_ids == set(ids)


def test_cancel_queued_is_idempotent_and_public_run_hides_fencing_fields(tmp_path: Path) -> None:
    app_module.app.state.product_database_path = tmp_path / "product.db"
    with TestClient(app_module.app) as client:
        created = client.post("/api/v1/tasks", json=_payload()).json()
        task_id = created["task"]["task_id"]
        first = client.post(f"/api/v1/tasks/{task_id}/cancel")
        assert first.status_code == 200
        assert first.json()["task"]["status"] == "cancelled"
        second = client.post(f"/api/v1/tasks/{task_id}/cancel")
        assert second.status_code == 200
        body = second.json()
        assert body["latest_run"]["status"] == "cancelled"
        assert "deadline_at" in body["latest_run"]
        for forbidden in ("lease_owner", "execution_epoch", "checkpoint_id", "checkpoint_ns"):
            assert forbidden not in body["latest_run"]


def test_resume_requires_strong_if_match_and_rejects_stale_version(tmp_path: Path) -> None:
    app_module.app.state.product_database_path = tmp_path / "product.db"
    with TestClient(app_module.app) as client:
        created = client.post("/api/v1/tasks", json=_payload()).json()
        task_id = created["task"]["task_id"]
        missing = client.post(f"/api/v1/tasks/{task_id}/resume")
        assert missing.status_code == 428
        assert missing.json()["error"]["code"] == "TASK_VERSION_REQUIRED"
        for value in ("W/\"0\"", "bogus", "9" * 30):
            invalid = client.post(f"/api/v1/tasks/{task_id}/resume", headers={"If-Match": value})
            assert invalid.status_code == 422
            assert invalid.json()["error"]["code"] == "INVALID_TASK_VERSION"
        stale = client.post(f"/api/v1/tasks/{task_id}/resume", headers={"If-Match": '"99"'})
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] in {"TASK_VERSION_CONFLICT", "TASK_STATUS_TRANSITION_NOT_ALLOWED"}


def test_create_submits_to_lifespan_coordinator_without_running_provider(
    tmp_path: Path, monkeypatch
) -> None:
    submitted: list[tuple[str, bool | None]] = []

    class FakeCoordinator:
        def __init__(self, _repository, _checkpointer, *, enabled=True):
            self.enabled = enabled

        async def start(self):
            return ()

        async def stop(self):
            return None

        async def submit(self, run_id: str, *, resume: bool | None = None):
            submitted.append((run_id, resume))
            return True

    monkeypatch.setattr(app_module, "RunCoordinator", FakeCoordinator)
    app_module.app.state.execution_enabled = True
    app_module.app.state.product_database_path = tmp_path / "product.db"
    with TestClient(app_module.app) as client:
        response = client.post("/api/v1/tasks", json=_payload())
        assert response.status_code == 202
        run_id = response.json()["latest_run"]["run_id"]
        assert submitted == [(run_id, False)]


def test_resume_returns_accepted_when_post_commit_wakeup_fails(
    tmp_path: Path, monkeypatch
) -> None:
    class FakeCoordinator:
        fail = False

        def __init__(self, _repository, _checkpointer, *, enabled=True):
            self.enabled = enabled

        async def start(self):
            return ()

        async def stop(self):
            return None

        async def submit(self, _run_id: str, *, resume: bool | None = None):
            if self.fail:
                raise RuntimeError("transient wake-up failure")
            return True

    monkeypatch.setattr(app_module, "RunCoordinator", FakeCoordinator)
    app_module.app.state.execution_enabled = True
    app_module.app.state.product_database_path = tmp_path / "product.db"
    with TestClient(app_module.app) as client:
        created = client.post("/api/v1/tasks", json=_payload()).json()
        task_id = created["task"]["task_id"]
        repository = app_module.app.state.task_repository

        async def interrupt_queued_run():
            running = await repository.transition_current_run(
                task_id,
                expected_task_version=0,
                target_task_status=TaskStatus.RUNNING,
                target_run_status=RunStatus.RUNNING,
            )
            return await repository.transition_current_run(
                task_id,
                expected_task_version=running.task.version,
                target_task_status=TaskStatus.INTERRUPTED,
                target_run_status=RunStatus.INTERRUPTED,
            )

        interrupted = client.portal.call(interrupt_queued_run)
        app_module.app.state.run_coordinator.fail = True
        response = client.post(
            f"/api/v1/tasks/{task_id}/resume",
            headers={"If-Match": str(interrupted.task.version)},
        )

        assert response.status_code == 202
        body = response.json()
        assert body["task"]["status"] == "queued"
        assert body["task"]["version"] == interrupted.task.version + 1
        events = client.portal.call(repository.list_task_events, task_id)
        assert events[-1].type == "run.retry_queued"
        assert events[-1].run_id == body["latest_run"]["run_id"]
