"""Public budget-summary aggregation and privacy contract tests."""

from __future__ import annotations

import json
from functools import partial

import pytest
from fastapi.testclient import TestClient

from deepchoice.server import app as app_module


@pytest.fixture
def budget_client(tmp_path):
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
        with TestClient(app_module.app) as client:
            yield client
    finally:
        for name, value in old.items():
            if value is missing:
                delattr(state, name)
            else:
                setattr(state, name, value)


def _create(client) -> tuple[str, str]:
    response = client.post(
        "/api/v1/tasks", json={"query": "compare FastAPI and Flask"}
    )
    assert response.status_code == 202
    body = response.json()
    return body["task"]["task_id"], body["latest_run"]["run_id"]


async def _seed_budget(
    state,
    run_id: str,
    entries=(),
    *,
    total_limit: int = 200,
    marker: dict | None = None,
    failed_error_id: str | None = None,
) -> None:
    connection = state.product_database_connection
    policy = {
        "policy_schema_version": 1,
        "policy_version": "standard-enforced-v1",
        "tier": "standard",
        "enforcement_mode": "enforced",
        "soft_limit_ratio": 0.7,
        "hard_limits": {
            "total_tokens": total_limit,
            "llm_calls": 10,
            "cost_micro_usd": 100,
        },
        "price_catalog_version": "unpriced-v1",
    }
    async with state.product_database_lock:
        await connection.execute("DROP TRIGGER run_budget_policies_reject_update")
        await connection.execute(
            "UPDATE run_budget_policies SET policy_json = ? WHERE run_id = ?",
            (json.dumps(policy, separators=(",", ":")), run_id),
        )
        for identity, sequence, status, reserved, actual in entries:
            terminal = status != "reserved"
            await connection.execute(
                """
                INSERT INTO budget_ledger(
                    ledger_entry_id, run_id, execution_epoch, call_id,
                    reservation_id, entry_sequence, status, resource,
                    reserved_amount, actual_amount, price_status,
                    price_catalog_version, summary_json, created_at,
                    expires_at, settled_at
                ) VALUES (?, ?, 1, NULL, ?, ?, ?, 'total_tokens', ?, ?,
                          'not_applicable', 'unpriced-v1', '{}',
                          '2026-01-01T00:00:00Z', '2027-01-01T00:00:00Z', ?)
                """,
                (
                    f"private-ledger-{identity}-{sequence}",
                    run_id,
                    identity,
                    sequence,
                    status,
                    reserved,
                    actual,
                    "2026-01-02T00:00:00Z" if terminal else None,
                ),
            )
        if marker is not None:
            snapshot = {
                "budget_limited": marker,
                "report": "PRIVATE REPORT BODY MUST NOT BE EXPOSED",
                "private_extension": "PRIVATE SNAPSHOT FIELD MUST NOT BE EXPOSED",
            }
            await connection.execute(
                """
                INSERT INTO run_results(
                    run_id, result_schema_version, snapshot_json, report,
                    report_format, created_at
                ) VALUES (?, 1, ?, 'PRIVATE REPORT BODY MUST NOT BE EXPOSED',
                          'what_why_how', '2026-01-02T00:00:00Z')
                """,
                (run_id, json.dumps(snapshot, separators=(",", ":"))),
            )
        if failed_error_id is not None:
            await connection.execute(
                "UPDATE runs SET status = 'failed', error_id = ? WHERE run_id = ?",
                (failed_error_id, run_id),
            )
        await connection.commit()


def test_budget_summary_aggregates_only_latest_reservation_state_and_hides_ids(
    budget_client,
):
    task_id, run_id = _create(budget_client)
    state = app_module.app.state
    entries = (
        ("settled", 1, "reserved", 100, None),
        ("settled", 2, "settled", 100, 70),
        ("unknown", 1, "reserved", 50, None),
        ("unknown", 2, "unknown_spend", 50, 50),
        ("active", 1, "reserved", 30, None),
        ("released", 1, "reserved", 40, None),
        ("released", 2, "released", 40, None),
    )
    budget_client.portal.call(_seed_budget, state, run_id, entries)

    response = budget_client.get(f"/api/v1/tasks/{task_id}/observability")
    assert response.status_code == 200
    body = response.json()
    budget = body["budget"]
    assert budget["availability"] == "available"
    assert budget["policy_version"] == "standard-enforced-v1"
    assert budget["tier"] == "standard"
    assert budget["enforcement_mode"] == "enforced"
    assert budget["soft_limit_ratio"] == 0.7
    totals = budget["resources"]["total_tokens"]
    assert totals == {
        "availability": "available",
        "hard_limit": 200,
        "settled": 70,
        "unknown_spend": 50,
        "reserved": 30,
        "remaining": 50,
        "soft_limit_reached": True,
        "exhausted": False,
    }
    assert budget["resources"]["llm_calls"]["settled"] == 0
    assert budget["resources"]["llm_calls"]["remaining"] == 10
    cost = budget["resources"]["cost_micro_usd"]
    assert cost == {
        "availability": "unavailable",
        "hard_limit": None,
        "settled": None,
        "unknown_spend": None,
        "reserved": None,
        "remaining": None,
        "soft_limit_reached": None,
        "exhausted": None,
    }
    assert budget["price_availability"] == "unavailable"
    for private in ("reservation_id", "execution_epoch", "call_id", "private-ledger"):
        assert private not in response.text


def test_historical_budget_policy_and_cost_remain_unavailable(budget_client):
    task_id, run_id = _create(budget_client)
    connection = app_module.app.state.product_database_connection

    async def remove_policy():
        await connection.execute("DROP TRIGGER run_budget_policies_reject_delete")
        await connection.execute(
            "DELETE FROM run_budget_policies WHERE run_id = ?", (run_id,)
        )
        await connection.commit()

    budget_client.portal.call(remove_policy)
    response = budget_client.get(f"/api/v1/tasks/{task_id}/observability")
    assert response.status_code == 200
    body = response.json()
    assert body["budget_policy_availability"] == "unavailable"
    assert body["budget_policy_unavailable_reason"] == "historical_run"
    assert body["budget"] == {
        "availability": "unavailable",
        "policy_version": None,
        "tier": None,
        "enforcement_mode": None,
        "soft_limit_ratio": None,
        "admission_denied": False,
        "denied_resource": None,
        "price_availability": "unavailable",
        "resources": {},
    }


def test_denied_request_is_projected_without_claiming_ledger_exhaustion(
    budget_client,
):
    task_id, run_id = _create(budget_client)
    state = app_module.app.state
    # 58,000 tokens were already charged. A subsequent 8,000-token request
    # exceeds the 60,000 ceiling and is rejected before it creates a ledger row.
    budget_client.portal.call(
        partial(
            _seed_budget,
            state,
            run_id,
            (("prior-usage", 1, "settled", 58_000, 58_000),),
            total_limit=60_000,
            marker={
                "limited": True,
                "policy_version": "standard-enforced-v1",
                "exhausted_resource": "total_tokens",
                "minimum_evidence_met": True,
                "reason": "RUN_BUDGET_EXCEEDED",
            },
        )
    )

    response = budget_client.get(f"/api/v1/tasks/{task_id}/observability")
    assert response.status_code == 200
    budget = response.json()["budget"]
    tokens = budget["resources"]["total_tokens"]
    assert tokens["settled"] == 58_000
    assert tokens["remaining"] == 2_000
    assert tokens["exhausted"] is False
    assert budget["admission_denied"] is True
    assert budget["denied_resource"] == "total_tokens"
    assert "PRIVATE REPORT BODY" not in response.text
    assert "PRIVATE SNAPSHOT FIELD" not in response.text
    assert "snapshot_json" not in response.text


def test_failed_minimum_evidence_budget_denial_is_visible_without_result(
    budget_client,
):
    task_id, run_id = _create(budget_client)
    state = app_module.app.state
    budget_client.portal.call(
        partial(
            _seed_budget,
            state,
            run_id,
            total_limit=60_000,
            failed_error_id="BUDGET_EXCEEDED_INSUFFICIENT_EVIDENCE",
        )
    )

    response = budget_client.get(f"/api/v1/tasks/{task_id}/observability")
    assert response.status_code == 200
    budget = response.json()["budget"]
    assert budget["admission_denied"] is True
    assert budget["denied_resource"] is None
    assert budget["resources"]["total_tokens"]["exhausted"] is False
