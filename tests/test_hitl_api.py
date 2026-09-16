from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from deepchoice.hitl import DecisionPause
from deepchoice.persistence.records import CheckpointReference
from deepchoice.server import app as app_module


@pytest.fixture(autouse=True)
def isolate_app_state(tmp_path: Path):
    state = app_module.app.state
    missing = object()
    names = (
        "execution_enabled",
        "checkpoint_database_path",
        "product_database_path",
        "legacy_snapshot_root",
    )
    old = {name: getattr(state, name, missing) for name in names}
    state.execution_enabled = False
    state.checkpoint_database_path = tmp_path / "checkpoints.db"
    state.product_database_path = tmp_path / "product.db"
    state.legacy_snapshot_root = tmp_path / "legacy"
    try:
        yield
    finally:
        for name, value in old.items():
            if value is missing:
                delattr(state, name)
            else:
                setattr(state, name, value)


def test_decision_api_is_public_bounded_idempotent_and_recoverable():
    with TestClient(app_module.app) as client:
        created = client.post(
            "/api/v1/tasks", json={"query": "compare FastAPI and Flask"}
        ).json()
        task_id = created["task"]["task_id"]
        run_id = created["latest_run"]["run_id"]
        missing = client.get(f"/api/v1/tasks/{task_id}/decision")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "TASK_DECISION_NOT_FOUND"

        repository = app_module.app.state.task_repository
        now = datetime.now(UTC)

        async def pause():
            run = await repository.get_run(run_id)
            grant = await repository.acquire_run_lease(
                run_id,
                lease_owner="worker",
                lease_ttl=timedelta(minutes=1),
                run_timeout=timedelta(minutes=30),
                now=now,
            )
            reference = CheckpointReference(
                run_id=run_id,
                storage_checkpoint_ns="deepchoice-execution-1",
                checkpoint_id="decision-checkpoint",
                state_schema_version=run.manifest.state_schema_version,
                execution_epoch=grant.execution_epoch,
                created_at=now + timedelta(seconds=1),
            )
            await repository.add_checkpoint_reference(
                reference,
                lease_owner="worker",
                execution_epoch=grant.execution_epoch,
                now=now + timedelta(seconds=1),
            )
            return await repository.pause_for_decision(
                DecisionPause(
                    decision_id="decision-api",
                    reason="Evidence is structurally insufficient.",
                    gaps=("Missing independent evidence.",),
                ),
                reference,
                lease_owner="worker",
                execution_epoch=grant.execution_epoch,
                now=now + timedelta(seconds=2),
            )

        decision = client.portal.call(pause)
        fetched = client.get(f"/api/v1/tasks/{task_id}/decision")
        assert fetched.status_code == 200
        encoded = fetched.text.lower()
        assert "checkpoint" not in encoded
        assert "epoch" not in encoded
        assert fetched.json()["status"] == "pending"
        assert fetched.json()["allowed_actions"] == [
            "provide_context", "limited_report", "cancel"
        ]

        bypass = client.post(
            f"/api/v1/tasks/{task_id}/resume", headers={"If-Match": "2"}
        )
        assert bypass.status_code == 409
        assert bypass.json()["error"]["code"] == "TASK_DECISION_REQUIRED"

        for payload in (
            {"action": "provide_context"},
            {"action": "limited_report", "supplemental_input": "not allowed"},
            {"action": "cancel", "extra": True},
        ):
            invalid = client.post(
                f"/api/v1/tasks/{task_id}/decisions/{decision.decision_id}",
                headers={"If-Match": "2"},
                json=payload,
            )
            assert invalid.status_code == 422

        resolved = client.post(
            f"/api/v1/tasks/{task_id}/decisions/{decision.decision_id}",
            headers={"If-Match": "2"},
            json={"action": "limited_report"},
        )
        assert resolved.status_code == 202
        assert resolved.json()["task"]["task"]["status"] == "queued"
        assert resolved.json()["decision"]["decision_id"] == decision.decision_id
        assert resolved.json()["decision"]["status"] == "resolved"
        assert resolved.json()["decision"]["resolved_action"] == "limited_report"
        assert "checkpoint" not in resolved.text.lower()
        replay = client.post(
            f"/api/v1/tasks/{task_id}/decisions/{decision.decision_id}",
            headers={"If-Match": "0"},
            json={"action": "limited_report"},
        )
        assert replay.status_code == 202
        assert replay.json()["replayed"] is True
        recovered = client.portal.call(
            lambda: repository.recover_runs(now=now + timedelta(minutes=2))
        )
        assert len(recovered) == 1
        assert recovered[0].run_id == run_id
        assert recovered[0].resume is True


def test_legacy_research_route_does_not_expose_decision_api_behavior(monkeypatch):
    class LegacyOrchestrator:
        task_id = "legacy-task"

        async def astream_research_task(self):
            yield {"report_generator": {"report": "# legacy"}}

        async def get_state(self):
            class State:
                values = {"report": "# legacy", "current_phase": "self_reviewer"}
            return State()

    monkeypatch.setattr(app_module, "ChiefEditorAgent", lambda *_args, **_kwargs: LegacyOrchestrator())
    with TestClient(app_module.app) as client:
        response = client.post("/research", json={"query": "A vs B"})
        assert response.status_code in {200, 202}
        assert "decision" not in response.text.lower()
