"""Prepare fresh PR2 profiles with the tracked PR2A control-chain identity."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from dotenv import load_dotenv

EXPECTED_COMMIT = "7d622fd4916dad950ca077924327647a1f8f12c0"
EXPECTED_DATASET = "e0317ddeaa2b37526f5a7261d8df26217b75619d6c46bcd1bc8705895f16981f"
EXPECTED_KNOWLEDGE = "e55ddcac30d0e498c6e5ae02cb40d1bae95eb2831fda71e924ed9211b76466e4"
EXPECTED_DEPENDENCIES = "c07764a225a2eef37b2ee47dacdd1dec0efac5cd263c4522b5c121c50a40493b"
EXPECTED_CONFIGURATION = "4240dcd933e728eff05ea91d27cc5a57056c6c87404d20fa3b946cef50d9c474"
EXPECTED_ENDPOINT = "12b8deaccc34b32757dbb1497e029da0c2e7b26ffa86b9c926c08cb4692f4508"
EXPECTED_PROXY = "813477bf51a0efb3b5926c3759f01d02cdf25cd70e6cfc7fa186d9d5e1e1d118"
EXPECTED_EMBEDDING_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
EXPECTED_MANIFEST_BY_CASE = {"P01": "3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a", "P02": "4374d25d239cdc5891453a3785479c91bc52cf272db5c0e32b11c5a755eed563", "P03": "3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a", "P04": "e7389bdbe64920fa7d00879e4de449498b945ce16c548f1341d4f2ec4adbaef6", "P05": "e7389bdbe64920fa7d00879e4de449498b945ce16c548f1341d4f2ec4adbaef6", "P06": "4374d25d239cdc5891453a3785479c91bc52cf272db5c0e32b11c5a755eed563", "P07": "3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a", "P08": "3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a", "P09": "4374d25d239cdc5891453a3785479c91bc52cf272db5c0e32b11c5a755eed563", "P10": "e7389bdbe64920fa7d00879e4de449498b945ce16c548f1341d4f2ec4adbaef6", "P11": "4374d25d239cdc5891453a3785479c91bc52cf272db5c0e32b11c5a755eed563", "P12": "3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a"}
EXPECTED_ASSET_REGISTRY = "15cb66f6602a7f36090c1337f983ecbdbb3c74e77d7c9ca52c6c3c5ba799c850"
PROFILES = ("serial-r1", "concurrent-r1", "concurrent-r2", "serial-r2")
PR2A_CONTROL_CHAIN = (
    "o1_pr2a_prepare.py",
    "o1_pr2a_child.py",
    "o1_pr2a_control.py",
)

def _main(root: Path, preflight: Path, seed: Path, expected: str,
          frozen_root: Path, env_file: Path) -> dict:
    if root.exists():
        raise ValueError("experiment root must be fresh")
    if not env_file.is_file():
        raise ValueError("private environment is unavailable")
    load_dotenv(env_file, override=False)
    os.chdir(frozen_root)
    sys.path.insert(0, str(frozen_root))
    from benchmarks import product_baseline_qualification as qualification
    from benchmarks.product_baseline import load_dataset, load_environment
    from benchmarks.product_baseline_experiment import RESOURCE_SETTINGS, embedding_revision, tree_hash
    from deepchoice.contracts.api import ResearchRequest
    from deepchoice.contracts.manifest import build_core_asset_registry, build_run_manifest
    from deepchoice.utils.llm import TIERS
    tool_directory = Path(__file__).resolve().parent
    tool_hashes = {
        name: qualification.file_hash(tool_directory / name)
        for name in PR2A_CONTROL_CHAIN
    }
    cfg = qualification.trusted_configuration()
    if expected != EXPECTED_KNOWLEDGE:
        raise ValueError("CLI knowledge identity differs from the frozen PR1 value")
    if qualification.git_identity() != EXPECTED_COMMIT:
        raise ValueError("frozen candidate identity changed")
    evidence = json.loads((preflight / "preflight-summary.json").read_text(encoding="utf-8"))
    llm_path = preflight / "llm-preflight.json"
    llm = json.loads(llm_path.read_text(encoding="utf-8"))
    model = TIERS["deepseek-flash"]
    dependencies = qualification.dependency_records()
    dependency_bytes = (json.dumps(dependencies, ensure_ascii=False, indent=2) + "\n").encode()
    dependency_hash = hashlib.sha256(dependency_bytes).hexdigest()
    endpoint_hash = hashlib.sha256(model["base"].encode()).hexdigest()
    configuration_hash = qualification.configuration_sha256(cfg)
    registry_id = build_core_asset_registry().registry_id
    if (dependency_hash != EXPECTED_DEPENDENCIES
            or configuration_hash != EXPECTED_CONFIGURATION
            or endpoint_hash != EXPECTED_ENDPOINT
            or cfg.safe_fetch_proxy_sha256 != EXPECTED_PROXY
            or embedding_revision() != EXPECTED_EMBEDDING_REVISION
            or registry_id != EXPECTED_ASSET_REGISTRY):
        raise ValueError("frozen PR1 environment identity changed")
    if (not evidence.get("passed") or evidence.get("git_commit") != EXPECTED_COMMIT
            or evidence.get("proxy_sha256") != cfg.safe_fetch_proxy_sha256
            or evidence.get("dependency_snapshot_sha256") != dependency_hash
            or qualification.file_hash(preflight / "dependencies.json") != dependency_hash
            or evidence.get("configuration_sha256") != configuration_hash
            or evidence.get("model_id") != model["model"]
            or evidence.get("endpoint_sha256") != endpoint_hash
            or not llm.get("passed") or llm.get("model_id") != model["model"]):
        raise ValueError("same-candidate prerequisite evidence required")
    root.mkdir(parents=True)
    knowledge_seed = root / "knowledge-seed"
    knowledge_hash = qualification.copy_frozen_seed(seed, knowledge_seed, expected)
    for profile in PROFILES:
        profile_root = root / profile
        shutil.copytree(knowledge_seed, profile_root / "knowledge")
        if tree_hash(profile_root / "knowledge") != knowledge_hash:
            raise ValueError("profile knowledge copy changed")
        (profile_root / "runtime").mkdir()
        (profile_root / "control").mkdir()
    qualification.write_json(root / "dependencies.json", dependencies)
    dataset, dataset_hash = load_dataset(
        frozen_root / "benchmarks/product-baseline-v1.json", require_frozen=True)
    manifest_by_case = {
        case["id"]: build_run_manifest(
            ResearchRequest.model_validate(case["request"]).model_dump(exclude_none=True)
        ).manifest_id for case in dataset["cases"]
    }
    if dataset_hash != EXPECTED_DATASET:
        raise ValueError("frozen dataset identity changed")
    if manifest_by_case != EXPECTED_MANIFEST_BY_CASE:
        raise ValueError("dataset requests differ from the frozen case manifest map")
    environment = {
        "schema_version": 1, "status": "ready",
        "model": {"provider": "deepseek-flash", "model_id": model["model"],
                  "thinking": "disabled"},
        "dependency_snapshot_sha256": qualification.file_hash(root / "dependencies.json"),
        "knowledge_snapshot_sha256": knowledge_hash,
        "retrieval_health": "passed", "llm_compatibility": "passed",
        "notes": {
            "settings": {**RESOURCE_SETTINGS,
                         "LLM_DS_CONCURRENCY": os.getenv("LLM_DS_CONCURRENCY", "80"),
                         "DEEPCHOICE_SYNTH_THINKING": "0"},
            "git_commit": EXPECTED_COMMIT, "dataset_hash": dataset_hash,
            "llm_evidence_sha256": qualification.file_hash(llm_path),
            "retrieval_evidence_sha256":
                qualification.file_hash(preflight / "preflight-summary.json"),
            "endpoint_sha256": endpoint_hash,
            "safe_fetch_proxy_sha256": cfg.safe_fetch_proxy_sha256,
            "configuration_sha256": configuration_hash,
            "embedding_model": "BAAI/bge-m3", "embedding_revision": embedding_revision(),
            "embedding_startup_mode": "cold-in-research",
            "snapshot_copy_mode": "byte-exact-frozen-no-wal",
            "expected_manifest_by_case": manifest_by_case,
            "core_asset_registry_id": registry_id,
            "price_availability": "unavailable", "auto_recovery": False,
            "task_admission_limit": 12, "profile_order": list(PROFILES),
            "round_gate": "complete-paired-review-before-next-round",
            "pr2_tool_hashes": tool_hashes}}
    qualification.write_json(root / "environment.json", environment)
    evidence_root = root / "prerequisite-evidence"
    evidence_root.mkdir()
    for name in ("preflight-summary.json", "llm-preflight.json", "dependencies.json"):
        shutil.copy2(preflight / name, evidence_root / name)
    load_environment(root / "environment.json", require_ready=True)
    return {"prepared": True, "profiles": list(PROFILES),
            "knowledge_sha256": knowledge_hash,
            "expected_manifest_by_case": manifest_by_case, "git_commit": EXPECTED_COMMIT}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--preflight-dir", type=Path, required=True)
    parser.add_argument("--frozen-seed", type=Path, required=True)
    parser.add_argument("--expected-knowledge-sha256", required=True)
    parser.add_argument("--frozen-root", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = _main(args.root.resolve(), args.preflight_dir.resolve(),
                       args.frozen_seed.resolve(), args.expected_knowledge_sha256,
                       args.frozen_root.resolve(), args.env_file.resolve())
        print(json.dumps(result, sort_keys=True), flush=True)
    except Exception as exc:
        print(json.dumps({"error_type": type(exc).__name__}), flush=True)
        raise SystemExit(1)
