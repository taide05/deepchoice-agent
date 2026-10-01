from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
import hashlib
from pathlib import Path
import sqlite3

import httpx
import pytest

from benchmarks import quality_selection as q
from benchmarks import quality_selection_runtime as runtime



def audited_seed(path, monkeypatch):
    from deepchoice.retrievers import chroma_kb
    from deepchoice.utils.official_catalog import AUDITED_PRODUCT_SEED_IDENTITY
    (path / "chroma").mkdir(parents=True)
    with closing(sqlite3.connect(path / "chroma/chroma.sqlite3")) as db, db:
        db.execute("CREATE TABLE fixture (id INTEGER)")
    (path / "learned_docs.json").write_text("{}", encoding="utf-8")
    text = "Source statement. " * 33 + "Only with the stated prerequisite.\nAnother line."
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    doc_id = "fixture:" + text_hash[:16]
    metadata = {"target_id": "fixture", "url": "https://example.com/doc", "source_type": "official",
                "seed_identity_sha256": AUDITED_PRODUCT_SEED_IDENTITY}
    q.write_json(path / "chunks.json", [{"chunk_id": doc_id, "source_id": "fixture", "text_sha256": text_hash}])
    q.write_json(path / "seed-manifest.json", {"sources": [{"stable_id": "fixture", "url": metadata["url"],
                                                          "source_kind": "official"}]})
    monkeypatch.setattr(chroma_kb, "_AUDITED_CHUNKS_SHA256", q.file_digest(path / "chunks.json"))
    monkeypatch.setattr(chroma_kb, "_AUDITED_MANIFEST_SHA256", q.file_digest(path / "seed-manifest.json"))
    return text, metadata, doc_id

def initialize_ledger(tmp_path):
    proof = tmp_path / "reconciliation.json"
    evidence = tmp_path / "history-evidence.json"
    q.write_json(evidence, {"historical_admissions": 114, "fixture": True})
    q.write_json(proof, {"protocol": q.PROTOCOL, "used": 114, "new_protocol_admissions": 0,
                         "reviewed": True, "evidence_path": str(evidence),
                         "evidence_sha256": q.file_digest(evidence)})
    return q.ResearchLedger.initialize(tmp_path / "ledger.sqlite3", proof)


@pytest.fixture
def ledger(tmp_path):
    return initialize_ledger(tmp_path)


@pytest.fixture
def frozen(tmp_path, ledger):
    dataset = Path("benchmarks/quality-selection-development-v1.json").resolve()
    specs = [{"split": "development", "path": str(dataset), "sha256": q.DATASETS["development"][1]}]
    cases = q.load_cases(specs)
    environment = {"configuration_sha256": "c" * 64, "dependency_snapshot_sha256": "d" * 64,
                   "knowledge_sha256": "e" * 64, "embedding_revision": "a" * 40, "settings": {},
                   "model_id": "fixture", "endpoint_sha256": "f" * 64,
                   "tavily_state_path": str(tmp_path / "shared-state.json")}
    source_policy = {"holdout_reference_ingestion": False, "development_exposure": "fixture"}
    now = datetime.now(UTC)
    binding = {
        "schema_version": 1, "protocol": q.PROTOCOL, "phase": "baseline",
        "frozen_at": now.isoformat(), "valid_until": (now + timedelta(days=1)).isoformat(),
        "identity": {"production_commit": "a" * 40, "runner_commit": "b" * 40,
                     "core_asset_registry_id": "c" * 64, "environment_sha256": q.digest(environment),
                     "source_policy_sha256": q.digest(source_policy)},
        "environment": environment, "source_policy": source_policy,
        "datasets": specs, "stop_policy": q.STOP_POLICY, "run_limits": q.RUN_LIMITS,
        "starting_used": 114, "ledger_base_used": 114, "ledger_identity": ledger.identity,
        "cells": [{"cell_id": f"baseline-r1-{key}", "case_id": key, "repetition": 1,
                   "request_sha256": case["request_sha256"], "manifest_id": "a" * 64,
                   "hitl": {"action": "limited_report"}} for key, case in cases.items()],
    }
    path = tmp_path / "binding.json"
    q.write_json(path, binding)
    return binding, cases, path


def observation(status="completed"):
    return {"availability": "available", "run_failure_category":
            {"timed_out": "run_timeout", "cancelled": "cancelled", "failed": "unknown"}.get(status),
            "calls": [{"status": "succeeded", "failure_category": None}],
            "budget": {"availability": "available", "policy_version": "standard-enforced-v1",
                       "enforcement_mode": "enforced", "admission_denied": False,
                       "resources": {key: {"availability": "available", "hard_limit": value,
                                           "reserved": 0} for key, value in q.RUN_LIMITS.items()}}}


def record(status="completed"):
    return {"status": status, "observability": observation(status), "observability_final": True,
            "artifact_consistent": status in q.SUCCESS_STATUSES}


def test_original_requests_and_locked_holdout_boundary(frozen, tmp_path):
    binding, cases, path = frozen
    assert q.load_binding(path)[1] == cases
    assert list(cases) == ["P01", "P04", "P08", "P02"]
    assert all(q.digest(c["request"]) == c["request_sha256"] for c in cases.values())
    with pytest.raises(ValueError, match="holdout requires"):
        q.load_cases([{"split": "holdout", "path": str(tmp_path / "never-open.json")}])
    binding["datasets"][0]["sha256"] = "0" * 64
    q.write_json(path, binding)
    with pytest.raises(ValueError, match="dataset drift"):
        q.load_binding(path)


@pytest.mark.parametrize("change,match", [
    (lambda b: b["cells"].append(deepcopy(b["cells"][0])), "denominator"),
    (lambda b: b["cells"][1].update(cell_id=b["cells"][0]["cell_id"]), "cell identity"),
    (lambda b: b["cells"][0].update(repetition=2), "repetition"),
    (lambda b: b["cells"][0].update(request_sha256="0" * 64), "request/manifest"),
    (lambda b: b["cells"][0].update(hitl={"action": "provide_context"}), "context is missing"),
    (lambda b: b["identity"].update(environment_sha256="0" * 64), "metadata drift"),
    (lambda b: b.update(valid_until=(datetime.now(UTC) + timedelta(days=8)).isoformat()), "seven days"),
    (lambda b: b.update(starting_used=154), "hard cap"),
    (lambda b: b.update(ledger_base_used=0), "ledger binding"),
])
def test_binding_refuses_drift(frozen, change, match):
    binding, _, path = frozen
    change(binding)
    q.write_json(path, binding)
    with pytest.raises(ValueError, match=match):
        q.load_binding(path)


def test_comparison_reuses_original_inputs_and_window(frozen, tmp_path):
    baseline, _, original = frozen
    candidate = deepcopy(baseline)
    candidate["phase"] = "candidate"
    candidate["baseline_binding"] = {"path": str(original), "sha256": q.file_digest(original)}
    path = tmp_path / "candidate.json"
    q.write_json(path, candidate)
    assert q.load_binding(path)[0]["phase"] == "candidate"
    saved = candidate["environment"]["tavily_state_path"]
    candidate["environment"]["tavily_state_path"] = str(tmp_path / "reset-state.json")
    candidate["identity"]["environment_sha256"] = q.digest(candidate["environment"])
    q.write_json(path, candidate)
    with pytest.raises(ValueError, match="shared key-state path drift"):
        q.load_binding(path)
    candidate["environment"]["tavily_state_path"] = saved
    candidate["identity"]["environment_sha256"] = q.digest(candidate["environment"])
    candidate["cells"][0]["hitl"] = {"action": "cancel"}
    q.write_json(path, candidate)
    with pytest.raises(ValueError, match="request/HITL drift"):
        q.load_binding(path)


def test_synthetic_holdout_requires_review_and_preserves_full_matrix(frozen, tmp_path, monkeypatch):
    binding, cases, path = frozen
    # Synthetic shape only: never open the actual private holdout.
    fake = {"dataset_id": "synthetic", "version": "1.0.0", "status": "frozen", "protocol": q.PROTOCOL,
            "cases": [{"id": f"X{i}", "request": deepcopy(next(iter(cases.values()))["request"]),
                       "hitl": {"action": "limited_report"}} for i in range(4)]}
    dataset = tmp_path / "synthetic.json"
    q.write_json(dataset, fake)
    monkeypatch.setitem(q.DATASETS, "holdout", ("synthetic", q.file_digest(dataset)))
    baseline_path = tmp_path / "baseline-for-lock.json"
    q.write_json(baseline_path, binding)
    development_candidate = deepcopy(binding)
    development_candidate["phase"] = "candidate"
    development_candidate["baseline_binding"] = {"path": str(baseline_path), "sha256": q.file_digest(baseline_path)}
    candidate_path = tmp_path / "candidate-for-lock.json"
    q.write_json(candidate_path, development_candidate)
    binding["phase"] = "acceptance"
    binding["datasets"].append({"split": "holdout", "path": str(dataset), "sha256": q.file_digest(dataset)})
    q.write_json(path, binding)
    with pytest.raises(ValueError, match="candidate/review lock"):
        q.load_binding(path)
    lock = tmp_path / "review.json"
    q.write_json(lock, {"accepted": True, "candidate_commit": binding["identity"]["production_commit"],
                        "candidate_binding": {"path": str(candidate_path), "sha256": q.file_digest(candidate_path)}})
    binding["candidate_lock"] = {"production_commit": binding["identity"]["production_commit"],
                                 "path": str(lock), "development_review_sha256": q.file_digest(lock)}
    all_cases = q.load_cases(binding["datasets"], allow_holdout=True)
    binding["cells"] = [{"cell_id": f"r{rep}-{key}", "case_id": key, "repetition": rep,
                          "manifest_id": "a" * 64, "request_sha256": case["request_sha256"],
                          "hitl": {"action": "limited_report"}}
                         for rep in range(1, 4) for key, case in all_cases.items()]
    q.write_json(path, binding)
    assert len(q.load_binding(path)[0]["cells"]) == 24
    historical_start = binding["starting_used"]
    for current_start in (127, 131):
        binding["starting_used"] = current_start
        q.write_json(path, binding)
        with pytest.raises(ValueError, match="newly reviewed"):
            q.load_binding(path)
    binding["starting_used"] = historical_start
    q.write_json(path, binding)
    stable = deepcopy(binding)
    binding["source_policy"]["development_exposure"] = "changed"
    binding["identity"]["source_policy_sha256"] = q.digest(binding["source_policy"])
    q.write_json(path, binding)
    with pytest.raises(ValueError, match="comparison environment drift"):
        q.load_binding(path)
    binding = deepcopy(stable)
    binding["cells"][8]["hitl"] = {"action": "cancel"}
    q.write_json(path, binding)
    with pytest.raises(ValueError, match="HITL drift|HITL policy drift"):
        q.load_binding(path)
    binding = deepcopy(stable)
    binding["cells"][0], binding["cells"][8] = binding["cells"][8], binding["cells"][0]
    q.write_json(path, binding)
    with pytest.raises(ValueError, match="interleave"):
        q.load_binding(path)


def test_ledger_missing_or_rewound_database_fails_closed(ledger):
    assert ledger.used() == 114
    ledger.reserve("batch", "one", "baseline", expected_used=114)
    with closing(sqlite3.connect(ledger.path)) as db, db:
        db.execute("DELETE FROM admissions")
    with pytest.raises(ValueError, match="journal mismatch"):
        q.ResearchLedger(ledger.path)
    ledger.path.unlink()
    with pytest.raises(sqlite3.OperationalError):
        q.ResearchLedger(ledger.path)
    assert not ledger.path.exists()


def test_ledger_duplicate_stale_and_phase_cap(ledger):
    ledger.reserve("batch", "one", "baseline", expected_used=114)
    with pytest.raises(sqlite3.IntegrityError):
        ledger.reserve("batch", "one", "baseline", expected_used=115)
    with pytest.raises(ValueError, match="changed"):
        ledger.reserve("batch", "two", "baseline", expected_used=114)
    for i in range(3):
        ledger.reserve("batch", str(i), "baseline", expected_used=115 + i)
    with pytest.raises(ValueError, match="exhausted"):
        ledger.reserve("other", "one", "baseline", expected_used=118)
    assert ledger.used() == 118


def test_ledger_serializes_concurrent_claims(ledger):
    def claim(i):
        try:
            return ledger.reserve("batch", str(i), "baseline", expected_used=114)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(claim, range(8)))
    assert results.count(115) == 1
    assert ledger.used() == 115


def test_failed_db_commit_leaves_conservative_witness(ledger, monkeypatch):
    original = ledger._connect
    class FailedCommit:
        def __enter__(self):
            self.db = sqlite3.connect(ledger.path)
            return self.db
        def __exit__(self, *_):
            self.db.rollback()
            self.db.close()
            raise sqlite3.OperationalError("fixture commit failure")
    monkeypatch.setattr(ledger, "_connect", FailedCommit)
    with pytest.raises(sqlite3.OperationalError):
        ledger.reserve("batch", "one", "baseline", expected_used=114)
    monkeypatch.setattr(ledger, "_connect", original)
    with pytest.raises(ValueError, match="journal mismatch"):
        ledger.used()


@pytest.mark.parametrize("status", ["timed_out", "cancelled"])
def test_known_terminal_cancellation_is_runtime_failure(status):
    item = record(status)
    item["observability"]["calls"] = [{"status": "cancelled", "failure_category":
                                       {"timed_out": "run_timeout", "cancelled": "cancelled"}[status]}]
    assert q.classify_record(item) == ("runtime_failed", None)


@pytest.mark.parametrize("call", [
    {"status": "started"}, {"status": "cancelled"}, {}, {"status": "unknown"},
    {"status": "cancelled", "failure_category": "cancelled"},
    {"status": "failed", "failure_category": "budget_persistence_failed"},
])
def test_unclassified_or_authority_call_stops(call):
    item = record()
    item["observability"]["calls"] = [call]
    assert q.classify_record(item)[0] == "safety_stop"


@pytest.mark.parametrize("change", [
    lambda r: r.update(observability_final=False),
    lambda r: r.update(artifact_consistent=False),
    lambda r: r.update(error_code="FROZEN_MANIFEST_MISMATCH"),
    lambda r: r["observability"]["budget"].update(admission_denied=True),
    lambda r: r["observability"]["budget"]["resources"]["llm_calls"].update(reserved=1),
    lambda r: r["observability"]["budget"]["resources"].update(http_calls={"reserved": 1}),
])
def test_unverified_result_or_budget_stops(change):
    item = record()
    change(item)
    assert q.classify_record(item)[0] == "safety_stop"


def test_snapshot_degradation_is_visible_without_trace_failure():
    item = record()
    item["source_projection"] = q.source_projection({"partial_failures": ["fixture"],
        "search_results": [{"status": "failed", "error": "private error"}],
        "citation_verification": {"status_counts": {"unknown": 2, "verified": 3}}})
    assert q.classify_record(item) == ("source_or_model_degraded", None)
    assert "private error" not in json.dumps(item["source_projection"])
    assert item["source_projection"]["trace_completeness"] == "unknown-best-effort"
    assert q.classify_record(record()) == ("artifact_complete", None)


class FakeService:
    def __init__(self, binding, mode="success"):
        self.binding = binding
        self.mode = mode
        self.posts = []
        self.task_reads = {}
        self.resolutions = []

    async def __call__(self, request):
        path = request.url.path
        if path == "/evaluation/identity":
            value = "bad" if self.mode == "identity" else q.digest(self.binding)
            return httpx.Response(200, json={"binding_sha256": value})
        if path == "/health":
            return httpx.Response(200, json={"runtime_instance": "active",
                                            "runtime_observations": {"authority_valid": True}})
        if path == "/api/v1/tasks" and request.method == "POST":
            self.posts.append(json.loads(request.content))
            if self.mode == "uncertain":
                raise httpx.ReadTimeout("fixture private error")
            if self.mode == "cancel":
                raise asyncio.CancelledError()
            return httpx.Response(202, json=self.task(len(self.posts), "queued"))
        n = int(path.split("/")[4])
        if path.endswith("/observability"):
            item = observation()
            if self.mode == "budget":
                item["budget"]["admission_denied"] = True
            if self.mode == "ordinary":
                item["calls"] = [{"status": "failed", "failure_category": "provider_timeout"}]
            return httpx.Response(200, json=item)
        if path.endswith("/snapshot"):
            return httpx.Response(200, json={"report": "原始报告\n", "partial_failures": [], "search_results": []})
        if path.endswith("/report"):
            return httpx.Response(200, json={"report": "原始报告\n", "run_id": f"run-{n}"})
        if path.endswith("/export"):
            assert request.url.params["format"] == "md"
            return httpx.Response(200, content=("changed" if self.mode == "export" else "原始报告\n").encode())
        if path.endswith("/decision"):
            return httpx.Response(200, json={"decision_id": f"decision-{len(self.resolutions)}"})
        if "/decisions/" in path:
            self.resolutions.append((dict(request.headers), json.loads(request.content)))
            return httpx.Response(202, json={"replayed": False})
        self.task_reads[n] = self.task_reads.get(n, 0) + 1
        status = "waiting_for_input" if self.mode == "hitl" and len(self.resolutions) < 2 else "completed"
        return httpx.Response(200, json=self.task(n, status))

    def task(self, n, status):
        manifest = "b" * 64 if self.mode == "manifest" else self.binding["cells"][n - 1]["manifest_id"]
        return {"task": {"task_id": str(n), "status": status, "version": 2},
                "latest_run": {"run_id": f"run-{n}", "manifest_id": manifest}}


@pytest.mark.parametrize("mode,admitted,complete", [
    ("success", 4, 4), ("ordinary", 4, 4), ("identity", 0, 0),
    ("uncertain", 1, 0), ("manifest", 1, 0), ("budget", 1, 1), ("export", 1, 0),
])
async def test_serial_matrix_continuation_and_stops(frozen, ledger, tmp_path, mode, admitted, complete):
    binding, cases, _ = frozen
    service = FakeService(binding, mode)
    root = tmp_path / "batch"
    async with httpx.AsyncClient(transport=httpx.MockTransport(service), base_url="http://test") as client:
        result = await q.collect_batch(binding, cases, root, ledger, client)
        with pytest.raises((ValueError, FileExistsError)):
            await q.collect_batch(binding, cases, root, ledger, client)
    assert len(service.posts) == admitted
    assert result["admitted_or_uncertain"] == admitted
    assert result["completed_consistent"] == complete
    assert result["planned"] == len(result["cells"]) == 4
    assert result["quality_review"] == "not_evaluated"
    assert ledger.used() == 114 + admitted
    assert bool(result["stop_reason"]) == (mode not in {"success", "ordinary"})
    if admitted == 1:
        assert all(c["status"] == "not_submitted" for c in result["cells"][1:])
    if mode in {"success", "ordinary"}:
        assert [q.digest(p) for p in service.posts] == [c["request_sha256"] for c in binding["cells"]]
        for cell in result["cells"]:
            assert (root / cell["record_path"]).exists()


async def test_cancellation_keeps_claimed_cell_uncertain(frozen, ledger, tmp_path):
    binding, cases, _ = frozen
    root = tmp_path / "cancelled"
    service = FakeService(binding, "cancel")
    async with httpx.AsyncClient(transport=httpx.MockTransport(service), base_url="http://test") as client:
        with pytest.raises(asyncio.CancelledError):
            await q.collect_batch(binding, cases, root, ledger, client)
    matrix = json.loads((root / "matrix.json").read_text(encoding="utf-8"))
    assert matrix["admitted_or_uncertain"] == 1
    assert matrix["cells"][0]["status"] == "admitted_or_uncertain"
    assert matrix["cells"][0]["research_ordinal"] == 115
    assert all(c["status"] == "not_submitted" for c in matrix["cells"][1:])


async def test_fixed_hitl_body_cas_and_private_journal(frozen, ledger, tmp_path):
    binding, cases, _ = frozen
    binding["cells"][0]["hitl"] = {"action": "provide_context", "repeat_action": "limited_report",
                                  "supplemental_input": "固定上下文"}
    service = FakeService(binding, "hitl")
    root = tmp_path / "hitl"
    async with httpx.AsyncClient(transport=httpx.MockTransport(service), base_url="http://test") as client:
        result = await q.collect_batch(binding, cases, root, ledger, client)
    assert result["completed_consistent"] == 4
    assert [r[1] for r in service.resolutions] == [
        {"action": "provide_context", "supplemental_input": "固定上下文"}, {"action": "limited_report"}]
    assert all(r[0]["if-match"] == "2" for r in service.resolutions)
    for path in root.glob("cells/*/*.jsonl"):
        assert "固定上下文" not in path.read_text(encoding="utf-8")


def test_paid_collection_requires_explicit_switch(capsys):
    with pytest.raises(SystemExit):
        q.main(["collect", "--binding", "never-read.json"])
    assert "--execute-paid-runs" in capsys.readouterr().err


def test_configuration_preserves_limits_and_disables_reprobe(monkeypatch, tmp_path):
    from benchmarks import product_baseline_qualification
    marker = object()
    monkeypatch.setattr(product_baseline_qualification, "trusted_configuration", lambda: marker)
    monkeypatch.delenv("LLM_DS_CONCURRENCY", raising=False)
    monkeypatch.delenv("DEEPCHOICE_SYNTH_THINKING", raising=False)
    monkeypatch.setenv("TAVILY_KEY_STATE_PATH", str(tmp_path / "shared-state.json"))
    monkeypatch.setenv("TAVILY_REPROBE", "0")
    assert runtime._configure(None) is marker
    monkeypatch.setenv("TAVILY_REPROBE", "1")
    with pytest.raises(ValueError, match="exhausted-key"):
        runtime._configure(None)


def test_runtime_freeze_copies_seed_and_binds_clean_identities(frozen, tmp_path, monkeypatch):
    from benchmarks.product_baseline_experiment import tree_hash
    from benchmarks import product_baseline_qualification as qualification
    binding, _, _ = frozen
    runner = tmp_path / "runner"
    runner.mkdir()
    proof = tmp_path / "reconciliation.json"
    q.ResearchLedger.initialize(runner / "outputs/quality-selection-v1-ledger.sqlite3", proof)
    seed = tmp_path / "seed"
    audited_seed(seed, monkeypatch)
    environment = {**binding["environment"], "knowledge_root": str(seed), "knowledge_sha256": tree_hash(seed),
                   "knowledge_audit": runtime.audited_seed_identity(seed)}
    preflight = tmp_path / "preflight.json"
    q.write_json(preflight, {"ended_at": datetime.now(UTC).isoformat()})
    monkeypatch.setattr(runtime, "runner_root", lambda: runner)
    monkeypatch.setattr(runtime, "clean_commit", lambda _: "a" * 40)
    monkeypatch.setattr(runtime, "environment_identity", lambda *_: environment)
    monkeypatch.setattr(runtime, "_preflight_compatible", lambda path, _: json.loads(path.read_text()))
    spec = tmp_path / "spec.json"
    q.write_json(spec, {"phase": "baseline", "production_root": str(runner),
        "seed_path": str(seed), "seed_sha256": tree_hash(seed), "preflight_path": str(preflight),
        "source_policy": binding["source_policy"], "datasets": binding["datasets"],
        "hitl": {c["case_id"]: c["hitl"] for c in binding["cells"]}})
    destination = tmp_path / "prepared/binding.json"
    prepared = runtime.freeze(spec, destination, object())
    assert prepared["starting_used"] == 114
    assert prepared["identity"]["production_commit"] == "a" * 40
    assert prepared["identity"]["runner_commit"] == "a" * 40
    assert len(prepared["cells"]) == 4
    assert tree_hash(tmp_path / "prepared/knowledge") == tree_hash(seed)
    assert q.load_binding(destination)[0] == prepared
    with pytest.raises(ValueError, match="fresh"):
        runtime.freeze(spec, destination, object())
    # Use the real helper: the copied seed remains a valid stopped SQLite pair.
    with pytest.raises(ValueError):
        qualification.copy_frozen_seed(seed, tmp_path / "wrong-copy", "0" * 64)


def test_preflight_reuse_checks_bounds_age_environment_and_probe_code(tmp_path, monkeypatch):
    env = {k: "fixture" for k in ("configuration_sha256", "dependency_snapshot_sha256",
                                "model_id", "endpoint_sha256")}
    env["production_root"] = str(tmp_path)
    evidence = {**env, "passed": True, "llm_compatibility": True, "tavily_post_status": 200,
                "research_runs_submitted": 0, "llm_attempts": 2, "http_attempts": 5,
                "tavily_post_attempts": 1, "ended_at": datetime.now(UTC).isoformat(), "git_commit": "a" * 40}
    path = tmp_path / "preflight.json"
    q.write_json(path, evidence)
    def git(args, **kwargs):
        if "ls-files" in args:
            return "src/deepchoice/utils/llm.py\n"
        return b"" if "diff" in args else b"same probe"
    monkeypatch.setattr(runtime.subprocess, "check_output", git)
    assert runtime._preflight_compatible(path, env)["passed"]
    for key, value in [("llm_attempts", 5), ("research_runs_submitted", 1),
                       ("configuration_sha256", "drift"),
                       ("ended_at", (datetime.now(UTC) - timedelta(days=8)).isoformat())]:
        q.write_json(path, {**evidence, key: value})
        with pytest.raises(ValueError):
            runtime._preflight_compatible(path, env)
    q.write_json(path, evidence)
    monkeypatch.setattr(runtime.subprocess, "check_output", lambda args, **kwargs:
                        "src/deepchoice/utils/llm.py\n" if "ls-files" in args else args[-1].encode())
    with pytest.raises(ValueError, match="calling code changed"):
        runtime._preflight_compatible(path, env)


def test_knowledge_paths_must_precede_import(monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace
    monkeypatch.setenv("CHROMA_PATH", "fixture-before")
    monkeypatch.setenv("LEARNED_DOCS_PATH", "fixture-before")
    monkeypatch.setitem(sys.modules, "deepchoice.retrievers.learned_docs",
                        SimpleNamespace(LEARNED_DOCS_PATH=tmp_path / "old.json"))
    with pytest.raises(ValueError, match="before evaluation isolation"):
        runtime.set_knowledge_paths(tmp_path)
    monkeypatch.setitem(sys.modules, "deepchoice.retrievers.learned_docs",
                        SimpleNamespace(LEARNED_DOCS_PATH=tmp_path / "learned_docs.json"))
    runtime.set_knowledge_paths(tmp_path)


def test_serve_verifies_before_runtime_creation_and_never_restarts(frozen, tmp_path, monkeypatch):
    from fastapi import FastAPI
    from benchmarks import product_baseline_server
    import uvicorn
    binding, _, path = frozen
    binding["environment"]["knowledge_root"] = str(tmp_path / "knowledge")
    binding["identity"]["environment_sha256"] = q.digest(binding["environment"])
    q.write_json(path, binding)
    order = []
    monkeypatch.setattr(runtime, "set_knowledge_paths", lambda _: order.append("paths"))
    monkeypatch.setattr(runtime, "verify_runtime", lambda *_: order.append("verified"))
    monkeypatch.setattr(runtime, "verify_live_identity", lambda *_: None)
    monkeypatch.setattr(product_baseline_server, "create_app", lambda: FastAPI())
    def run(app, **kwargs):
        assert order[:2] == ["paths", "verified"]
        assert kwargs == {"host": "127.0.0.1", "port": 8765, "workers": 1}
        route = next(route for route in app.routes if route.path == "/evaluation/identity")
        assert asyncio.run(route.endpoint()) == {"binding_sha256": q.digest(binding)}
        def drift(*_):
            raise ValueError("fixture private detail")
        monkeypatch.setattr(runtime, "verify_live_identity", drift)
        response = asyncio.run(route.endpoint())
        assert response.status_code == 409 and b"private detail" not in response.body
    monkeypatch.setattr(uvicorn, "run", run)
    monkeypatch.setenv("DEEPCHOICE_EXPERIMENT_DIR", "fixture-before")
    runtime.serve(path, object(), 8765)
    assert (tmp_path / "runtime").is_dir()
    assert (tmp_path / "server-started.json").is_file()
    with pytest.raises(ValueError, match="no restart"):
        runtime.serve(path, object(), 8765)


def test_verify_runtime_rejects_runner_and_production_drift(frozen, monkeypatch):
    binding, cases, _ = frozen
    binding["environment"].update(production_root="fixture-production", runner_root=str(runtime.runner_root()))
    monkeypatch.setattr(runtime, "clean_commit", lambda _: "0" * 40)
    with pytest.raises(ValueError, match="runner identity"):
        runtime.verify_runtime(binding, cases, object())
    monkeypatch.setattr(runtime, "verify_runner", lambda _: None)
    with pytest.raises(ValueError, match="production identity"):
        runtime.verify_runtime(binding, cases, object())


def test_reconciliation_requires_real_matching_evidence(tmp_path):
    evidence = tmp_path / "history.json"
    q.write_json(evidence, {"fixture": True})
    proof = tmp_path / "bad-proof.json"
    q.write_json(proof, {"protocol": q.PROTOCOL, "used": 114, "new_protocol_admissions": 0,
                         "reviewed": True, "evidence_path": str(evidence), "evidence_sha256": "e" * 64})
    path = tmp_path / "ledger.sqlite3"
    with pytest.raises(ValueError, match="reconciliation evidence drift"):
        q.ResearchLedger.initialize(path, proof)
    assert not path.exists()


def test_expired_baseline_receipt_does_not_expire_legal_comparison(frozen, tmp_path):
    baseline, _, path = frozen
    now = datetime.now(UTC)
    baseline["frozen_at"] = (now - timedelta(days=2)).isoformat()
    baseline["valid_until"] = (now - timedelta(days=1)).isoformat()
    q.write_json(path, baseline)
    candidate = deepcopy(baseline)
    candidate.update(phase="candidate", frozen_at=now.isoformat(),
                     valid_until=(now + timedelta(days=1)).isoformat(),
                     baseline_binding={"path": str(path), "sha256": q.file_digest(path)})
    candidate_path = tmp_path / "candidate-current.json"
    q.write_json(candidate_path, candidate)
    assert q.load_binding(candidate_path)[0]["phase"] == "candidate"
    with pytest.raises(ValueError, match="outside its frozen window"):
        q.load_binding(path)
    candidate["identity"]["runner_commit"] = "f" * 40
    q.write_json(candidate_path, candidate)
    with pytest.raises(ValueError, match="runner drift"):
        q.load_binding(candidate_path)


def test_environment_identity_uses_loaded_code_and_shared_key_state(tmp_path, monkeypatch):
    import deepchoice
    from benchmarks import product_baseline_experiment as experiment
    from benchmarks import product_baseline_qualification as qualification
    production = Path(next(iter(deepchoice.__path__))).resolve().parents[1]
    seed = tmp_path / "seed"
    audited_seed(seed, monkeypatch)
    state = tmp_path / "shared-key-state.json"
    for key, value in {**experiment.RESOURCE_SETTINGS, "DEEPCHOICE_SYNTH_THINKING": "0",
                       "LLM_DS_CONCURRENCY": "80", "TAVILY_KEY_STATE_PATH": str(state)}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(experiment, "embedding_revision", lambda: "a" * 40)
    monkeypatch.setattr(qualification, "dependency_records", lambda: [("fixture", "1")])
    monkeypatch.setattr(qualification, "configuration_sha256", lambda _: "c" * 64)
    first = runtime.environment_identity(production, seed, object())
    assert first["tavily_state_path"] == str(state)
    assert first["tavily_state_sha256"] == "absent"
    q.write_json(state, {"exhausted": {"fixture-key-hash": 1}})
    second = runtime.environment_identity(production, seed, object())
    assert second["tavily_state_sha256"] == q.file_digest(state)
    assert first["knowledge_sha256"] == second["knowledge_sha256"]
    with pytest.raises(ValueError, match="loaded production"):
        runtime.environment_identity(tmp_path / "other-code", seed, object())


def test_audited_copy_preserves_real_retriever_window_and_identity(tmp_path, monkeypatch):
    from benchmarks.product_baseline_experiment import tree_hash
    from deepchoice.retrievers import chroma_kb
    seed, copy = tmp_path / "seed", tmp_path / "copy"
    text, metadata, doc_id = audited_seed(seed, monkeypatch)
    before = chroma_kb._load_audited_index(str(seed / "chroma"))
    assert len(before) == 1
    audit = runtime.copy_audited_seed(seed, copy, tree_hash(seed))
    after = chroma_kb._load_audited_index(str(copy / "chroma"))
    assert audit == runtime.audited_seed_identity(copy) and before == after
    assert tree_hash(seed) == tree_hash(copy)
    restored = chroma_kb._bounded_snippet(text, metadata, doc_id=doc_id, index=after)
    assert restored == text.split("\n")[0] and len(restored) > 500
    assert chroma_kb._bounded_snippet(text, metadata, doc_id=doc_id, index={}) == text[:500]


@pytest.mark.parametrize("fault", ["chunks.json", "seed-manifest.json", "tamper", "wal", "extra", "database", "link"])
def test_audited_copy_rejects_broken_runtime_seed_before_creating_output(tmp_path, monkeypatch, fault):
    from benchmarks.product_baseline_experiment import tree_hash
    seed, copy = tmp_path / "seed", tmp_path / "copy"
    audited_seed(seed, monkeypatch)
    if fault in {"chunks.json", "seed-manifest.json"}:
        (seed / fault).unlink()
    elif fault == "tamper":
        with (seed / "chunks.json").open("a") as handle:
            handle.write(" ")
    elif fault == "wal":
        (seed / "chroma/chroma.sqlite3-wal").write_bytes(b"pending")
    elif fault == "extra":
        (seed / "build-record.json").write_text("{}")
    elif fault == "database":
        (seed / "chroma/chroma.sqlite3").write_bytes(b"not SQLite")
    elif fault == "link":
        original = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda p: p == seed / "chroma" or original(p))
    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        runtime.copy_audited_seed(seed, copy, tree_hash(seed))
    assert not copy.exists()


def repair_binding(binding, tmp_path):
    original = tmp_path / "original-baseline.json"
    q.write_json(original, binding)
    incident = tmp_path / "incident.json"
    q.write_json(incident, {"research_used": 119, "old_roots_closed": True,
                           "original_audited_index_entries": 234, "prepared_audited_index_entries": 0})
    binding.update(phase="repair_baseline", starting_used=119, repair_purpose={"id": q.REPAIR_PURPOSE,
        "incident": {"path": str(incident), "sha256": q.file_digest(incident)},
        "original_baseline_binding": {"path": str(original), "sha256": q.file_digest(original)}})
    binding["environment"]["knowledge_audit"] = {"index_entries": 234}
    binding["identity"]["environment_sha256"] = q.digest(binding["environment"])
    return binding


def test_repair_binding_and_followup_bind_purpose_and_incident(frozen, tmp_path):
    baseline, _, path = frozen
    repair_binding(baseline, tmp_path)
    q.write_json(path, baseline)
    assert q.load_binding(path)[0]["phase"] == "repair_baseline"
    candidate = deepcopy(baseline)
    candidate.pop("repair_purpose")
    candidate.update(phase="followup", starting_used=123,
                     baseline_binding={"path": str(path), "sha256": q.file_digest(path)})
    target = tmp_path / "followup.json"
    q.write_json(target, candidate)
    assert q.load_binding(target)[0]["phase"] == "followup"
    candidate["phase"] = "candidate"
    q.write_json(target, candidate)
    with pytest.raises(ValueError, match="baseline binding"):
        q.load_binding(target)
    baseline["repair_purpose"]["id"] = "try-until-pass"
    q.write_json(path, baseline)
    with pytest.raises(ValueError, match="repair purpose"):
        q.load_binding(path)
    baseline["repair_purpose"]["id"] = q.REPAIR_PURPOSE
    q.write_json(path, baseline)
    (tmp_path / "incident.json").write_text("{}")
    with pytest.raises(ValueError, match="incident drift"):
        q.load_binding(path)


def test_one_repair_batch_never_refunds_old_calls_or_consumes_final_allocation(ledger):
    with pytest.raises(ValueError, match="reconciled batch"):
        ledger.reserve("repair", "early", "repair_baseline", expected_used=114)
    for i in range(4):
        ledger.reserve("old-baseline", str(i), "baseline", expected_used=114 + i)
    ledger.reserve("old-candidate", "one", "candidate", expected_used=118)
    ledger.reserve("repair", "one", "repair_baseline", expected_used=119)
    with pytest.raises(ValueError, match="one frozen batch"):
        ledger.reserve("different-repair", "two", "repair_baseline", expected_used=120)
    for i in range(3):
        ledger.reserve("repair", str(i), "repair_baseline", expected_used=120 + i)
    with pytest.raises(ValueError, match="exhausted"):
        ledger.reserve("repair", "fifth", "repair_baseline", expected_used=123)
    for i in range(4):
        ledger.reserve("followup", str(i), "followup", expected_used=123 + i)
    with pytest.raises(ValueError, match="incomplete"):
        ledger.reserve("acceptance", "old-lock", "acceptance", expected_used=127)
    for i in range(4):
        ledger.reserve("reviewed", str(i), "reviewed_candidate", expected_used=127 + i)
    for i in range(24):
        ledger.reserve("acceptance", str(i), "acceptance", expected_used=131 + i)
    assert ledger.used() == 155
    with closing(sqlite3.connect(ledger.path)) as db:
        assert db.execute("SELECT COUNT(*) FROM admissions WHERE batch LIKE 'old-%'").fetchone() == (5,)


@pytest.mark.parametrize("change", ["production", "request", "hitl", "manifest", "config"])
def test_repair_cannot_replace_the_original_control(frozen, tmp_path, change):
    binding, _, path = frozen
    repair_binding(binding, tmp_path)
    if change == "production":
        binding["identity"]["production_commit"] = "0" * 40
    elif change == "request":
        binding["cells"][0]["request_sha256"] = "0" * 64
    elif change == "hitl":
        binding["cells"][0]["hitl"] = {"action": "cancel"}
    elif change == "manifest":
        binding["cells"][0]["manifest_id"] = "0" * 64
    else:
        binding["environment"]["configuration_sha256"] = "0" * 64
        binding["identity"]["environment_sha256"] = q.digest(binding["environment"])
    q.write_json(path, binding)
    with pytest.raises(ValueError, match="drift"):
        q.load_binding(path)


def test_old_partly_used_phase_cannot_be_reallocated(ledger):
    ledger.reserve("closed-candidate", "one", "candidate", expected_used=114)
    with pytest.raises(ValueError, match="frozen batch"):
        ledger.require_unused_phase("candidate", 4)
    with pytest.raises(ValueError, match="one frozen batch"):
        ledger.reserve("new-candidate", "two", "candidate", expected_used=115)
    assert ledger.used() == 115


def fill_reviewed_history(ledger):
    for phase, count in (("baseline", 4), ("candidate", 1), ("repair_baseline", 4), ("followup", 4)):
        for index in range(count):
            ledger.reserve(phase, str(index), phase, expected_used=ledger.used())
    assert ledger.used() == 127


def reviewed_binding(frozen, tmp_path):
    baseline, cases, baseline_path = frozen
    repair_binding(baseline, tmp_path)
    q.write_json(baseline_path, baseline)
    candidate = deepcopy(baseline)
    candidate.pop("repair_purpose")
    auth = {"protocol": q.PROTOCOL, "phase": "reviewed_candidate", "approved": True,
            "starting_used": 127, "maximum_new_research_admissions": 4,
            "maximum_after_development": 131, "conditional_final_cells": 24,
            "maximum_with_final": 155, "ledger_identity_sha256": q.digest(candidate["ledger_identity"]),
            "case_order": ["P01", "P04", "P08", "P02"], "user_confirmation": "明确授权"}
    auth_path = tmp_path / "authorization.json"
    q.write_json(auth_path, auth)
    candidate.update(phase="reviewed_candidate", starting_used=127,
        comparison_mode="historical-baseline-different-collector-v1",
        baseline_binding={"path": str(baseline_path), "sha256": q.file_digest(baseline_path)},
        development_authorization={"path": str(auth_path), "sha256": q.file_digest(auth_path)})
    candidate["identity"]["runner_commit"] = "f" * 40
    path = tmp_path / "reviewed.json"
    q.write_json(path, candidate)
    return candidate, cases, path, auth_path


def test_reviewed_allocation_requires_exact_history_and_preserves_final24(ledger):
    with pytest.raises(ValueError, match="127-admission"):
        ledger.require_unused_phase("reviewed_candidate", 4)
    with pytest.raises(ValueError, match="127-admission"):
        ledger.reserve("reviewed", "early", "reviewed_candidate", expected_used=114)
    fill_reviewed_history(ledger)
    before = ledger.path.with_suffix(".admissions.jsonl").read_bytes()
    with pytest.raises(ValueError, match="incomplete"):
        ledger.require_unused_phase("acceptance", 24)
    ledger.require_unused_phase("reviewed_candidate", 4)
    def claim(i):
        try:
            return ledger.reserve("reviewed", str(i), "reviewed_candidate", expected_used=127)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(claim, range(8)))
    assert results.count(128) == 1
    with pytest.raises(ValueError, match="one frozen batch"):
        ledger.reserve("other", "other", "reviewed_candidate", expected_used=128)
    with pytest.raises(ValueError, match="frozen batch"):
        ledger.require_unused_phase("reviewed_candidate", 4)
    with pytest.raises(ValueError, match="incomplete"):
        ledger.require_unused_phase("acceptance", 24)
    with pytest.raises(ValueError, match="incomplete"):
        ledger.reserve("final", "premature", "acceptance", expected_used=128)
    for i in range(3):
        ledger.reserve("reviewed", f"next-{i}", "reviewed_candidate", expected_used=128+i)
    assert ledger.used() == 131
    with pytest.raises(ValueError, match="exhausted"):
        ledger.reserve("reviewed", "fifth", "reviewed_candidate", expected_used=131)
    for i in range(24):
        ledger.reserve("final", str(i), "acceptance", expected_used=131+i)
    assert ledger.used() == 155
    assert ledger.path.with_suffix(".admissions.jsonl").read_bytes().startswith(before)


@pytest.mark.parametrize("fault", ["missing", "tamper", "unapproved", "scope", "ledger", "order", "mode", "config", "hitl"])
def test_reviewed_binding_refuses_authorization_or_comparison_drift(frozen, tmp_path, fault):
    candidate, _, path, auth_path = reviewed_binding(frozen, tmp_path)
    assert q.load_binding(path)[0] == candidate
    if fault == "missing":
        candidate.pop("development_authorization")
    elif fault in {"tamper", "unapproved", "scope", "ledger"}:
        auth = json.loads(auth_path.read_text(encoding="utf-8"))
        if fault in {"tamper", "unapproved"}: auth["approved"] = False
        elif fault == "scope": auth["maximum_new_research_admissions"] = 5
        else: auth["ledger_identity_sha256"] = "0" * 64
        q.write_json(auth_path, auth)
        if fault != "tamper": candidate["development_authorization"]["sha256"] = q.file_digest(auth_path)
    elif fault == "order": candidate["cells"].reverse()
    elif fault == "mode": candidate["comparison_mode"] = "concurrent-paired"
    elif fault == "config":
        candidate["environment"]["configuration_sha256"] = "0" * 64
        candidate["identity"]["environment_sha256"] = q.digest(candidate["environment"])
    else: candidate["cells"][0]["hitl"] = {"action": "cancel"}
    q.write_json(path, candidate)
    with pytest.raises(ValueError):
        q.load_binding(path)


def test_reviewed_candidate_can_lock_but_acceptance_still_requires_same_runner(frozen, tmp_path):
    candidate, _, path, _ = reviewed_binding(frozen, tmp_path)
    review = tmp_path / "accepted.json"
    matrix = tmp_path / "closed-matrix.json"
    q.write_json(matrix, {"binding_sha256": q.digest(candidate), "state": "closed", "planned": 4,
        "admitted_or_uncertain": 4, "completed_consistent": 4, "stop_reason": None,
        "cells": [{"cell_id": c["cell_id"], "status": "completed"} for c in candidate["cells"]]})
    q.write_json(review, {"accepted": True, "candidate_commit": candidate["identity"]["production_commit"],
        "development_matrix": {"path": str(matrix), "sha256": q.file_digest(matrix)},
        "development_summary": {"usable_and_supported": 3, "critical_errors": 0,
                                "no_material_regression": True, "independent_review_passed": True},
        "candidate_binding": {"path": str(path), "sha256": q.file_digest(path)}})
    lock = {"path": str(review), "development_review_sha256": q.file_digest(review),
            "production_commit": candidate["identity"]["production_commit"]}
    assert q.load_candidate_lock(lock, candidate["identity"]["production_commit"]) == candidate
    changed = deepcopy(candidate)
    changed["identity"]["runner_commit"] = "e" * 40
    with pytest.raises(ValueError, match="runner drift"):
        q.verify_comparison(changed, candidate)


@pytest.mark.parametrize("mode,admitted", [("success", 4), ("uncertain", 1), ("budget", 1)])
async def test_reviewed_candidate_uses_real_ledger_and_existing_stop_contract(frozen, ledger, tmp_path, mode, admitted):
    fill_reviewed_history(ledger)
    candidate, cases, path, _ = reviewed_binding(frozen, tmp_path)
    candidate, _ = q.load_binding(path)
    service = FakeService(candidate, mode)
    async with httpx.AsyncClient(transport=httpx.MockTransport(service), base_url="http://test") as client:
        result = await q.collect_batch(candidate, cases, tmp_path / "reviewed-output", ledger, client)
    assert len(service.posts) == admitted and ledger.used() == 127 + admitted
    assert result["planned"] == 4 and result["quality_review"] == "not_evaluated"
    assert all(c["status"] == "not_submitted" for c in result["cells"][admitted:])


@pytest.mark.parametrize("fault", ["absent", "running", "short", "unsafe", "wrong-binding", "critical", "two-pass", "no-independent"])
def test_reviewed_promotion_refuses_incomplete_or_failed_evidence(frozen, tmp_path, fault):
    candidate, _, path, _ = reviewed_binding(frozen, tmp_path)
    matrix = {"binding_sha256": q.digest(candidate), "state": "closed", "planned": 4,
        "admitted_or_uncertain": 4, "completed_consistent": 4, "stop_reason": None,
        "cells": [{"cell_id": c["cell_id"], "status": "completed"} for c in candidate["cells"]]}
    summary = {"usable_and_supported": 3, "critical_errors": 0, "no_material_regression": True, "independent_review_passed": True}
    if fault == "running": matrix["state"] = "running"
    elif fault == "short": matrix["admitted_or_uncertain"] = 3
    elif fault == "unsafe": matrix["stop_reason"] = "BUDGET_STATE_UNVERIFIED"
    elif fault == "wrong-binding": matrix["binding_sha256"] = "0"*64
    elif fault == "critical": summary["critical_errors"] = 1
    elif fault == "two-pass": summary["usable_and_supported"] = 2
    elif fault == "no-independent": summary["independent_review_passed"] = False
    matrix_path = tmp_path / "matrix.json"
    q.write_json(matrix_path, matrix)
    review = {"accepted": True, "candidate_commit": candidate["identity"]["production_commit"],
              "candidate_binding": {"path": str(path), "sha256": q.file_digest(path)}, "development_summary": summary}
    if fault != "absent": review["development_matrix"] = {"path": str(matrix_path), "sha256": q.file_digest(matrix_path)}
    review_path = tmp_path / "review.json"
    q.write_json(review_path, review)
    lock = {"path": str(review_path), "development_review_sha256": q.file_digest(review_path), "production_commit": candidate["identity"]["production_commit"]}
    with pytest.raises(ValueError): q.load_candidate_lock(lock, candidate["identity"]["production_commit"])


def test_reviewed_runtime_freeze_checks_authorization_before_copy_and_roundtrips(frozen, tmp_path, monkeypatch):
    candidate, cases, _, auth_path = reviewed_binding(frozen, tmp_path)
    runner = tmp_path / "runner"
    runner.mkdir()
    new_ledger = q.ResearchLedger.initialize(runner / "outputs/quality-selection-v1-ledger.sqlite3", tmp_path / "reconciliation.json")
    fill_reviewed_history(new_ledger)
    auth = json.loads(auth_path.read_text(encoding="utf-8"))
    # Real execution reuses one ledger. Align this isolated runner fixture and baseline.
    baseline_path = Path(candidate["baseline_binding"]["path"])
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    original_path = Path(baseline["repair_purpose"]["original_baseline_binding"]["path"])
    original = json.loads(original_path.read_text(encoding="utf-8"))
    original["ledger_identity"] = new_ledger.identity
    q.write_json(original_path, original)
    baseline["ledger_identity"] = new_ledger.identity
    baseline["repair_purpose"]["original_baseline_binding"]["sha256"] = q.file_digest(original_path)
    q.write_json(baseline_path, baseline)
    auth["ledger_identity_sha256"] = q.digest(new_ledger.identity)
    q.write_json(auth_path, auth)
    environment = deepcopy(candidate["environment"])
    copies = []
    monkeypatch.setattr(runtime, "runner_root", lambda: runner)
    monkeypatch.setattr(runtime, "clean_commit", lambda _: "f" * 40)
    monkeypatch.setattr(runtime, "environment_identity", lambda *_: environment)
    monkeypatch.setattr(runtime, "_preflight_compatible", lambda *_: {"ended_at": datetime.now(UTC).isoformat()})
    monkeypatch.setattr(runtime, "copy_audited_seed", lambda *args: copies.append(args) or environment["knowledge_audit"])
    preflight = tmp_path / "preflight.json"
    q.write_json(preflight, {})
    spec = {"phase": "reviewed_candidate", "production_root": str(runner), "seed_path": str(tmp_path / "seed"),
        "seed_sha256": environment["knowledge_sha256"], "preflight_path": str(preflight),
        "source_policy": candidate["source_policy"], "datasets": candidate["datasets"],
        "hitl": {c["case_id"]: c["hitl"] for c in candidate["cells"]},
        "baseline_binding_path": str(baseline_path),
        "development_authorization": {"path": str(auth_path), "sha256": "0"*64}}
    spec_path = tmp_path / "spec.json"
    q.write_json(spec_path, spec)
    destination = tmp_path / "new-batch/binding.json"
    with pytest.raises(ValueError, match="authorization drift"):
        runtime.freeze(spec_path, destination, object())
    assert not copies and not destination.parent.exists()
    spec["development_authorization"]["sha256"] = q.file_digest(auth_path)
    q.write_json(spec_path, spec)
    result = runtime.freeze(spec_path, destination, object())
    assert len(copies) == 1 and result["starting_used"] == 127
    assert result["comparison_mode"] == "historical-baseline-different-collector-v1"
    assert q.load_binding(destination)[0] == result and new_ledger.used() == 127
