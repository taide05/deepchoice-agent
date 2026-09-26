from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from benchmarks import product_optimization_repair_pair_v5 as protocol_v5
from benchmarks import product_optimization_repair_pair_v6 as protocol_v6
from scripts import product_optimization_repair_pair as runner_v4
from scripts import product_optimization_repair_pair_v6 as runner_v6


ALLOWED = {
    "chroma/chroma.sqlite3",
    "chroma/c29ae142-54e0-4e63-b329-24f1f4af8a53/data_level0.bin",
    "chroma/c29ae142-54e0-4e63-b329-24f1f4af8a53/length.bin",
}


def _knowledge_copy(root: Path) -> Path:
    files = {
        "seed-manifest.json": b"manifest\n",
        "learned_docs.json": b"[]\n",
        "chroma/chroma.sqlite3": b"sqlite00",
        "chroma/c29ae142-54e0-4e63-b329-24f1f4af8a53/data_level0.bin": b"data0000",
        "chroma/c29ae142-54e0-4e63-b329-24f1f4af8a53/length.bin": b"length00",
        "chroma/c29ae142-54e0-4e63-b329-24f1f4af8a53/header.bin": b"header00",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return root


def test_v6_allows_only_listed_same_size_drift_after_attempt(tmp_path: Path):
    pristine = _knowledge_copy(tmp_path / "pristine")
    used = _knowledge_copy(tmp_path / "used")
    (used / "chroma/chroma.sqlite3").write_bytes(b"changed0")
    (used / (
        "chroma/c29ae142-54e0-4e63-b329-24f1f4af8a53/data_level0.bin"
    )).write_bytes(b"changed0")

    runner_v6._validate_used_knowledge_copy(pristine, used, ALLOWED)


def test_v6_allows_unchanged_attempted_knowledge_copy(tmp_path: Path):
    pristine = _knowledge_copy(tmp_path / "pristine")
    used = _knowledge_copy(tmp_path / "used")

    runner_v6._validate_used_knowledge_copy(pristine, used, ALLOWED)


@pytest.mark.parametrize(
    ("relative", "content", "message"),
    (
        ("learned_docs.json", b"{}\n", "used knowledge content drift"),
        ("chroma/chroma.sqlite3", b"longer-content", "used knowledge content drift"),
        ("chroma/new.bin", b"new", "used knowledge inventory drift"),
    ),
)
def test_v6_rejects_unbounded_knowledge_drift(
    tmp_path: Path, relative: str, content: bytes, message: str
):
    pristine = _knowledge_copy(tmp_path / "pristine")
    used = _knowledge_copy(tmp_path / "used")
    path = used / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

    with pytest.raises(runner_v6.RepairPairControlError, match=message):
        runner_v6._validate_used_knowledge_copy(pristine, used, ALLOWED)


def test_v6_masks_only_attempted_block_tree_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    experiment = tmp_path / "experiment"
    knowledge = (
        runner_v4._block_root(experiment, "baseline", 2)
        / "serial-r2/knowledge"
    )
    knowledge.mkdir(parents=True)
    runner_v4._write_json(
        experiment / "execution-binding.json",
        {
            "blocks": [{
                "arm": "baseline",
                "repetition": 2,
                "profile": "serial-r2",
                "knowledge_sha256": "frozen-tree",
            }],
        },
    )
    protocol = {
        "protocol_id": "product-optimization-repair-pair-v6",
        "design": {"execution_blocks": [{"arm": "baseline", "repetition": 2}]},
        "stopping": {"allowed_chroma_runtime_drift_paths": sorted(ALLOWED)},
    }
    calls = 0

    def validate(*_args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise runner_v6.RepairPairControlError("prepared block drift")
        assert runner_v4._tree_hash(knowledge) == "frozen-tree"
        return protocol, {"blocks": []}

    original_tree_hash = runner_v4._tree_hash
    monkeypatch.setattr(runner_v6, "_BASE_VALIDATE_EXECUTION_BINDING", validate)
    monkeypatch.setattr(runner_v6, "_bootstrap_approved_protocol", lambda _sha: protocol)
    monkeypatch.setattr(
        runner_v6, "_attempted_blocks", lambda _protocol: {("baseline", 2)}
    )
    monkeypatch.setattr(
        runner_v6, "_validate_used_knowledge_copy", lambda *_args: None
    )

    returned = runner_v6._validate_execution_binding_allow_used(
        experiment,
        tmp_path / "preflight",
        tmp_path / "baseline",
        tmp_path / "candidate",
        tmp_path / ".env",
        "0" * 64,
    )

    assert returned == (protocol, {"blocks": []})
    assert calls == 2
    assert runner_v4._tree_hash is original_tree_hash


def _reconciliation_fixture(tmp_path: Path) -> tuple[Path, dict]:
    (runner_v6.LEDGER_ROOT / "cells").mkdir(parents=True)
    (runner_v6.LEDGER_ROOT / "cells/baseline-r2-P04.json").write_text(
        json.dumps({
            "schema_version": 1,
            "protocol_id": "product-optimization-repair-pair-v6",
            "arm": "baseline",
            "repetition": 2,
            "case_id": "P04",
            "status": "attempted-before-post",
        }) + "\n",
        encoding="utf-8",
    )
    runner_v6.LEDGER_ROOT.joinpath("observations.jsonl").write_text(
        json.dumps({
            "schema_version": 1,
            "protocol_id": "product-optimization-repair-pair-v6",
            "arm": "baseline",
            "repetition": 2,
            "case_id": "P04",
            "task_id": "task-1",
            "run_id": "run-1",
            "status": "completed",
            "error_code": None,
        }) + "\n",
        encoding="utf-8",
    )
    experiment = tmp_path / "experiment"
    collection = experiment / "collections/baseline-r2"
    collection.mkdir(parents=True)
    record = {
        "experiment_id": "product-optimization-repair-pair-v6",
        "case_id": "P04",
        "task_id": "task-1",
        "run_id": "run-1",
        "status": "completed",
        "error_code": None,
    }
    (collection / "runs.jsonl").write_text(
        json.dumps(record) + "\n", encoding="utf-8"
    )
    result = {
        "schema_version": 1,
        "protocol_id": "product-optimization-repair-pair-v6",
        "started_cells": 0,
        "planned_cells": 12,
        "complete": False,
        "stop_reason": "CONTROL_RepairPairControlError",
        "cells": [{
            "block": 1,
            "arm": "baseline",
            "repetition": 2,
            "case_id": "P04",
            "status": "not_submitted",
        }],
        "records": [],
        "no_retries_or_splices": True,
        "ledger": {},
    }
    return experiment, result


def test_v6_reconciles_completed_same_root_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(runner_v6, "LEDGER_ROOT", tmp_path / "ledger")
    experiment, result = _reconciliation_fixture(tmp_path)
    monkeypatch.setattr(runner_v4, "_record_stop_reason", lambda *_args: None)
    with runner_v6._configured_base():
        reconciled = runner_v6._reconcile_completed_records(
            experiment, result, "product-optimization-repair-pair-v6"
        )

    assert reconciled["started_cells"] == 1
    assert reconciled["cells"][0]["status"] == "completed"
    assert reconciled["records"][0]["block"] == 1
    assert reconciled["ledger"] == {
        "attempted_cells": 1,
        "known_admitted_min": 1,
        "possibly_submitted_max": 1,
        "uncertain_cells": 0,
        "submission_count_uncertain": False,
    }
    assert json.loads(
        (experiment / "repair-pair-run-result.json").read_text(encoding="utf-8")
    ) == reconciled


def test_v6_reconciliation_rejects_cross_run_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(runner_v6, "LEDGER_ROOT", tmp_path / "ledger")
    experiment, result = _reconciliation_fixture(tmp_path)
    runs = experiment / "collections/baseline-r2/runs.jsonl"
    record = json.loads(runs.read_text(encoding="utf-8"))
    record["run_id"] = "other-run"
    runs.write_text(json.dumps(record) + "\n", encoding="utf-8")
    monkeypatch.setattr(runner_v4, "_record_stop_reason", lambda *_args: None)

    with runner_v6._configured_base(), pytest.raises(
        runner_v6.RepairPairControlError,
        match="completed record reconciliation failed",
    ):
        runner_v6._reconcile_completed_records(
            experiment, result, "product-optimization-repair-pair-v6"
        )


def test_v6_reconciliation_rejects_invalid_observation_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(runner_v6, "LEDGER_ROOT", tmp_path / "ledger")
    experiment, result = _reconciliation_fixture(tmp_path)
    runner_v6.LEDGER_ROOT.joinpath("observations.jsonl").write_text(
        "{invalid\n", encoding="utf-8"
    )

    with pytest.raises(
        runner_v6.RepairPairControlError,
        match="protocol observation ledger is invalid",
    ):
        runner_v6._reconcile_completed_records(
            experiment, result, "product-optimization-repair-pair-v6"
        )


def test_v6_reconciliation_rejects_unknown_observation_cell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(runner_v6, "LEDGER_ROOT", tmp_path / "ledger")
    experiment, result = _reconciliation_fixture(tmp_path)
    observation_path = runner_v6.LEDGER_ROOT / "observations.jsonl"
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    observation["case_id"] = "unknown"
    observation_path.write_text(json.dumps(observation) + "\n", encoding="utf-8")

    with pytest.raises(
        runner_v6.RepairPairControlError,
        match="protocol observation cell drift",
    ):
        runner_v6._reconcile_completed_records(
            experiment, result, "product-optimization-repair-pair-v6"
        )


def test_v6_serial_effect_protocol_loads_and_preserves_v5_identity():
    frozen_v6 = protocol_v6.load_repair_pair_protocol()
    frozen_v5 = protocol_v5.load_repair_pair_protocol()

    assert frozen_v6.payload["protocol_id"] == protocol_v6.PROTOCOL_ID
    assert frozen_v6.payload["status"] == "frozen"
    assert frozen_v6.payload["controller"]["research_admission"] == (
        "open-after-offline-runner-acceptance"
    )
    assert frozen_v6.payload["budgets"]["research_ledger"] == {
        "starting_used": 97,
        "local_pair_max": 12,
        "final_concurrency_reserve": 0,
        "unallocated": 47,
        "hard_total": 156,
    }
    assert frozen_v6.payload["authorization"]["effective_hard_total"] == 156
    assert frozen_v6.payload["authorization"]["concurrency_runs_authorized"] == 0
    assert [
        item["blind_label"]
        for item in frozen_v6.payload["design"]["blind_review_order"]
    ] == [f"RP6-{index:02d}" for index in range(1, 13)]
    assert frozen_v5.byte_sha256 == (
        "13e8bd9ef2e6877c4c8465db22c3ab0bc1b11f3f386e704b7b314a45ef0fd796"
    )


def test_v6_serial_effect_protocol_opens_only_the_existing_cap():
    protocol = protocol_v6.load_repair_pair_protocol().payload
    runner_v6._require_active_protocol(protocol)

    changed = copy.deepcopy(protocol)
    changed["authorization"]["concurrency_runs_authorized"] = 1
    with pytest.raises(
        runner_v6.RepairPairControlError,
        match="research admission is not approved",
    ):
        runner_v6._require_active_protocol(changed)


def test_v6_base_configuration_is_scoped_and_restored():
    names = (
        "PROTOCOL_PATH", "CHILD", "LEDGER_ROOT", "_bootstrap_approved_protocol",
        "_load_approved_protocol", "_require_active_protocol",
        "_validate_execution_binding",
    )
    before = {name: getattr(runner_v4, name) for name in names}
    with runner_v6._configured_base():
        assert runner_v4.PROTOCOL_PATH == runner_v6.PROTOCOL_PATH
        assert runner_v4.CHILD == runner_v6.CHILD
        assert runner_v4.LEDGER_ROOT == runner_v6.LEDGER_ROOT
        assert runner_v4._validate_execution_binding is (
            runner_v6._validate_execution_binding_allow_used
        )
    assert {name: getattr(runner_v4, name) for name in names} == before
