"""Offline acceptance for the closed v4 serial measurement identity."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from benchmarks import product_optimization_serial_check_v3 as old_contract
from benchmarks import product_optimization_serial_check_v4 as contract
from scripts import product_optimization_serial_check_v3 as old_runner
from scripts import product_optimization_serial_check_v4 as runner


def test_frozen_overlay_binds_new_candidate_and_preserves_strict_stopping():
    old = old_contract.load_serial_check_protocol().payload
    frozen = contract.load_serial_check_protocol()
    new = runner._bootstrap_approved_protocol(frozen.byte_sha256)
    for field in ("dataset", "knowledge_seed", "environment", "stopping", "metrics"):
        assert new[field] == old[field]
    assert new["identities"]["baseline"] == old["identities"]["baseline"]
    assert new["identities"]["candidate"]["anchor_commit"] == "f0217760a8c620f3f8afd0aa09c1b18dc1bc811a"
    assert new["identities"]["candidate"]["source_objects"][0]["git_object"] == "c23f03dd5189bedbe72770a194b70562b18c9d4a"
    assert new["design"]["execution_blocks"][0]["case_order"] == ["P04", "P08", "P01"]
    assert [row["case_id"] for row in new["design"]["blind_review_order"]] == ["P04", "P08", "P01"]
    assert [row["blind_label"] for row in new["design"]["blind_review_order"]] == ["SC4-01", "SC4-02", "SC4-03"]
    assert new["design"]["concurrency"] == 1
    assert new["design"]["hitl_policy"] == old["design"]["hitl_policy"]
    assert new["budgets"]["research_ledger"] == {
        "starting_used": 107, "diagnostic_max": 3, "concurrency_reserve": 0,
        "unallocated": 46, "hard_total": 156,
    }
    assert new["controller"]["research_admission"] == contract.CLOSED
    with pytest.raises(runner.RepairPairControlError, match="not open"):
        runner._require_active_protocol(new)


@pytest.mark.parametrize("path,value", [
    (("candidate", "anchor_commit"), "a" * 40),
    (("design", "case_order"), ["P04", "P01", "P08"]),
    (("design", "hitl_policy", "cases", "P04", "stop_at_hitl"), False),
    (("budgets", "research_ledger", "starting_used"), 105),
    (("budgets", "research_ledger", "hard_total"), 157),
    (("budgets", "research_ledger", "concurrency_reserve"), 1),
    (("control_predecessor", "accounted_research_runs"), 3),
    (("control_predecessor", "artifacts", "run_result", "root"), "candidate"),
    (("controller", "research_admission"), "open-without-review"),
    (("controller", "required_files", 0, "sha256"), "0" * 64),
    (("acceptance", "citation"), "verified-count-is-quality"),
])
def test_protocol_drift_rejected(path, value):
    raw = json.loads(contract.PROTOCOL_PATH.read_text(encoding="utf-8"))
    target = raw
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(contract.SerialCheckProtocolError, match="drift"):
        contract._validate_raw(raw)


def test_local_card_and_split_predecessor_are_bound(monkeypatch):
    raw = json.loads(contract.PROTOCOL_PATH.read_text(encoding="utf-8"))
    real_hash = contract._file_sha256
    monkeypatch.setattr(contract, "_file_sha256", lambda path:
                        "0" * 64 if Path(path) == contract.CARD_PATH else real_hash(path))
    with pytest.raises(contract.SerialCheckProtocolError, match="design card drift"):
        contract._validate_raw(raw)

    monkeypatch.setattr(contract, "_file_sha256", real_hash)
    protocol = contract.load_serial_check_protocol().payload
    real_read = runner._base._bound_json_artifact

    def altered(root, specification):
        data = real_read(root, specification)
        if specification["path"].endswith("serial-check-run-result.json"):
            data["started_cells"] = 3
        return data

    monkeypatch.setattr(runner._base, "_bound_json_artifact", altered)
    with pytest.raises(runner.RepairPairControlError, match="accounting drift"):
        runner._validate_control_predecessor(protocol)


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["preflight", "prepare", "run"])
async def test_closed_paid_entrypoints_have_no_side_effects(monkeypatch, tmp_path, command):
    monkeypatch.setattr(old_runner.parent.parent, "_install_call_environment", lambda *_: None)
    monkeypatch.setattr(old_runner, command, lambda *_: pytest.fail("paid path reached"))
    closed = deepcopy(contract.load_serial_check_protocol().payload)
    monkeypatch.setattr(runner, "_bootstrap_approved_protocol", lambda *_: closed)
    arguments = [tmp_path / "unused"] * (5 if command == "preflight" else 6)
    arguments[-1] = contract.load_serial_check_protocol().byte_sha256
    with pytest.raises(runner.RepairPairControlError, match="not open"):
        if command == "run":
            await runner.run(*arguments)
        else:
            getattr(runner, command)(*arguments)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["preflight", "prepare", "run"])
async def test_prospective_open_gate_delegates_only_to_v4_scope(monkeypatch, tmp_path, command):
    protocol = deepcopy(contract.load_serial_check_protocol().payload)
    protocol["controller"]["research_admission"] = contract.OPEN
    seen = []
    monkeypatch.setattr(old_runner.parent.parent, "_install_call_environment", lambda *_: seen.append("env"))
    monkeypatch.setattr(runner, "_bootstrap_approved_protocol", lambda *_: protocol)
    monkeypatch.setattr(runner, "_load_approved_protocol", lambda *_: SimpleNamespace(payload=protocol))

    def delegated(*args):
        assert seen == ["env"]
        assert old_runner.PROTOCOL_PATH == runner.PROTOCOL_PATH
        assert old_runner.LEDGER_ROOT == runner.LEDGER_ROOT
        return {"research_runs_submitted": 0}

    async def async_delegated(*args):
        return delegated(*args)

    monkeypatch.setattr(old_runner, command, async_delegated if command == "run" else delegated)
    arguments = [tmp_path / "unused"] * (5 if command == "preflight" else 6)
    arguments[-1] = contract.load_serial_check_protocol().byte_sha256
    result = await runner.run(*arguments) if command == "run" else getattr(runner, command)(*arguments)
    assert result == {"research_runs_submitted": 0}
    assert list(tmp_path.iterdir()) == []


def test_scoped_adapter_restores_v3_globals_on_failure():
    names = ("PROTOCOL_PATH", "LEDGER_ROOT", "_load_approved_protocol",
             "_bootstrap_approved_protocol", "_require_active_protocol")
    before = {name: getattr(old_runner, name) for name in names}
    with pytest.raises(RuntimeError):
        with runner._configured_parent():
            assert old_runner.PROTOCOL_PATH == runner.PROTOCOL_PATH
            assert old_runner.LEDGER_ROOT == runner.LEDGER_ROOT
            raise RuntimeError("controlled failure")
    assert all(getattr(old_runner, name) == value for name, value in before.items())


def test_import_does_not_freeze_llm_settings_before_private_environment():
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(runner.ROOT / "src"), str(runner.ROOT)))
    result = subprocess.run([
        sys.executable, "-c",
        "import sys; import scripts.product_optimization_serial_check_v4; "
        "assert 'deepchoice.utils.llm' not in sys.modules; print('not-loaded')",
    ], cwd=runner.ROOT, env=environment, capture_output=True, text=True, check=True, timeout=30)
    assert result.stdout.strip() == "not-loaded"


@pytest.mark.parametrize("command", ["preflight", "run"])
def test_cli_requires_paid_flags_before_dispatch(monkeypatch, command):
    monkeypatch.setattr(sys, "argv", [
        "v4", command, "--baseline-root", "a", "--candidate-root", "b",
        "--expected-protocol-byte-sha256", "a" * 64,
    ])
    monkeypatch.setattr(old_runner.parent.parent, command, lambda *_: pytest.fail("must not dispatch"))
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2


@pytest.mark.parametrize("command", ["preflight", "prepare", "run"])
def test_cli_paid_flags_cannot_open_closed_card(monkeypatch, tmp_path, capsys, command):
    env_file = tmp_path / "private.env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(old_runner.parent.parent, "_install_call_environment", lambda *_: None)
    monkeypatch.setattr(old_runner.parent.parent, "_validate_prepared_hitl_policy", lambda *_: None)
    monkeypatch.setattr(old_runner.parent.parent, "_prepared_environment_paths", lambda *_: [])
    monkeypatch.setattr(old_runner._base, "audit", lambda *_: pytest.fail("audit reached from closed paid path"))
    closed = deepcopy(contract.load_serial_check_protocol().payload)
    monkeypatch.setattr(runner, "_bootstrap_approved_protocol", lambda *_: closed)
    monkeypatch.setattr(runner, "LEDGER_ROOT", tmp_path / "v4-ledger")
    monkeypatch.setattr(sys, "argv", [
        "v4", command, "--baseline-root", str(tmp_path), "--candidate-root", str(tmp_path),
        "--env-file", str(env_file), "--output-dir", str(tmp_path / "preflight"),
        "--preflight-dir", str(tmp_path / "preflight"),
        "--experiment-root", str(tmp_path / "experiment"),
        "--expected-protocol-byte-sha256", contract.load_serial_check_protocol().byte_sha256,
        "--execute-paid-runs", "--execute-paid-probes", "--trust-current-local-proxy",
    ])
    assert runner.main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["error_type"] == "RepairPairControlError"
    assert result["research_runs_submitted"] == 0
    assert list(tmp_path.iterdir()) == [env_file]
