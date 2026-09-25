from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.machinery
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import o1_pr2b_control
from scripts import product_optimization_repair_pair as runner


def _protocol() -> dict:
    return {
        "protocol_id": "product-optimization-repair-pair-v1",
        "dataset": {
            "parent_sha256": "e" * 64,
            "development_projection_sha256": "d" * 64,
        },
        "knowledge_seed": {
            "artifact_tree_sha256": "",
        },
        "environment": {
            "model": "deepseek-v4-flash",
            "endpoint_sha256": "b" * 64,
            "configuration_sha256": "q" * 64,
            "safe_fetch_proxy_sha256": None,
            "embedding_model": "BAAI/bge-m3",
            "embedding_revision": "5617a9f61b028005a4858fdac845db406aefb181",
        },
        "design": {
            "same_window_days": 7,
            "execution_blocks": [
                {"block": 1, "arm": "baseline", "repetition": 2,
                 "case_order": ["P04", "P01", "P08"]},
                {"block": 2, "arm": "candidate", "repetition": 2,
                 "case_order": ["P04", "P08", "P01"]},
                {"block": 3, "arm": "candidate", "repetition": 1,
                 "case_order": ["P04", "P08", "P01"]},
                {"block": 4, "arm": "baseline", "repetition": 1,
                 "case_order": ["P04", "P08", "P01"]},
            ]
        },
    }


def _audit() -> dict:
    manifests = {"P01": "1" * 64, "P04": "4" * 64, "P08": "8" * 64}
    contract = {
        "manifests": manifests,
        "core_asset_registry_id": "a" * 64,
        "model_id": "deepseek-v4-flash",
        "endpoint_sha256": "b" * 64,
        "resource_settings": {
            "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
            "TOKENIZERS_PARALLELISM": "false", "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1", "LEARNED_DOCS_READONLY": "1",
            "RETRIEVAL_CACHE_ENABLED": "1",
        },
    }
    return {
        "roots": {
            "baseline": {"anchor_commit": "b" * 40},
            "candidate": {"anchor_commit": "c" * 40},
        },
        "arm_contracts": {"baseline": contract, "candidate": contract},
        "seed": {"artifact_tree_sha256": "s" * 64},
        "protocol_byte_sha256": "f" * 64,
        "effective_environment_identity_sha256": "v" * 64,
        "dependency_snapshot_sha256": "d" * 64,
        "configuration_sha256": "q" * 64,
        "safe_fetch_proxy_sha256": None,
        "endpoint_sha256": "b" * 64,
    }


def _successful_record(case_id: str, snapshot: str = "snapshot.json") -> dict:
    resources = {
        name: {
            "availability": "available", "exhausted": False,
            "reserved": 0, "unknown_spend": 0,
        }
        for name in ("active_milliseconds", "llm_calls", "retrieval_calls", "total_tokens")
    }
    return {
        "case_id": case_id,
        "status": "completed",
        "error_code": None,
        "hitl_resolutions": 0,
        "report_path": "report.md",
        "snapshot_path": snapshot,
        "observability_final": True,
        "observability": {
            "totals": {"token_usage_complete": True},
            "budget": {"availability": "available", "resources": resources,
                       "admission_denied": False},
            "calls": [],
        },
        "runtime_observations": {
            "authority_valid": True,
            "lease_remaining_ms": 30000,
        },
        "run_heartbeat": {"failures": 0, "lease_losses": 0},
    }


def test_case_payload_uses_only_frozen_development_projection():
    assert {runner._case_payload(case_id)["id"] for case_id in ("P01", "P04", "P08")} == {
        "P01", "P04", "P08"
    }
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "product-baseline-v1.json" not in source
    assert all(f'"P{index:02d}"' not in source for index in range(9, 13))


def test_record_gate_accepts_only_complete_six_source_success(tmp_path: Path):
    snapshot = {
        "search_results": [
            {"source": source, "status": "success"}
            for source in ("tavily", "chroma", "github", "arxiv", "community", "official")
        ]
    }
    (tmp_path / "report.md").write_text("report", encoding="utf-8")
    (tmp_path / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    assert runner._record_stop_reason(_successful_record("P04"), tmp_path) is None


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"error_code": "HITL_REQUIRED_NO_AUTO_RESOLUTION",
          "status": "waiting_for_input"}, "CELL_NOT_SUCCESSFUL"),
        ({"hitl_resolutions": 1}, "HITL_AUTO_RESOLUTION_FORBIDDEN"),
        ({"observability_final": False}, "BUDGET_OR_CALL_OBSERVABILITY_ANOMALY"),
        ({"report_path": None}, "REPORT_OR_SNAPSHOT_MISSING"),
    ],
)
def test_record_gate_stops_on_hitl_unknown_or_incomplete(
    tmp_path: Path, change: dict, expected: str
):
    (tmp_path / "snapshot.json").write_text(
        json.dumps({"search_results": []}), encoding="utf-8"
    )
    (tmp_path / "report.md").write_text("report", encoding="utf-8")
    record = _successful_record("P04")
    record.update(change)
    assert runner._record_stop_reason(record, tmp_path) == expected


def test_record_gate_stops_on_source_or_budget_degradation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / "snapshot.json").write_text(
        json.dumps({"search_results": []}), encoding="utf-8"
    )
    (tmp_path / "report.md").write_text("report", encoding="utf-8")
    assert runner._record_stop_reason(_successful_record("P08"), tmp_path) == (
        "SOURCE_ENVELOPE_ANOMALY"
    )
    monkeypatch.setattr(o1_pr2b_control, "budget_anomaly", lambda record: True)
    assert runner._record_stop_reason(_successful_record("P08"), tmp_path) == (
        "BUDGET_OR_CALL_OBSERVABILITY_ANOMALY"
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda record: record["observability"].pop("totals"),
        lambda record: record["observability"]["totals"].update(
            token_usage_complete=False
        ),
        lambda record: record["observability"]["budget"]["resources"][
            "llm_calls"
        ].update(reserved=1),
        lambda record: record["observability"]["budget"]["resources"][
            "total_tokens"
        ].update(unknown_spend=1),
    ],
)
def test_record_gate_stops_on_incomplete_or_uncertain_usage(
    tmp_path: Path, mutate
):
    (tmp_path / "snapshot.json").write_text(
        json.dumps({"search_results": []}), encoding="utf-8"
    )
    (tmp_path / "report.md").write_text("report", encoding="utf-8")
    record = _successful_record("P08")
    mutate(record)
    assert runner._record_stop_reason(record, tmp_path) == (
        "BUDGET_OR_CALL_OBSERVABILITY_ANOMALY"
    )


def test_run_schedules_exact_frozen_twelve_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    protocol = _protocol()
    monkeypatch.setattr(
        runner, "_validate_execution_binding", lambda *args: (protocol, {})
    )
    monkeypatch.setattr(runner, "audit", lambda *args: _audit())
    monkeypatch.setattr(runner, "_claim_protocol_execution", lambda *args: None)
    observed: list[tuple[str, int, str]] = []

    async def fake_block(**kwargs):
        block = kwargs["block"]
        records = []
        for case_id in block["case_order"]:
            kwargs["before_admission"]()
            observed.append((block["arm"], block["repetition"], case_id))
            record = _successful_record(case_id)
            record.update(arm=block["arm"], repetition=block["repetition"])
            records.append(record)
        return records, None

    monkeypatch.setattr(runner, "_run_block", fake_block)
    result = asyncio.run(runner.run(tmp_path, tmp_path, tmp_path / "base",
                                    tmp_path / "candidate", tmp_path / ".env",
                                    "f" * 64))

    assert result["complete"] is True
    assert result["started_cells"] == result["planned_cells"] == 12
    assert len(observed) == len(set(observed)) == 12
    assert result["no_retries_or_splices"] is True


def test_run_latches_first_stop_and_preserves_denominator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    protocol = _protocol()
    monkeypatch.setattr(
        runner, "_validate_execution_binding", lambda *args: (protocol, {})
    )
    monkeypatch.setattr(runner, "audit", lambda *args: _audit())
    monkeypatch.setattr(runner, "_claim_protocol_execution", lambda *args: None)
    called: list[int] = []

    async def fake_block(**kwargs):
        called.append(kwargs["block"]["block"])
        block = kwargs["block"]
        case_id = block["case_order"][0]
        record = _successful_record(case_id)
        record.update(arm=block["arm"], repetition=block["repetition"])
        return [record], "ORDINARY_HTTP_5XX_STOP"

    monkeypatch.setattr(runner, "_run_block", fake_block)
    result = asyncio.run(runner.run(tmp_path, tmp_path, tmp_path / "base",
                                    tmp_path / "candidate", tmp_path / ".env",
                                    "f" * 64))

    assert called == [1]
    assert result["complete"] is False
    assert result["planned_cells"] == 12
    assert result["started_cells"] == 1
    assert sum(cell["status"] == "not_submitted" for cell in result["cells"]) == 11


def test_run_persists_denominator_when_block_control_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    protocol = _protocol()
    monkeypatch.setattr(
        runner, "_validate_execution_binding", lambda *args: (protocol, {})
    )
    monkeypatch.setattr(runner, "audit", lambda *args: _audit())
    monkeypatch.setattr(runner, "_claim_protocol_execution", lambda *args: None)

    async def fail_block(**kwargs):
        raise runner.RepairPairControlError("binding drift")

    monkeypatch.setattr(runner, "_run_block", fail_block)
    result = asyncio.run(runner.run(tmp_path, tmp_path, tmp_path / "base",
                                    tmp_path / "candidate", tmp_path / ".env",
                                    "f" * 64))

    assert result["complete"] is False
    assert result["planned_cells"] == 12
    assert result["started_cells"] == 0
    assert result["stop_reason"] == "CONTROL_RepairPairControlError"
    assert (tmp_path / "repair-pair-run-result.json").is_file()


def test_preflight_window_rejects_stale_or_future_evidence(tmp_path: Path):
    now = datetime.now(timezone.utc)
    path = tmp_path / "preflight-summary.json"
    path.write_text(json.dumps({"started_at": (now - timedelta(minutes=2)).isoformat(),
                                "ended_at": (now - timedelta(minutes=1)).isoformat()}),
                    encoding="utf-8")
    runner._validate_preflight_window(tmp_path, 7)

    path.write_text(json.dumps({"started_at": (now - timedelta(days=9)).isoformat(),
                                "ended_at": (now - timedelta(days=8)).isoformat()}),
                    encoding="utf-8")
    with pytest.raises(runner.RepairPairControlError, match="outside the frozen window"):
        runner._validate_preflight_window(tmp_path, 7)

    path.write_text(json.dumps({"started_at": now.isoformat(),
                                "ended_at": (now + timedelta(minutes=1)).isoformat()}),
                    encoding="utf-8")
    with pytest.raises(runner.RepairPairControlError, match="outside the frozen window"):
        runner._validate_preflight_window(tmp_path, 7)


def test_preflight_revalidation_rejects_llm_or_dependency_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    audit = _audit()
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    dependency_bytes = b"frozen-dependencies\n"
    dependency_hash = hashlib.sha256(dependency_bytes).hexdigest()
    audit["dependency_snapshot_sha256"] = dependency_hash
    now = datetime.now(timezone.utc)
    summary = {
        "passed": True,
        "research_runs_submitted": 0,
        "git_commit": audit["roots"]["candidate"]["anchor_commit"],
        "proxy_sha256": None,
        "endpoint_sha256": audit["endpoint_sha256"],
        "dependency_snapshot_sha256": dependency_hash,
        "configuration_sha256": "q" * 64,
        "started_at": (now - timedelta(minutes=2)).isoformat(),
        "ended_at": (now - timedelta(minutes=1)).isoformat(),
    }
    llm = {"passed": True}
    runner._write_json(tmp_path / "preflight-summary.json", summary)
    runner._write_json(tmp_path / "llm-preflight.json", llm)
    (tmp_path / "dependencies.json").write_bytes(dependency_bytes)
    binding = {
        "schema_version": 1,
        "protocol_byte_sha256": audit["protocol_byte_sha256"],
        "audit_sha256": hashlib.sha256(
            runner._signature(audit).encode("utf-8")
        ).hexdigest(),
        "audit": audit,
        "effective_environment_identity_sha256":
            audit["effective_environment_identity_sha256"],
        "preflight_summary_sha256": runner._file_hash(
            tmp_path / "preflight-summary.json"
        ),
        "llm_preflight_sha256": runner._file_hash(tmp_path / "llm-preflight.json"),
        "dependencies_sha256": dependency_hash,
        "research_runs_submitted": 0,
    }
    runner._write_json(tmp_path / "repair-pair-preflight-binding.json", binding)
    monkeypatch.setattr(
        runner, "_install_private_environment",
        lambda path: ({}, audit["effective_environment_identity_sha256"]),
    )
    monkeypatch.setattr(runner, "_dependency_snapshot_sha256", lambda: dependency_hash)
    from benchmarks import product_baseline_qualification as qualification
    monkeypatch.setattr(
        qualification, "trusted_configuration",
        lambda: SimpleNamespace(safe_fetch_proxy_sha256=None),
    )
    monkeypatch.setattr(qualification, "configuration_sha256", lambda cfg: "q" * 64)

    runner._validate_preflight(tmp_path, audit, env_file)
    runner._write_json(tmp_path / "llm-preflight.json", {"passed": True, "drift": True})
    with pytest.raises(runner.RepairPairControlError, match="prerequisite evidence invalid"):
        runner._validate_preflight(tmp_path, audit, env_file)
    runner._write_json(tmp_path / "llm-preflight.json", llm)
    (tmp_path / "dependencies.json").write_bytes(b"changed\n")
    with pytest.raises(runner.RepairPairControlError, match="prerequisite evidence invalid"):
        runner._validate_preflight(tmp_path, audit, env_file)

def test_health_requires_explicit_authority_lease_and_clean_heartbeat():
    good = {
        "runtime_instance": "active",
        "runtime_observations": {"authority_valid": True, "lease_remaining_ms": 1000},
        "run_heartbeat": {"failures": 0, "lease_losses": 0},
    }
    assert runner._health_safe(good) is True
    for mutation in (
        {"runtime_observations": None},
        {"runtime_observations": {"authority_valid": True}},
        {"runtime_observations": {"authority_valid": False, "lease_remaining_ms": 1000}},
        {"run_heartbeat": None},
        {"run_heartbeat": {"failures": 1, "lease_losses": 0}},
        {"run_heartbeat": {"failures": 0, "lease_losses": 1}},
    ):
        payload = {**good, **mutation}
        assert runner._health_safe(payload) is False


@pytest.mark.parametrize(
    "event",
    [
        {"event": "external_http_response", "operation": "other", "status_code": 200},
        {"event": "external_http_response", "operation": "official", "status_code": 429},
        {"event": "safe_fetch_failure", "status": "failure",
         "error_type": "UnsafeUrlError", "failure": "dns_uncertain"},
    ],
)
def test_strict_telemetry_stops_unknown_rate_limit_and_safety_failure(
    tmp_path: Path, event: dict, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "telemetry.jsonl"
    path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        o1_pr2b_control,
        "telemetry_state",
        lambda *args, **kwargs: {"anomaly": False, "reason": None},
    )
    state = runner._strict_telemetry_state(path)
    assert state["anomaly"] is True


def test_global_ledger_prevents_second_execution_or_cell_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(runner, "LEDGER_ROOT", tmp_path / "ledger")
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    (experiment / "execution-binding.json").write_text("{}\n", encoding="utf-8")
    binding = {"protocol_byte_sha256": "f" * 64}
    runner._claim_protocol_execution(experiment, binding)
    with pytest.raises(runner.RepairPairControlError, match="already attempted"):
        runner._claim_protocol_execution(experiment, binding)
    runner._reserve_cell("baseline", 2, "P04")
    with pytest.raises(runner.RepairPairControlError, match="already attempted"):
        runner._reserve_cell("baseline", 2, "P04")
    assert runner._ledger_summary() == {
        "attempted_cells": 1,
        "known_admitted_min": 0,
        "possibly_submitted_max": 1,
        "uncertain_cells": 1,
        "submission_count_uncertain": True,
    }


def test_artifact_paths_must_be_contained_regular_nonempty_files(tmp_path: Path):
    inside = tmp_path / "development/report.md"
    inside.parent.mkdir()
    inside.write_text("report", encoding="utf-8")
    assert runner._contained_artifact(
        tmp_path, "development/report.md", nonempty=True
    ) == inside.resolve()
    assert runner._contained_artifact(tmp_path, "../escape.md", nonempty=True) is None
    assert runner._contained_artifact(tmp_path, str(inside.resolve()), nonempty=True) is None

def test_prepare_makes_four_hash_identical_physical_seed_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    seed = tmp_path / "seed"
    (seed / "chroma").mkdir(parents=True)
    (seed / "chroma/chroma.sqlite3").write_bytes(b"database")
    (seed / "learned_docs.json").write_text("[]\n", encoding="utf-8")
    protocol = _protocol()
    protocol["knowledge_seed"]["artifact_tree_sha256"] = runner._tree_hash(seed)
    frozen = SimpleNamespace(payload=protocol, byte_sha256="f" * 64,
                             canonical_sha256="c" * 64)
    monkeypatch.setattr(runner, "SEED_ROOT", seed)
    monkeypatch.setattr(runner, "_load_approved_protocol", lambda value: frozen)
    monkeypatch.setattr(runner, "_bootstrap_approved_protocol", lambda value: protocol)
    dependencies = [["demo", "1"]]
    dependency_bytes = (json.dumps(dependencies, ensure_ascii=False, indent=2)
                        + "\n").encode()
    dependency_hash = hashlib.sha256(dependency_bytes).hexdigest()
    audit_value = _audit()
    audit_value["dependency_snapshot_sha256"] = dependency_hash
    monkeypatch.setattr(runner, "audit", lambda *args: audit_value)
    summary = {"dependency_snapshot_sha256": dependency_hash,
               "configuration_sha256": "q" * 64}
    cfg = SimpleNamespace(safe_fetch_proxy_sha256=None)
    monkeypatch.setattr(runner, "_validate_preflight",
                        lambda *args: (summary, cfg))
    from benchmarks import product_baseline_experiment, product_baseline_qualification
    monkeypatch.setattr(product_baseline_experiment, "embedding_revision",
                        lambda: protocol["environment"]["embedding_revision"])
    monkeypatch.setattr(product_baseline_qualification, "dependency_records",
                        lambda: dependencies)
    monkeypatch.setattr(product_baseline_qualification, "configuration_sha256",
                        lambda value: "q" * 64)
    preflight = tmp_path / "preflight"
    preflight.mkdir()
    (preflight / "dependencies.json").write_bytes(dependency_bytes)
    for name in ("llm-preflight.json", "preflight-summary.json",
                 "repair-pair-preflight-binding.json"):
        (preflight / name).write_text("{}\n", encoding="utf-8")
    experiment = tmp_path / "experiment"
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")

    result = runner.prepare(experiment, preflight, tmp_path / "base",
                            tmp_path / "candidate", env_file, "f" * 64)
    databases = list(experiment.glob("arms/*/r*/serial-r*/knowledge/chroma/chroma.sqlite3"))

    assert result["planned_cells"] == 12
    assert len(databases) == 4
    assert len({str(path.resolve()) for path in databases}) == 4
    assert all(path.read_bytes() == b"database" for path in databases)

    monkeypatch.setattr(runner, "_validate_preflight_window", lambda *args: None)
    databases[1].unlink()
    os.link(databases[0], databases[1])
    with pytest.raises(runner.RepairPairControlError, match="hard-linked"):
        runner._validate_execution_binding(
            experiment, preflight, tmp_path / "base", tmp_path / "candidate", env_file,
            "f" * 64,
        )
    databases[1].unlink()
    databases[1].write_bytes(b"database")

    binding_path = experiment / "execution-binding.json"
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    binding["blocks"] = []
    binding_path.write_text(json.dumps(binding), encoding="utf-8")
    with pytest.raises(runner.RepairPairControlError, match="execution block binding drift"):
        runner._validate_execution_binding(
            experiment, preflight, tmp_path / "base", tmp_path / "candidate", env_file,
            "f" * 64,
        )


def test_child_prioritizes_frozen_src_before_importing_product():
    source = runner.CHILD.read_text(encoding="utf-8")
    root_insert = source.index('sys.path.insert(0, str(frozen_root))')
    src_insert = source.index('sys.path.insert(0, str(frozen_root / "src"))')
    product_import = source.index("from deepchoice.outbound.tunnel import proxy_endpoint_identity")
    assert root_insert < src_insert < product_import
    assert 'parser.add_argument("--instance-nonce", required=True)' in source
    assert 'instance_nonce=args.instance_nonce' in source


def test_external_protocol_root_is_checked_before_project_import():
    import ast

    source = Path(runner.__file__).read_text(encoding="utf-8")
    module = ast.parse(source)
    bootstrap_index = next(
        index for index, node in enumerate(module.body)
        if isinstance(node, ast.FunctionDef) and node.name == "_load_approved_protocol"
    )
    assert not any(
        isinstance(node, ast.ImportFrom)
        and (node.module or "").startswith("benchmarks")
        for node in module.body[:bootstrap_index]
    )
    expected = runner._file_hash(runner.PROTOCOL_PATH)
    frozen = runner._load_approved_protocol(expected)
    assert frozen.byte_sha256 == expected
    with pytest.raises(runner.RepairPairControlError, match="identity mismatch"):
        runner._load_approved_protocol("0" * 64)


def test_audit_installs_private_environment_before_project_module_load():
    source = Path(runner.audit.__code__.co_filename).read_text(encoding="utf-8")
    audit_source = source[source.index("def audit("):source.index("def preflight(")]
    root_validation = audit_source.index("_validate_product_root")
    environment_install = audit_source.index("_install_private_environment")
    project_load = audit_source.index("_load_approved_protocol")
    qualification_import = audit_source.index(
        "from benchmarks import product_baseline_qualification"
    )
    assert root_validation < environment_install < project_load < qualification_import


def test_product_root_git_checks_are_scoped_to_approved_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    anchor = "a" * 40
    source_object = "b" * 40
    runtime_object = "c" * 40
    protocol = {
        "identities": {
            "baseline": {
                "anchor_commit": anchor,
                "source_objects": [
                    {"path": "src/deepchoice", "git_object": source_object}
                ],
                "runtime_objects": [
                    {"path": "benchmarks/__init__.py", "git_object": runtime_object}
                ],
            }
        },
        "controller": {"required_files": []},
    }
    git_calls: list[tuple[str, ...]] = []
    process_calls: list[list[str]] = []

    def fake_git(root: Path, *args: str) -> str:
        git_calls.append(args)
        if args == ("rev-parse", "HEAD"):
            return anchor
        if args == ("rev-parse", "HEAD:src/deepchoice"):
            return source_object
        if args == ("rev-parse", "HEAD:benchmarks/__init__.py"):
            return runtime_object
        if args[:3] == ("ls-files", "--others", "--exclude-standard"):
            return ""
        raise AssertionError(args)

    def fake_run(command: list[str], **kwargs):
        process_calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner, "_run_git", fake_git)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    runner._validate_product_root(tmp_path, "baseline", protocol)

    assert all("status" not in call for call in git_calls)
    [diff_call] = process_calls
    assert diff_call[3:7] == ["diff-index", "--quiet", "HEAD", "--"]
    assert diff_call[7:] == ["src/deepchoice", "benchmarks/__init__.py"]
    assert "product-baseline-v1.json" not in diff_call
    ls_call = next(call for call in git_calls if call[0] == "ls-files")
    assert ls_call[-2:] == ("src/deepchoice", "benchmarks/__init__.py")


def test_transport_and_tls_environment_changes_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1111")
    _, first = runner._private_environment(env_file)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:2222")
    _, second = runner._private_environment(env_file)
    assert first != second


def test_all_proxy_and_certificate_bundle_contents_change_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    bundle = (tmp_path / "ca.pem").resolve()
    bundle.write_text("certificate-one", encoding="utf-8")
    monkeypatch.setenv("SSL_CERT_FILE", str(bundle))
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1111")
    _, first = runner._private_environment(env_file)
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:2222")
    _, proxy_changed = runner._private_environment(env_file)
    bundle.write_text("certificate-two", encoding="utf-8")
    _, content_changed = runner._private_environment(env_file)
    assert first != proxy_changed != content_changed
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path))
    with pytest.raises(runner.RepairPairControlError, match="directories are unsupported"):
        runner._private_environment(env_file)


def test_import_shadow_is_rejected_before_project_import(tmp_path: Path):
    package = tmp_path / "benchmarks"
    package.mkdir()
    (package / "product_baseline_experiment.py").write_text("VALUE = 1\n", encoding="utf-8")
    (package / "product_baseline_experiment").mkdir()
    with pytest.raises(runner.RepairPairControlError, match="import shadow"):
        runner._reject_import_shadows(
            tmp_path, ["benchmarks/product_baseline_experiment.py"]
        )


@pytest.mark.parametrize(
    "bound_path,package_path",
    [
        ("benchmarks/__init__.py", "benchmarks"),
        ("src/deepchoice", "src/deepchoice"),
    ],
)
def test_extension_package_initializer_shadow_is_rejected(
    tmp_path: Path, bound_path: str, package_path: str
):
    package = tmp_path / package_path
    package.mkdir(parents=True)
    suffix = importlib.machinery.EXTENSION_SUFFIXES[0]
    (package / f"__init__{suffix}").write_bytes(b"shadow")
    with pytest.raises(runner.RepairPairControlError, match="import shadow"):
        runner._reject_import_shadows(tmp_path, [bound_path])


def test_owned_service_requires_started_event_with_same_nonce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    nonce = "a" * 32
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(
        json.dumps({"event": "telemetry_ready", "status": "success",
                    "instance_nonce": nonce}) + "\n",
        encoding="utf-8",
    )
    assert runner._telemetry_nonce_ready(telemetry, nonce) is False
    with telemetry.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": "service_started", "status": "success",
                                 "instance_nonce": nonce}) + "\n")
    assert runner._telemetry_nonce_ready(telemetry, nonce) is True
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "timeout=30, trust_env=False" in source
    assert "owned service unavailable before admission" in source


def test_vendor_endpoint_and_routing_identity_are_not_self_approved():
    protocol = _protocol()
    protocol["environment"].update({
        "endpoint_sha256": "e" * 64,
        "configuration_sha256": "c" * 64,
        "safe_fetch_proxy_sha256": "p" * 64,
    })
    probes = {
        arm: {"model_id": "deepseek-v4-flash", "endpoint_sha256": "e" * 64}
        for arm in ("baseline", "candidate")
    }
    runner._validate_approved_runtime_identity(
        protocol, probes, "c" * 64, "p" * 64
    )
    probes["candidate"]["endpoint_sha256"] = "x" * 64
    with pytest.raises(runner.RepairPairControlError, match="endpoint drift"):
        runner._validate_approved_runtime_identity(
            protocol, probes, "c" * 64, "p" * 64
        )
    probes["candidate"]["endpoint_sha256"] = "e" * 64
    with pytest.raises(runner.RepairPairControlError, match="routing or proxy drift"):
        runner._validate_approved_runtime_identity(
            protocol, probes, "z" * 64, "p" * 64
        )
