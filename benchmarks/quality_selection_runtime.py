"""Offline binding freeze and isolated local server for quality-selection-v1.

Private configuration is loaded before importing the pipeline. Neither command
runs prerequisites or research; collection is a separate explicit paid command.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess


def clean_commit(root: Path) -> str:
    status = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True)
    if status.strip():
        raise ValueError("frozen checkout must be clean")
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()


def runner_root() -> Path:
    return Path(__file__).resolve().parents[1]


def verify_runner(binding: dict) -> None:
    root = runner_root()
    if (str(root) != binding["environment"]["runner_root"]
            or clean_commit(root) != binding["identity"]["runner_commit"]):
        raise ValueError("runner identity drift")


def _configure(env_file: Path | None):
    from dotenv import load_dotenv
    if env_file is not None:
        load_dotenv(env_file, override=False)
    from benchmarks.product_baseline_qualification import trusted_configuration
    os.environ.setdefault("DEEPCHOICE_SYNTH_THINKING", "0")
    os.environ.setdefault("LLM_DS_CONCURRENCY", "80")
    os.environ["TAVILY_KEY_STATE_PATH"] = str(Path(os.getenv("TAVILY_KEY_STATE_PATH", "tavily_key_state.json")).resolve())
    if os.getenv("TAVILY_REPROBE", "0") != "0":
        raise ValueError("evaluation must preserve exhausted-key state")
    return trusted_configuration()


def set_knowledge_paths(knowledge: Path) -> None:
    os.environ.update(CHROMA_PATH=str(knowledge / "chroma"),
                      LEARNED_DOCS_PATH=str(knowledge / "learned_docs.json"))
    # Import-time path constants cannot safely be repaired after loading.
    import sys
    learned = sys.modules.get("deepchoice.retrievers.learned_docs")
    if learned is not None and learned.LEARNED_DOCS_PATH.resolve() != (knowledge / "learned_docs.json").resolve():
        raise ValueError("knowledge configuration was loaded before evaluation isolation")


def environment_identity(production_root: Path, knowledge: Path, cfg) -> dict:
    import deepchoice
    from benchmarks.product_baseline_experiment import RESOURCE_SETTINGS, embedding_revision, tree_hash
    from benchmarks.product_baseline_qualification import configuration_sha256, dependency_records
    from deepchoice.utils.llm import TIERS
    actual = Path(next(iter(deepchoice.__path__))).resolve()
    if actual != (production_root / "src/deepchoice").resolve():
        raise ValueError("loaded production code differs from the frozen checkout")
    settings = {**RESOURCE_SETTINGS, "DEEPCHOICE_SYNTH_THINKING": "0",
                "LLM_DS_CONCURRENCY": os.getenv("LLM_DS_CONCURRENCY", "80")}
    if any(os.getenv(k) != v for k, v in settings.items()):
        raise ValueError("runtime resource settings drift")
    dependencies = (json.dumps(dependency_records(), ensure_ascii=False, indent=2) + "\n").encode()
    model = TIERS["deepseek-flash"]
    state_path = Path(os.environ["TAVILY_KEY_STATE_PATH"])
    if not state_path.is_absolute():
        raise ValueError("shared exhausted-key state must use an absolute path")
    return {
        "production_root": str(production_root.resolve()), "runner_root": str(runner_root()),
        "configuration_sha256": configuration_sha256(cfg),
        "dependency_snapshot_sha256": hashlib.sha256(dependencies).hexdigest(),
        "knowledge_root": str(knowledge.resolve()), "knowledge_sha256": tree_hash(knowledge),
        "embedding_revision": embedding_revision(), "settings": settings,
        "tavily_state_path": str(state_path),
        "tavily_state_sha256": hashlib.sha256(state_path.read_bytes()).hexdigest() if state_path.exists() else "absent",
        "model_id": model["model"], "endpoint_sha256": hashlib.sha256(model["base"].encode()).hexdigest(),
    }


def _preflight_compatible(path: Path, environment: dict) -> dict:
    from benchmarks.quality_selection import _require, _time
    evidence = json.loads(path.read_text(encoding="utf-8"))
    _require(evidence.get("passed") is True and evidence.get("llm_compatibility") is True
             and evidence.get("tavily_post_status") == 200 and evidence.get("research_runs_submitted") == 0,
             "bounded prerequisite evidence is not ready")
    for key in ("configuration_sha256", "dependency_snapshot_sha256", "model_id", "endpoint_sha256"):
        _require(evidence.get(key) == environment[key], "prerequisite environment drift")
    for key, limit in (("llm_attempts", 4), ("http_attempts", 20), ("tavily_post_attempts", 1)):
        _require(type(evidence.get(key)) is int and 0 < evidence[key] <= limit, "invalid prerequisite count")
    _require(0 <= (datetime.now(UTC) - _time(evidence["ended_at"])).total_seconds() < 7 * 86400,
             "prerequisite evidence expired")
    # Probe code compatibility, independent of synthesis prompt/report changes.
    root = Path(environment["production_root"])
    old_commit = evidence["git_commit"]
    files = subprocess.check_output(["git", "-C", str(root), "ls-files",
        "src/deepchoice/outbound", "src/deepchoice/utils/llm.py",
        "src/deepchoice/retrievers/tavily_keypool.py", "benchmarks/product_baseline_preflight.py",
        "benchmarks/product_baseline_qualification.py"], text=True).splitlines()
    _require(bool(files), "prerequisite source inventory is missing")
    _require(not subprocess.check_output(["git", "-C", str(root), "diff", "--name-only",
                 old_commit, "HEAD", "--", "src/deepchoice/outbound", "src/deepchoice/utils/llm.py",
                 "src/deepchoice/retrievers/tavily_keypool.py", "benchmarks/product_baseline_preflight.py",
                 "benchmarks/product_baseline_qualification.py"]).strip(), "prerequisite calling code changed")
    for relative in files:
        before = subprocess.check_output(["git", "-C", str(root), "show", f"{old_commit}:{relative}"])
        # Compare Git blobs; checkout CRLF must not look like a behavior change.
        current = subprocess.check_output(["git", "-C", str(root), "show", f"HEAD:{relative}"])
        _require(before == current, "prerequisite calling code changed")
    return evidence


def freeze(spec_path: Path, destination: Path, cfg) -> dict:
    from benchmarks.product_baseline_qualification import copy_frozen_seed
    from benchmarks.quality_selection import (
        BASE_USED, PHASE_LIMITS, PROTOCOL, RUN_LIMITS, STOP_POLICY, ResearchLedger,
        _require, _time, digest, file_digest, load_binding, load_cases, write_json,
        load_candidate_lock, verify_comparison,
    )
    from deepchoice.contracts.api import ResearchRequest
    from deepchoice.contracts.manifest import build_core_asset_registry, build_run_manifest
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    phase = spec["phase"]
    _require(phase in PHASE_LIMITS, "invalid phase")
    production = Path(spec["production_root"]).resolve()
    commit = clean_commit(production)
    runner_commit = clean_commit(runner_root())
    lock = None
    if phase == "acceptance":
        lock_path = Path(spec["candidate_lock_path"])
        lock_value = json.loads(lock_path.read_text(encoding="utf-8"))
        _require(lock_value.get("accepted") is True and lock_value.get("candidate_commit") == commit,
                 "development review has not locked this candidate")
        lock = {"production_commit": commit, "development_review_sha256": file_digest(lock_path),
                "path": str(lock_path.resolve())}
    _require(not destination.exists() and not destination.parent.exists(), "binding directory must be fresh")
    seed = Path(spec["seed_path"]).resolve()
    # Validate before creating the destination or touching the stopped seed.
    source_environment = environment_identity(production, seed, cfg)
    preflight_path = Path(spec["preflight_path"]).resolve()
    preflight = _preflight_compatible(preflight_path, source_environment)
    _require(source_environment["knowledge_sha256"] == spec["seed_sha256"], "frozen seed drift")
    source_policy = spec["source_policy"]
    _require(isinstance(source_policy, dict) and source_policy.get("holdout_reference_ingestion") is False
             and isinstance(source_policy.get("development_exposure"), str)
             and bool(source_policy["development_exposure"]), "source policy disclosure is required")
    if lock is not None:
        candidate = load_candidate_lock(lock, commit)
        verify_comparison({"identity": {"runner_commit": runner_commit},
                           "environment": source_environment, "source_policy": source_policy}, candidate)
    # Environment and review lock are checked before exposing holdout inputs.
    cases = load_cases(spec["datasets"], allow_holdout=lock is not None)
    destination.parent.mkdir(parents=True)
    knowledge = destination.parent / "knowledge"
    copy_frozen_seed(seed, knowledge, spec["seed_sha256"])
    environment = {**source_environment, "knowledge_root": str(knowledge.resolve())}
    ledger = ResearchLedger(runner_root() / "outputs/quality-selection-v1-ledger.sqlite3")
    started = datetime.now(UTC)
    until = min(started + timedelta(days=7), _time(preflight["ended_at"]) + timedelta(days=7))
    binding = {
        "schema_version": 1, "protocol": PROTOCOL, "phase": phase,
        "frozen_at": started.isoformat(), "valid_until": until.isoformat(),
        "identity": {"production_commit": commit, "runner_commit": runner_commit,
                     "core_asset_registry_id": build_core_asset_registry().registry_id,
                     "environment_sha256": digest(environment), "source_policy_sha256": digest(source_policy)},
        "environment": environment, "source_policy": source_policy,
        "preflight": {"path": str(preflight_path), "sha256": file_digest(preflight_path)},
        "datasets": spec["datasets"], "candidate_lock": lock, "run_limits": RUN_LIMITS,
        "stop_policy": STOP_POLICY, "starting_used": ledger.used(), "ledger_base_used": BASE_USED,
        "ledger_identity": ledger.identity, "cells": [],
    }
    order = list(cases)
    if phase == "acceptance":
        development = [key for key in order if cases[key]["split"] == "development"]
        holdout = [key for key in order if cases[key]["split"] == "holdout"]
        order = [key for pair in zip(development, holdout) for key in pair]
    for rep in range(1, 4 if phase == "acceptance" else 2):
        rotated = order[rep - 1:] + order[:rep - 1]
        for key in rotated:
            case = cases[key]
            hitl = case["hitl"] or spec["hitl"][key]
            binding["cells"].append({
                "cell_id": f"{phase}-r{rep}-{key}", "case_id": key, "repetition": rep,
                "request_sha256": case["request_sha256"],
                "manifest_id": build_run_manifest(ResearchRequest.model_validate(case["request"]).model_dump(exclude_none=True)).manifest_id,
                "hitl": hitl,
            })
    if phase in {"candidate", "followup"}:
        baseline_path = Path(spec["baseline_binding_path"]).resolve()
        binding["baseline_binding"] = {"path": str(baseline_path), "sha256": file_digest(baseline_path)}
    write_json(destination, binding, exclusive=True)
    load_binding(destination)
    return binding


def verify_runtime(binding: dict, cases: dict, cfg) -> None:
    from benchmarks.quality_selection import _require, digest, file_digest
    from deepchoice.contracts.api import ResearchRequest
    from deepchoice.contracts.manifest import build_core_asset_registry, build_run_manifest
    verify_runner(binding)
    frozen = binding["environment"]
    root = Path(frozen["production_root"])
    _require(clean_commit(root) == binding["identity"]["production_commit"], "production identity drift")
    current = environment_identity(root, Path(frozen["knowledge_root"]), cfg)
    _require(current == frozen and digest(current) == binding["identity"]["environment_sha256"], "environment drift")
    evidence_path = Path(binding["preflight"]["path"])
    _require(file_digest(evidence_path) == binding["preflight"]["sha256"], "prerequisite receipt drift")
    _preflight_compatible(evidence_path, current)
    _require(build_core_asset_registry().registry_id == binding["identity"]["core_asset_registry_id"], "asset drift")
    for cell in binding["cells"]:
        request = ResearchRequest.model_validate(cases[cell["case_id"]]["request"]).model_dump(exclude_none=True)
        _require(build_run_manifest(request).manifest_id == cell["manifest_id"], "request manifest drift")


def verify_live_identity(binding: dict, cfg) -> None:
    from benchmarks.quality_selection import _require
    from benchmarks.product_baseline_qualification import configuration_sha256
    from deepchoice.contracts.manifest import build_core_asset_registry
    verify_runner(binding)
    _require(clean_commit(Path(binding["environment"]["production_root"])) == binding["identity"]["production_commit"],
             "production identity drift")
    _require(configuration_sha256(cfg) == binding["environment"]["configuration_sha256"]
             and build_core_asset_registry().registry_id == binding["identity"]["core_asset_registry_id"],
             "live environment/asset drift")


def serve(binding_path: Path, cfg, port: int) -> None:
    raw = json.loads(binding_path.read_text(encoding="utf-8"))
    set_knowledge_paths(Path(raw["environment"]["knowledge_root"]))
    from benchmarks.quality_selection import digest, load_binding, write_json
    binding, cases = load_binding(binding_path)
    verify_runtime(binding, cases, cfg)
    directory = binding_path.parent
    runtime = directory / "runtime"
    if runtime.exists():
        raise ValueError("runtime directory must be fresh; no restart of a stopped experiment")
    runtime.mkdir()
    write_json(directory / "server-started.json", {"pid": os.getpid(), "binding_sha256": digest(binding)}, exclusive=True)
    knowledge = Path(binding["environment"]["knowledge_root"])
    set_knowledge_paths(knowledge)
    os.environ["DEEPCHOICE_EXPERIMENT_DIR"] = str(runtime)
    from benchmarks.product_baseline_server import create_app
    import uvicorn
    app = create_app()

    async def identity():
        import asyncio
        from fastapi.responses import JSONResponse
        try:
            await asyncio.to_thread(verify_live_identity, binding, cfg)
        except (ValueError, OSError, subprocess.SubprocessError):
            return JSONResponse({"error": "EVALUATION_IDENTITY_DRIFT"}, status_code=409)
        return {"binding_sha256": digest(binding)}

    app.add_api_route("/evaluation/identity", identity, methods=["GET"], include_in_schema=False)
    uvicorn.run(app, host="127.0.0.1", port=port, workers=1)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init-ledger", "freeze", "serve"])
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--reconciliation", type=Path)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if args.command == "init-ledger":
        if args.reconciliation is None:
            parser.error("init-ledger requires --reconciliation")
        from benchmarks.quality_selection import ResearchLedger
        ledger = ResearchLedger.initialize(runner_root() / "outputs/quality-selection-v1-ledger.sqlite3",
                                           args.reconciliation)
        print(json.dumps({"used": ledger.used(), "research_submitted": 0}))
        return 0
    if args.binding is None:
        parser.error("--binding is required")
    if args.command == "serve":
        raw = json.loads(args.binding.read_text(encoding="utf-8"))
        set_knowledge_paths(Path(raw["environment"]["knowledge_root"]))
        os.environ["TAVILY_KEY_STATE_PATH"] = raw["environment"]["tavily_state_path"]
    elif args.spec is not None:
        raw = json.loads(args.spec.read_text(encoding="utf-8"))
        set_knowledge_paths(Path(raw["seed_path"]).resolve())
    cfg = _configure(args.env_file)
    if args.command == "freeze":
        if args.spec is None:
            parser.error("freeze requires --spec")
        binding = freeze(args.spec, args.binding, cfg)
        print(json.dumps({"phase": binding["phase"], "cells": len(binding["cells"]), "research_submitted": 0}))
    else:
        serve(args.binding, cfg, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
