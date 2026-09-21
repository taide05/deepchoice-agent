"""Bounded S1 candidate prerequisite, preparation and single-admission runner.

This is not the twelve-cell paired experiment. An execution success still needs
report-quality qualification; it never opens the formal measurement gate.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from benchmarks import product_baseline_qualification as qualification
from benchmarks import product_optimization_s1 as protocol
from benchmarks.product_baseline_experiment import embedding_revision
from scripts import o1_pr2b_control as control


PROTOCOL_SHA256 = "1e771a7beb8c551df2c4eafc49d5c2a3f0d16845ca678f54f391018b0686d391"
TOOL_NAMES = ("s1_qualification.py", "o1_pr2b_control.py", "o1_pr2b_child.py")
PREREQUISITE_FILES = ("preflight-summary.json", "llm-preflight.json", "dependencies.json")


def check_candidate(cfg) -> dict:
    """Bind product, actual imported source, shared environment and clean runner."""
    _, digest = protocol.load_protocol()
    if digest != PROTOCOL_SHA256:
        raise ValueError("S1 frozen protocol digest changed")
    commit = qualification.git_identity()
    from deepchoice import state
    from deepchoice.utils.llm import TIERS

    if Path(state.__file__).resolve() != protocol.ROOT / "src/deepchoice/state.py":
        raise ValueError("imported product is not the checked candidate")
    dependencies = hashlib.sha256((json.dumps(
        qualification.dependency_records(), ensure_ascii=False, indent=2) + "\n").encode()).hexdigest()
    checks = {
        "dependencies": dependencies == control.EXPECTED_DEPENDENCIES,
        "configuration": qualification.configuration_sha256(cfg) == control.EXPECTED_CONFIGURATION,
        "proxy": cfg.safe_fetch_proxy_sha256 == control.EXPECTED_PROXY,
        "endpoint": hashlib.sha256(TIERS["deepseek-flash"]["base"].encode()).hexdigest()
                    == control.EXPECTED_ENDPOINT,
        "model": TIERS["deepseek-flash"]["model"] == "deepseek-v4-flash",
        "embedding": embedding_revision() == control.EXPECTED_EMBEDDING_REVISION,
        "cache": os.getenv("RETRIEVAL_CACHE_ENABLED", "1") == "1",
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("frozen S1 environment drift: " + ", ".join(failed))
    return {
        "schema_version": 1,
        "protocol_sha256": digest,
        "git_commit": commit,
        "tool_hashes": {name: qualification.file_hash(Path(__file__).parent / name)
                        for name in TOOL_NAMES},
    }


def prerequisite_hashes(root: Path) -> dict:
    directory = root.parent / "preflight"
    return {name: qualification.file_hash(directory / name) for name in PREREQUISITE_FILES}


def verify_prepared(root: Path, frozen_root: Path, environment: dict, cfg) -> dict:
    if frozen_root.resolve() != protocol.ROOT:
        raise ValueError("S1 qualification must execute the checked candidate root")
    expected = check_candidate(cfg)
    qualification.verify_frozen_environment(environment, cfg)
    expected["environment_sha256"] = qualification.file_hash(root / "environment.json")
    expected["prerequisite_hashes"] = prerequisite_hashes(root)
    actual = json.loads((root / "s1-execution-binding.json").read_text(encoding="utf-8"))
    if actual != expected:
        raise ValueError("S1 execution binding changed after preparation")
    return actual


def prepare(root: Path, seed: Path, cfg) -> dict:
    binding = check_candidate(cfg)
    qualification.prepare(root, root.parent / "preflight", seed,
                          control.EXPECTED_KNOWLEDGE, cfg)
    (root / "serial-r1/control").mkdir()
    binding["environment_sha256"] = qualification.file_hash(root / "environment.json")
    binding["prerequisite_hashes"] = prerequisite_hashes(root)
    qualification.write_json(root / "s1-execution-binding.json", binding)
    return {"prepared": True, "protocol_sha256": PROTOCOL_SHA256,
            "research_runs_submitted": 0}


async def run_command(args) -> dict:
    if not args.env_file.is_file():
        raise ValueError("private environment is unavailable")
    load_dotenv(args.env_file, override=False)
    os.chdir(protocol.ROOT)
    cfg = qualification.trusted_configuration()
    binding = check_candidate(cfg)
    if args.command == "audit":
        return {**binding, "research_runs_submitted": 0, "network_calls": 0}
    if args.command == "preflight":
        if not args.execute_paid_probes:
            raise ValueError("explicit bounded prerequisite dispatch flag required")
        # Exclusive root creation also prevents retrying a stopped prerequisite.
        args.root.mkdir(parents=True, exist_ok=False)
        qualification.write_json(args.root / "preflight-binding.json", binding)
        return await qualification.preflight(args.root / "preflight", cfg,
                                             commit=binding["git_commit"])
    previous = json.loads((args.root / "preflight-binding.json").read_text(encoding="utf-8"))
    if previous != binding:
        raise ValueError("candidate/controller changed since the bounded prerequisite")
    candidate_root = args.root / "qualification"
    if args.command == "prepare":
        if args.frozen_seed is None:
            raise ValueError("verified frozen seed required")
        return prepare(candidate_root, args.frozen_seed, cfg)
    if not args.execute_paid_run:
        raise ValueError("explicit single research admission flag required")
    succeeded = await control.execute(candidate_root, protocol.ROOT,
                                      args.env_file.resolve(), "serial-r1",
                                      s1_qualification=True)
    return {"execution_succeeded": succeeded,
            "report_quality_qualification": "pending" if succeeded else "unavailable",
            "formal_measurement_gate": "closed"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("audit", "preflight", "prepare", "run"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--frozen-seed", type=Path)
    parser.add_argument("--execute-paid-probes", action="store_true")
    parser.add_argument("--execute-paid-run", action="store_true")
    args = parser.parse_args(argv)
    args.root = args.root.resolve()
    args.env_file = args.env_file.resolve()
    try:
        result = asyncio.run(run_command(args))
        print(json.dumps(result, sort_keys=True))
        return 1 if result.get("passed") is False or result.get("execution_succeeded") is False else 0
    except Exception as exc:
        # Raw errors can carry environment paths or provider data.
        print(json.dumps({"error_type": type(exc).__name__, "status": "stopped",
                          "formal_measurement_gate": "closed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
