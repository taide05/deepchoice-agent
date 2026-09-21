from __future__ import annotations

from argparse import Namespace
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from scripts import s1_qualification as s1
from scripts import o1_pr2b_control as control
from benchmarks import product_baseline as baseline
from benchmarks import product_baseline_experiment as experiment


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["waiting_for_input", "running", "queued", "interrupted"])
async def test_qualification_cleanup_never_mutates_nonterminal_tasks(tmp_path, monkeypatch, status):
    methods = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(200, json={"task": {"status": status}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")
    monkeypatch.setattr(control.httpx, "AsyncClient", lambda **kwargs: client)
    result = await control.settle("http://test", ["task"], tmp_path / "journal", True,
                                  cancel_active=False)
    assert methods == ["GET"]
    assert result["attempted"] == 0
    assert result["unresolved"] == ["task"]
    assert not (tmp_path / "journal").exists()


@pytest.mark.asyncio
async def test_qualification_cleanup_accepts_existing_terminal_state(tmp_path, monkeypatch):
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"task": {"status": "completed"}})),
        base_url="http://test")
    monkeypatch.setattr(control.httpx, "AsyncClient", lambda **kwargs: client)
    result = await control.settle("http://test", ["task"], tmp_path / "journal", True,
                                  cancel_active=False)
    assert result["settled"] == 1
    assert result["attempted"] == 0
    assert result["unresolved"] == []


def _command_fixture(tmp_path, monkeypatch, command):
    env_file = tmp_path / "empty.env"
    env_file.touch()
    binding = {"git_commit": "f" * 40, "tool_hashes": {"runner": "a" * 64}}
    monkeypatch.setattr(s1.qualification, "trusted_configuration", lambda: object())
    monkeypatch.setattr(s1, "check_candidate", lambda cfg: binding)
    args = Namespace(command=command, root=tmp_path / "study", env_file=env_file,
                     execute_paid_probes=False, execute_paid_run=False, frozen_seed=None)
    return args, binding


@pytest.mark.asyncio
async def test_preflight_needs_explicit_dispatch_and_cannot_repeat(tmp_path, monkeypatch):
    args, _ = _command_fixture(tmp_path, monkeypatch, "preflight")
    calls = []

    async def probe(*args, **kwargs):
        calls.append(1)
        return {"passed": False}

    monkeypatch.setattr(s1.qualification, "preflight", probe)
    with pytest.raises(ValueError, match="dispatch flag"):
        await s1.run_command(args)
    assert not args.root.exists()
    args.execute_paid_probes = True
    assert (await s1.run_command(args))["passed"] is False
    with pytest.raises(FileExistsError):
        await s1.run_command(args)
    assert calls == [1]


@pytest.mark.asyncio
async def test_qualification_run_needs_binding_and_does_not_open_formal_gate(tmp_path, monkeypatch):
    args, binding = _command_fixture(tmp_path, monkeypatch, "run")
    args.root.mkdir()
    path = args.root / "preflight-binding.json"
    path.write_text(json.dumps({}), encoding="utf-8")
    with pytest.raises(ValueError, match="changed since"):
        await s1.run_command(args)
    path.write_text(json.dumps(binding), encoding="utf-8")
    with pytest.raises(ValueError, match="single research admission flag"):
        await s1.run_command(args)
    calls = []

    async def execute(*args, **kwargs):
        calls.append((args, kwargs))
        return True

    monkeypatch.setattr(control, "execute", execute)
    args.execute_paid_run = True
    result = await s1.run_command(args)
    assert calls[0][0][-1] == "serial-r1"
    assert calls[0][1] == {"s1_qualification": True}
    assert result["report_quality_qualification"] == "pending"
    assert result["formal_measurement_gate"] == "closed"


def test_prepared_binding_rejects_environment_or_tool_drift(tmp_path, monkeypatch):
    root = tmp_path / "qualification"
    root.mkdir()
    (root / "environment.json").write_text("{}", encoding="utf-8")
    expected = {"git_commit": "a" * 40, "tool_hashes": {"runner": "b" * 64}}
    monkeypatch.setattr(s1, "check_candidate", lambda cfg: dict(expected))
    monkeypatch.setattr(s1.qualification, "verify_frozen_environment", lambda *args: None)
    monkeypatch.setattr(s1, "prerequisite_hashes", lambda root: {"summary": "c" * 64})
    binding = {**expected, "environment_sha256": s1.qualification.file_hash(root / "environment.json"),
               "prerequisite_hashes": {"summary": "c" * 64}}
    path = root / "s1-execution-binding.json"
    path.write_text(json.dumps(binding), encoding="utf-8")
    assert s1.verify_prepared(root, s1.protocol.ROOT, {}, None) == binding
    expected["tool_hashes"] = {"runner": "d" * 64}
    with pytest.raises(ValueError, match="binding changed"):
        s1.verify_prepared(root, s1.protocol.ROOT, {}, None)


def test_cli_sanitizes_private_errors(monkeypatch, tmp_path, capsys):
    async def fail(args):
        raise ValueError("private-secret-and-provider-error")

    monkeypatch.setattr(s1, "run_command", fail)
    assert s1.main(["audit", "--root", str(tmp_path), "--env-file", str(tmp_path / "env")]) == 1
    output = capsys.readouterr().out
    assert "private-secret" not in output
    assert json.loads(output)["formal_measurement_gate"] == "closed"


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["success", "hitl", "duplicate", "decision", "cancel", "resume"])
async def test_real_controller_single_case_wiring_without_service_or_network(
        tmp_path, monkeypatch, scenario):
    """Run the actual controller coroutine with an in-process fake boundary.

    Product behavior is tested elsewhere; this checks its orchestration guards,
    collector options, denominators, and cleanup mode as one integrated path.
    """
    root = tmp_path / "qualification"
    profile = root / "serial-r1"
    for name in ("runtime", "control", "knowledge"):
        (profile / name).mkdir(parents=True)
    env_file = tmp_path / "empty.env"
    env_file.touch()
    dependencies = []
    (root / "dependencies.json").write_text(json.dumps(dependencies), encoding="utf-8")
    monkeypatch.setattr(control, "EXPECTED_DEPENDENCIES", control.file_hash(root / "dependencies.json"))
    monkeypatch.setattr(control.os, "chdir", lambda path: None)
    monkeypatch.setenv("LLM_DS_CONCURRENCY", "80")
    cfg = SimpleNamespace(safe_fetch_proxy_sha256=control.EXPECTED_PROXY)
    monkeypatch.setattr(s1.qualification, "trusted_configuration", lambda: cfg)
    monkeypatch.setattr(s1.qualification, "git_identity", lambda: "candidate")
    monkeypatch.setattr(s1.qualification, "dependency_records", lambda: dependencies)
    monkeypatch.setattr(s1.qualification, "configuration_sha256", lambda cfg: control.EXPECTED_CONFIGURATION)
    monkeypatch.setattr(experiment, "embedding_revision", lambda: control.EXPECTED_EMBEDDING_REVISION)
    monkeypatch.setattr(experiment, "tree_hash", lambda root: control.EXPECTED_KNOWLEDGE)
    from deepchoice.contracts import manifest
    monkeypatch.setattr(manifest, "build_core_asset_registry", lambda: SimpleNamespace(registry_id="asset"))
    notes = {
        "git_commit": "candidate", "dataset_hash": control.EXPECTED_DATASET,
        "configuration_sha256": control.EXPECTED_CONFIGURATION,
        "endpoint_sha256": control.EXPECTED_ENDPOINT,
        "safe_fetch_proxy_sha256": control.EXPECTED_PROXY,
        "embedding_revision": control.EXPECTED_EMBEDDING_REVISION,
        "expected_manifest_id": "manifest", "core_asset_registry_id": "asset",
        "settings": {**experiment.RESOURCE_SETTINGS, "LLM_DS_CONCURRENCY": "80",
                     "DEEPCHOICE_SYNTH_THINKING": "0"},
    }
    environment = {
        "notes": notes, "knowledge_snapshot_sha256": control.EXPECTED_KNOWLEDGE,
        "dependency_snapshot_sha256": control.EXPECTED_DEPENDENCIES,
        "model": {"provider": "deepseek-flash", "model_id": "deepseek-v4-flash", "thinking": "disabled"},
    }
    (root / "environment.json").write_text(json.dumps(environment), encoding="utf-8")
    binding = {"git_commit": "candidate", "tool_hashes": {
        name: control.file_hash(Path(control.__file__).parent / name) for name in s1.TOOL_NAMES}}
    monkeypatch.setattr(s1, "verify_prepared", lambda *args: binding)
    case = {"id": "P01", "request": {"query": "synthetic"}}
    monkeypatch.setattr(baseline, "load_dataset", lambda *args, **kwargs: (
        {"cases": [case]}, control.EXPECTED_DATASET))

    process_state = {"exited": False, "arguments": [], "port": None}
    fake_child = SimpleNamespace(pid=123, poll=lambda: 0 if process_state["exited"] else None)

    def popen(arguments, **kwargs):
        process_state["arguments"] = arguments
        process_state["port"] = int(arguments[arguments.index("--port") + 1])
        return fake_child

    process = SimpleNamespace(
        pid=123, create_time=lambda: 1, cmdline=lambda: process_state["arguments"],
        children=lambda **kwargs: [], memory_info=lambda: SimpleNamespace(rss=100),
        net_connections=lambda **kwargs: [SimpleNamespace(status=control.psutil.CONN_LISTEN,
            laddr=("127.0.0.1", process_state["port"]))])
    monkeypatch.setattr(control.subprocess, "Popen", popen)
    monkeypatch.setattr(control.subprocess, "CREATE_NO_WINDOW", 0, raising=False)
    monkeypatch.setattr(control.psutil, "Process", lambda pid: process)
    monkeypatch.setattr(control.psutil, "virtual_memory", lambda: SimpleNamespace(available=3 * 1024 ** 3))
    client_factory = httpx.AsyncClient
    monkeypatch.setattr(control.httpx, "AsyncClient", lambda **kwargs: client_factory(
        **kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(
            200, json={"runtime_instance": "active"}))))

    mutations = []

    async def request(collector, method, path, **kwargs):
        mutations.append((method, path))
        return httpx.Response(202), {
            "task": {"task_id": "task"},
            "latest_run": {"run_id": "run", "manifest_id": "manifest"}}

    async def collect_case(collector, current_case):
        await collector._request_json("POST", "/api/v1/tasks", json=current_case["request"])
        if scenario in {"duplicate", "decision", "cancel", "resume"}:
            path = {"duplicate": "/api/v1/tasks", "decision": "/api/v1/tasks/task/decisions/d",
                    "cancel": "/api/v1/tasks/task/cancel", "resume": "/api/v1/tasks/task/resume"}[scenario]
            await collector._request_json("POST", path, json=current_case["request"])
        observation = {"availability": "available", "calls": [], "budget": {
            "availability": "available", "resources": {name: {"availability": "available", "exhausted": False}
                for name in ("active_milliseconds", "llm_calls", "retrieval_calls", "total_tokens")}}}
        return {"status": "waiting_for_input" if scenario == "hitl" else "completed",
                "error_code": "HITL_REQUIRED_NO_AUTO_RESOLUTION" if scenario == "hitl" else None,
                "report_path": None if scenario == "hitl" else "report.md",
                "observability": observation, "observability_final": True}

    monkeypatch.setattr(baseline.DurableBaselineCollector, "_request_json", request)
    monkeypatch.setattr(baseline.DurableBaselineCollector, "_collect_case", collect_case)

    async def collect(args):
        assert (args.command, args.case_id, args.profile, args.concurrency, args.repetition,
                args.stop_at_hitl) == ("collect-single", "P01", "serial", 1, 1, True)
        collector = baseline.DurableBaselineCollector(None, root, experiment_id="e",
            dataset_hash=control.EXPECTED_DATASET, options=None)
        record = await collector._collect_case(case)
        collection = Path(args.output_dir)
        collection.mkdir(parents=True)
        (collection / "runs.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
        metadata = {"git_commit": "candidate", "dataset_hash": control.EXPECTED_DATASET,
                    "profile": "serial", "repetition": 1, "requested_concurrency": 1,
                    "case_denominator": 1, "order_seed": 20260917, "case_order": ["P01"],
                    "admitted_run_denominator": 1, "manifest_ids": ["manifest"],
                    "collector_stop_reason": collector._abort_reason,
                    "source_health": "degraded" if collector._abort_reason else "passed",
                    "peak_in_flight_cases": 1}
        (collection / "experiment.json").write_text(json.dumps(metadata), encoding="utf-8")
        return 0

    monkeypatch.setattr(baseline, "_collect", collect)
    cleanup_modes = []

    async def settle(*args, **kwargs):
        cleanup_modes.append(kwargs["cancel_active"])
        return {"attempted": 0, "settled": 1, "unresolved": []}

    async def final(*args, **kwargs):
        return {"complete": True}

    async def shutdown(*args):
        process_state["exited"] = True
        return {"action": "graceful", "unresolved": [], "error_type": None}

    monkeypatch.setattr(control, "settle", settle)
    monkeypatch.setattr(control, "collect_stop_final_observability", final)
    monkeypatch.setattr(control, "shutdown_child", shutdown)
    monkeypatch.setattr(control, "lifecycle_metrics", lambda *args: {"complete": True})
    monkeypatch.setattr(control, "active_budget_metrics", lambda *args: {"complete": True})
    monkeypatch.setattr(control, "telemetry_http_anomaly", lambda *args, **kwargs: False)
    succeeded = await control.execute(root, tmp_path, env_file, "serial-r1", s1_qualification=True)
    assert succeeded is (scenario == "success")
    assert mutations == [("POST", "/api/v1/tasks")]
    assert cleanup_modes == [False]
    assert process_state["exited"]
    assert baseline.DurableBaselineCollector._request_json is request
    result = json.loads((profile / "control/profile-control-result.json").read_text(encoding="utf-8"))
    assert result["admission_attempts"] == 1
    if scenario == "hitl":
        assert result["first_stop_reason"] == "S1_QUALIFICATION_HITL_STOP"
        metadata = json.loads((root / "collections/serial-r1/experiment.json").read_text(encoding="utf-8"))
        assert metadata["source_health"] == "passed"
