"""Prospective v2 bindings; no live probes, services or model calls."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from benchmarks import product_optimization_serial_check_v1 as old_contract
from benchmarks import product_optimization_serial_check_v2 as contract
from scripts import product_optimization_serial_check_v1 as old_runner
from scripts import product_optimization_serial_check_v2 as runner


def test_frozen_overlay_preserves_execution_and_updates_only_candidate_and_ledger():
    old = old_contract.load_serial_check_protocol().payload
    frozen = contract.load_serial_check_protocol()
    new = runner._bootstrap_approved_protocol(frozen.byte_sha256)
    for field in ("dataset", "knowledge_seed", "environment", "stopping", "metrics"):
        assert new[field] == old[field]
    assert new["identities"]["baseline"] == old["identities"]["baseline"]
    assert new["identities"]["candidate"]["anchor_commit"].startswith("c1c43d8")
    assert new["design"]["execution_blocks"] == old["design"]["execution_blocks"]
    assert new["design"]["concurrency"] == 1
    assert new["design"]["hitl_policy"] == old["design"]["hitl_policy"]
    assert [row["blind_label"] for row in new["design"]["blind_review_order"]] == [
        "SC2-01", "SC2-02", "SC2-03",
    ]
    assert new["budgets"]["research_ledger"] == {
        "starting_used": 103, "diagnostic_max": 3, "concurrency_reserve": 0,
        "unallocated": 50, "hard_total": 156,
    }
    assert new["controller"]["research_admission"] == contract.CLOSED
    with pytest.raises(runner.RepairPairControlError, match="not open"):
        runner._require_active_protocol(new)


@pytest.mark.parametrize("path,value", [
    (("candidate", "anchor_commit"), "a" * 40),
    (("candidate", "source_objects", 0, "git_object"), "b" * 40),
    (("design", "case_order"), ["P01", "P04", "P08"]),
    (("design", "formal_research_runs"), 4),
    (("design", "holdout_access"), "allowed"),
    (("design", "hitl_policy", "cases", "P01", "stop_at_hitl"), False),
    (("design", "hitl_policy", "cases", "P08", "max_auto_resolutions"), 3),
    (("budgets", "research_ledger", "starting_used"), 100),
    (("budgets", "research_ledger", "hard_total"), 157),
    (("budgets", "research_ledger", "concurrency_reserve"), 1),
    (("authorization", "concurrency_runs_authorized"), False),  # bool is not integer zero
    (("stopping", "replace_retry_or_splice_stopped_root"), True),
    (("acceptance", "citation"), "all-verified-means-quality-pass"),
    (("control_predecessor", "accounted_research_runs"), 0),
    (("controller", "research_admission"), "open-without-binding"),
    (("controller", "required_files", 0, "sha256"), "0" * 64),
])
def test_protocol_drift_rejected(path, value):
    raw = json.loads(contract.PROTOCOL_PATH.read_text(encoding="utf-8"))
    target = raw
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(contract.SerialCheckProtocolError, match="drift"):
        contract._validate_raw(raw)


def test_frozen_design_hash_is_verified(monkeypatch):
    raw = json.loads(contract.PROTOCOL_PATH.read_text(encoding="utf-8"))
    real_hash = old_contract._file_sha256
    monkeypatch.setattr(old_contract, "_file_sha256", lambda path:
                        "0" * 64 if str(path).endswith("serial-check-v2.md") else real_hash(path))
    with pytest.raises(contract.SerialCheckProtocolError, match="design drift"):
        contract._validate_raw(raw)


def test_wrong_external_protocol_hash_fails_before_loader(monkeypatch):
    monkeypatch.setattr(runner, "_load_approved_protocol", lambda *_:
                        pytest.fail("loader must not run before external SHA check"))
    with pytest.raises(runner.RepairPairControlError, match="identity mismatch"):
        runner._bootstrap_approved_protocol("0" * 64)


def test_import_does_not_freeze_llm_settings_before_private_environment():
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(runner.ROOT / "src"), str(runner.ROOT)))
    result = subprocess.run([
        sys.executable, "-c",
        "import sys; import scripts.product_optimization_serial_check_v2; "
        "assert 'deepchoice.utils.llm' not in sys.modules; print('not-loaded')",
    ], cwd=runner.ROOT, env=environment, capture_output=True, text=True, check=True, timeout=30)
    assert result.stdout.strip() == "not-loaded"


def test_scoped_adapter_restores_historical_globals_even_on_error():
    names = ("PROTOCOL_PATH", "LEDGER_ROOT", "_load_approved_protocol",
             "_bootstrap_approved_protocol", "_require_active_protocol")
    before = {name: getattr(old_runner, name) for name in names}
    with pytest.raises(RuntimeError):
        with runner._configured_parent(), old_runner._configured_base():
            assert old_runner.PROTOCOL_PATH == runner.PROTOCOL_PATH
            assert old_runner._v4.LEDGER_ROOT == runner.LEDGER_ROOT
            assert old_runner._v4._bootstrap_approved_protocol is runner._bootstrap_approved_protocol
            raise RuntimeError("controlled failure")
    assert all(getattr(old_runner, name) == value for name, value in before.items())
    assert old_contract.load_serial_check_protocol().payload["protocol_id"].endswith("v1")


@pytest.mark.parametrize("command", ["audit", "preflight", "prepare"])
def test_public_entry_points_install_environment_before_materializing(monkeypatch, command):
    seen = []
    monkeypatch.setattr(old_runner, "_install_call_environment", lambda *args: seen.append("env"))
    monkeypatch.setattr(runner, "_admit_call", lambda *_: None)  # Future activated-path routing only.

    def base_call(*args):
        assert seen == ["env"]
        assert old_runner._v4.PROTOCOL_PATH == runner.PROTOCOL_PATH
        assert old_runner._v4.LEDGER_ROOT == runner.LEDGER_ROOT
        return {"research_runs_submitted": 0}

    monkeypatch.setattr(old_runner._v4, command, base_call)
    monkeypatch.setattr(old_runner, "_freeze_prepared_hitl_policy", lambda *_: None)
    args = [Path("unused")] * (6 if command == "prepare" else 5)
    if command == "prepare":
        args[-1] = contract.load_serial_check_protocol().byte_sha256
    assert getattr(runner, command)(*args)["research_runs_submitted"] == 0


def test_closed_preflight_stops_before_probe_or_output(monkeypatch, tmp_path):
    protocol = deepcopy(contract.load_serial_check_protocol().payload)
    protocol["controller"]["research_admission"] = "closed"
    monkeypatch.setattr(runner, "_bootstrap_approved_protocol", lambda *_: protocol)
    monkeypatch.setattr(old_runner, "_install_call_environment", lambda *_: None)
    monkeypatch.setattr(old_runner._v4, "audit", lambda *_: pytest.fail("paid path reached"))
    env = tmp_path / "private.env"
    env.write_text("", encoding="utf-8")
    output = tmp_path / "must-not-exist"
    with pytest.raises(runner.RepairPairControlError, match="not open"):
        runner.preflight(output, tmp_path, tmp_path, env, "a" * 64)
    assert not output.exists()


@pytest.mark.parametrize("field,value", [("started_cells", 2), ("complete", True),
                                         ("stop_reason", None)])
def test_predecessor_accounting_cannot_be_relabelled(monkeypatch, field, value):
    protocol = contract.load_serial_check_protocol().payload
    real_read = old_runner._v4._bound_json_artifact

    def altered(root, spec):
        data = real_read(root, spec)
        if spec == protocol["control_predecessor"]["artifacts"]["run_result"]:
            data[field] = value
        return data

    monkeypatch.setattr(old_runner._v4, "_bound_json_artifact", altered)
    with pytest.raises(runner.RepairPairControlError, match="accounting drift"):
        runner._validate_control_predecessor(protocol)


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_after", [None, 1])
async def test_real_run_shell_uses_only_v2_ledger_and_three_serial_cells(monkeypatch, tmp_path, stop_after):
    protocol = contract.load_serial_check_protocol().payload
    digest = contract.load_serial_check_protocol().byte_sha256
    base = old_runner._v4
    # Exercise the inherited execution shell only under explicitly simulated
    # future activation; the actual checked-in card is tested closed below.
    monkeypatch.setattr(runner, "_admit_call", lambda *_: None)
    monkeypatch.setattr(runner, "_require_active_protocol", lambda *_: None)
    ledger = tmp_path / "v2-ledger"
    experiment = tmp_path / "fresh-experiment"
    experiment.mkdir()
    binding = {"protocol_byte_sha256": digest}
    base._write_json(experiment / "execution-binding.json", binding)
    monkeypatch.setattr(runner, "LEDGER_ROOT", ledger)
    monkeypatch.setattr(old_runner, "_install_call_environment", lambda *_: None)
    monkeypatch.setattr(old_runner, "_validate_execution_binding_allow_used", lambda *_: (protocol, binding))
    monkeypatch.setattr(old_runner, "audit", lambda *_: {
        "arm_contracts": {"candidate": {"manifests": {case: case for case in ("P04", "P01", "P08")}}},
    })

    async def block(**kwargs):
        assert kwargs["block"]["case_order"] == ["P04", "P01", "P08"]
        assert base.LEDGER_ROOT == ledger
        records = []
        for case in kwargs["block"]["case_order"]:
            kwargs["before_admission"]()
            base._reserve_cell("candidate", 1, case, runner.PROTOCOL_ID)
            record = {"arm": "candidate", "repetition": 1, "block": 1, "case_id": case,
                      "task_id": case, "run_id": case, "status": "completed", "error_code": None}
            base._append_ledger_observation(record, runner.PROTOCOL_ID)
            records.append(record)
            if stop_after == len(records):
                return records, "TELEMETRY_strict_safe_fetch_failure"
        return records, None

    monkeypatch.setattr(old_runner, "_run_candidate_block", block)
    result = await runner.run(experiment, tmp_path, tmp_path, tmp_path, tmp_path, digest)
    assert result["protocol_id"] == runner.PROTOCOL_ID
    assert result["planned_cells"] == 3
    assert result["started_cells"] == (stop_after or 3)
    assert result["complete"] is (stop_after is None)
    assert result["ledger"]["possibly_submitted_max"] == (stop_after or 3)
    assert json.loads((ledger / "execution-claim.json").read_text())["protocol_id"] == runner.PROTOCOL_ID
    if stop_after:
        assert [row["status"] for row in result["cells"]] == ["completed", "not_submitted", "not_submitted"]
    with pytest.raises(runner.RepairPairControlError):
        await runner.run(experiment, tmp_path, tmp_path, tmp_path, tmp_path, digest)


@pytest.mark.parametrize("command", ["preflight", "run"])
def test_cli_requires_paid_flags_before_any_entry(monkeypatch, command):
    monkeypatch.setattr(sys, "argv", ["v2", command, "--baseline-root", "a", "--candidate-root", "b",
                                     "--expected-protocol-byte-sha256", "a" * 64])
    monkeypatch.setattr(old_runner, command, lambda *_: pytest.fail("must not dispatch"))
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["preflight", "prepare", "run"])
async def test_actual_frozen_card_blocks_all_side_effect_entrypoints(monkeypatch, tmp_path, command):
    monkeypatch.setattr(old_runner, "_install_call_environment", lambda *_: None)
    monkeypatch.setattr(old_runner, command, lambda *_: pytest.fail("closed card dispatched"))
    monkeypatch.setattr(runner, "LEDGER_ROOT", tmp_path / "new-ledger")
    args = [tmp_path / "unused"] * (5 if command == "preflight" else 6)
    args[-1] = contract.load_serial_check_protocol().byte_sha256
    with pytest.raises(runner.RepairPairControlError, match="not open"):
        if command == "run":
            await runner.run(*args)
        else:
            getattr(runner, command)(*args)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("command", ["preflight", "prepare", "run"])
def test_cli_paid_flags_cannot_open_actual_closed_card(monkeypatch, tmp_path, capsys, command):
    env = tmp_path / "private.env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setattr(old_runner, "_install_call_environment", lambda *_: None)
    # Allow run to reach the existing active-protocol gate without a prepared
    # environment. No service or client may be created, even with paid flags.
    monkeypatch.setattr(old_runner, "_validate_prepared_hitl_policy", lambda *_: None)
    monkeypatch.setattr(old_runner, "_prepared_environment_paths", lambda *_: [])
    monkeypatch.setattr(old_runner._v4, "audit", lambda *_: pytest.fail("audit reached from closed paid path"))
    monkeypatch.setattr(runner, "LEDGER_ROOT", tmp_path / "v2-ledger")
    monkeypatch.setattr(sys, "argv", [
        "v2", command, "--baseline-root", str(tmp_path), "--candidate-root", str(tmp_path),
        "--env-file", str(env), "--output-dir", str(tmp_path / "preflight"),
        "--preflight-dir", str(tmp_path / "preflight"), "--experiment-root", str(tmp_path / "experiment"),
        "--expected-protocol-byte-sha256", contract.load_serial_check_protocol().byte_sha256,
        "--execute-paid-runs", "--execute-paid-probes", "--trust-current-local-proxy",
    ])
    assert runner.main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["error_type"] == "RepairPairControlError"
    assert result["research_runs_submitted"] == 0
    assert list(tmp_path.iterdir()) == [env]
