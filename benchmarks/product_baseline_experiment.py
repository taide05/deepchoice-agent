"""Prepare isolated O1 snapshots and serve one single-worker profile."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
from importlib.metadata import distributions
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time

from dotenv import load_dotenv


PROFILES = ("serial-r1", "concurrent-r1", "concurrent-r2", "serial-r2")
RESOURCE_SETTINGS = {
    "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1", "TOKENIZERS_PARALLELISM": "false",
    "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
    "LEARNED_DOCS_READONLY": "1", "RETRIEVAL_CACHE_ENABLED": "1",
}


def file_hash(path: Path) -> str:
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256")
    return digest.hexdigest()


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("knowledge snapshot must not contain symlinks")
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode() + b"\0")
            digest.update(file_hash(path).encode() + b"\n")
    return digest.hexdigest()


def copy_knowledge(chroma: Path, learned: Path, destination: Path) -> str:
    """Never change the source; detect concurrent source writes around copying."""
    if destination.exists():
        raise ValueError("knowledge destination must be fresh")
    if (chroma / "chroma.sqlite3-wal").exists():
        raise ValueError("source knowledge must be stopped with no pending WAL")
    before = (tree_hash(chroma), file_hash(learned))
    destination.mkdir(parents=True)
    shutil.copytree(chroma, destination / "chroma")
    source_db = chroma / "chroma.sqlite3"
    with sqlite3.connect(source_db.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as source:
        with sqlite3.connect(destination / "chroma" / "chroma.sqlite3") as target:
            source.backup(target)
    shutil.copy2(learned, destination / "learned_docs.json")
    if before != (tree_hash(chroma), file_hash(learned)):
        raise ValueError("source knowledge changed during snapshot preparation")
    return tree_hash(destination)


def embedding_revision() -> str:
    hub = Path(os.getenv("HF_HUB_CACHE", str(Path(os.getenv("HF_HOME",
               str(Path.home() / ".cache" / "huggingface"))) / "hub")))
    revision = (hub / "models--BAAI--bge-m3" / "refs" / "main").read_text().strip()
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueError("cached embedding revision is invalid")
    return revision


async def prepare(root: Path, llm_evidence: Path) -> dict:
    if root.exists():
        raise ValueError("experiment root must be fresh")
    load_dotenv()
    os.environ.update(RESOURCE_SETTINGS)
    from benchmarks.run_baseline import health_check_report
    from deepchoice.utils.llm import TIERS

    probe = json.loads(llm_evidence.read_text(encoding="utf-8"))
    if not probe.get("passed") or probe.get("model_id") != TIERS["deepseek-flash"]["model"]:
        raise ValueError("compatible model probe evidence is required")
    if os.getenv("DEEPCHOICE_SYNTH_THINKING", "0") != "0":
        raise ValueError("current probe covers disabled thinking only")
    chroma = Path(os.getenv("CHROMA_PATH", "./chroma_kb/chroma_db")).resolve()
    learned = Path(os.getenv("LEARNED_DOCS_PATH", "./learned_docs.json")).resolve()
    health = await health_check_report()
    if not health.get("ok") or not health.get("tavily_direct", {}).get("ok"):
        raise ValueError("full retrieval prerequisite failed")
    root.mkdir(parents=True)
    safe_health = {"passed": True, "sources": health["sources"], "tavily_post": "HTTP_200"}
    (root / "retrieval-health.json").write_text(json.dumps(safe_health, indent=2) + "\n", encoding="utf-8")
    dependency = sorted({(item.metadata["Name"].lower(), item.version) for item in distributions()
                         if item.metadata.get("Name")})
    dependency_path = root / "dependencies.json"
    dependency_path.write_text(json.dumps(dependency, indent=2) + "\n", encoding="utf-8")
    identity = copy_knowledge(chroma, learned, root / "knowledge-seed")
    for profile in PROFILES:
        shutil.copytree(root / "knowledge-seed", root / profile / "knowledge")
        if tree_hash(root / profile / "knowledge") != identity:
            raise ValueError("profile snapshot differs from frozen seed")
        (root / profile / "runtime").mkdir()
    settings = {**RESOURCE_SETTINGS, "LLM_DS_CONCURRENCY": os.getenv("LLM_DS_CONCURRENCY", "80"),
                "DEEPCHOICE_SYNTH_THINKING": "0"}
    model = TIERS["deepseek-flash"]
    environment = {"schema_version": 1, "status": "ready",
        "model": {"provider": "deepseek-flash", "model_id": model["model"], "thinking": "disabled"},
        "dependency_snapshot_sha256": file_hash(dependency_path),
        "knowledge_snapshot_sha256": identity, "retrieval_health": "passed", "llm_compatibility": "passed",
        "notes": {"settings": settings, "llm_evidence_sha256": file_hash(llm_evidence),
            "retrieval_evidence_sha256": file_hash(root / "retrieval-health.json"),
            "endpoint_sha256": hashlib.sha256(model["base"].encode()).hexdigest(),
            "embedding_model": "BAAI/bge-m3", "embedding_revision": embedding_revision(),
            "price_availability": "unavailable", "source_original_sha256": tree_hash(chroma)}}
    (root / "environment.json").write_text(json.dumps(environment, indent=2) + "\n", encoding="utf-8")
    return {"prepared": True, "profiles": list(PROFILES), "knowledge_sha256": identity}


def serve(root: Path, profile: str, port: int) -> None:
    load_dotenv()
    environment = json.loads((root / "environment.json").read_text(encoding="utf-8"))
    settings = environment["notes"]["settings"]
    if set(settings) != set(RESOURCE_SETTINGS) | {"LLM_DS_CONCURRENCY", "DEEPCHOICE_SYNTH_THINKING"}:
        raise ValueError("runtime settings must use the fixed allowlist")
    if any(not isinstance(value, str) for value in settings.values()):
        raise ValueError("runtime settings must be strings")
    os.environ.update(settings)
    knowledge = (root / profile / "knowledge").resolve()
    if tree_hash(knowledge) != environment["knowledge_snapshot_sha256"]:
        raise ValueError("profile knowledge changed before startup")
    runtime = (root / profile / "runtime").resolve()
    if any(runtime.iterdir()):
        raise ValueError("profile runtime is not empty; reconcile instead of auto-resuming")
    os.environ["CHROMA_PATH"] = str(knowledge / "chroma")
    os.environ["LEARNED_DOCS_PATH"] = str(knowledge / "learned_docs.json")
    os.environ["DEEPCHOICE_EXPERIMENT_DIR"] = str(runtime)
    os.environ["WEB_CONCURRENCY"] = "1"
    # Paths must be set before importing contracts/server: they import learned_docs.
    from benchmarks.product_baseline import load_environment
    load_environment(root / "environment.json", require_ready=True)
    from deepchoice.utils.llm import TIERS
    actual = TIERS["deepseek-flash"]
    if (actual["model"] != environment["model"]["model_id"] or
        hashlib.sha256(actual["base"].encode()).hexdigest() != environment["notes"]["endpoint_sha256"] or
        embedding_revision() != environment["notes"]["embedding_revision"]):
        raise ValueError("effective model configuration changed after preparation")
    import torch
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    from deepchoice.utils.embedding import get_embedding_model
    warmup_started = time.monotonic()
    vector = get_embedding_model().encode("O1 embedding prerequisite")
    if len(vector) != 1024:
        raise ValueError("embedding dimension differs from frozen knowledge")
    print(json.dumps({"embedding_warmed": True, "embedding_startup_mode": "prewarmed",
                      "embedding_warmup_ms": round((time.monotonic() - warmup_started) * 1000),
                      "profile": profile}), flush=True)
    import uvicorn
    uvicorn.run("benchmarks.product_baseline_server:create_app", factory=True,
                host="127.0.0.1", port=port, workers=1, log_level="warning")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "serve"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--llm-evidence")
    parser.add_argument("--execute-paid-health-check", action="store_true")
    parser.add_argument("--profile", choices=PROFILES)
    parser.add_argument("--port", type=int, default=8011)
    args = parser.parse_args()
    try:
        root = Path(args.root).resolve()
        if args.command == "prepare":
            if not args.llm_evidence or not args.execute_paid_health_check:
                parser.error("prepare requires probe evidence and paid health-check consent")
            print(json.dumps(asyncio.run(prepare(root, Path(args.llm_evidence)))), flush=True)
        else:
            if not args.profile:
                parser.error("serve requires a profile")
            serve(root, args.profile, args.port)
        return 0
    except Exception as exc:
        print(json.dumps({"error_type": type(exc).__name__, "research_runs_submitted": 0}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
