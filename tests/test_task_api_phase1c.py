"""API/lifespan contracts for the queue-only task surface."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from deepchoice.server import app as app_module


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
