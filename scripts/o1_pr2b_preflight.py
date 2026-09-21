"""Run one bounded, observed PR2B prerequisite from the frozen candidate."""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import httpx
from dotenv import load_dotenv

EXPECTED_COMMIT = "d23c9480b9f368f8ec75ec44ee7e25c64146d4be"
EXPECTED_PROXY = "813477bf51a0efb3b5926c3759f01d02cdf25cd70e6cfc7fa186d9d5e1e1d118"
EXPECTED_DATASET = "e0317ddeaa2b37526f5a7261d8df26217b75619d6c46bcd1bc8705895f16981f"
EXPECTED_DEPENDENCIES = "c07764a225a2eef37b2ee47dacdd1dec0efac5cd263c4522b5c121c50a40493b"
EXPECTED_CONFIGURATION = "4240dcd933e728eff05ea91d27cc5a57056c6c87404d20fa3b946cef50d9c474"
EXPECTED_ENDPOINT = "12b8deaccc34b32757dbb1497e029da0c2e7b26ffa86b9c926c08cb4692f4508"
EXPECTED_EMBEDDING_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
EXPECTED_MANIFEST_BY_CASE = {"P01": "3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a", "P02": "4374d25d239cdc5891453a3785479c91bc52cf272db5c0e32b11c5a755eed563", "P03": "3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a", "P04": "e7389bdbe64920fa7d00879e4de449498b945ce16c548f1341d4f2ec4adbaef6", "P05": "e7389bdbe64920fa7d00879e4de449498b945ce16c548f1341d4f2ec4adbaef6", "P06": "4374d25d239cdc5891453a3785479c91bc52cf272db5c0e32b11c5a755eed563", "P07": "3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a", "P08": "3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a", "P09": "4374d25d239cdc5891453a3785479c91bc52cf272db5c0e32b11c5a755eed563", "P10": "e7389bdbe64920fa7d00879e4de449498b945ce16c548f1341d4f2ec4adbaef6", "P11": "4374d25d239cdc5891453a3785479c91bc52cf272db5c0e32b11c5a755eed563", "P12": "3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a"}
EXPECTED_ASSET_REGISTRY = "15cb66f6602a7f36090c1337f983ecbdbb3c74e77d7c9ca52c6c3c5ba799c850"

def _activate(frozen_root: Path, env_file: Path):
    if not frozen_root.is_dir() or not env_file.is_file():
        raise ValueError("frozen candidate or private environment is unavailable")
    load_dotenv(env_file, override=False)
    os.chdir(frozen_root)
    sys.path.insert(0, str(frozen_root))
    from benchmarks import product_baseline_qualification as qualification
    from deepchoice.outbound import throttle
    if qualification.git_identity() != EXPECTED_COMMIT:
        raise ValueError("frozen candidate identity changed")
    return qualification, throttle

async def _main(output: Path, frozen_root: Path, env_file: Path) -> int:
    qualification, throttle = _activate(frozen_root, env_file)
    audit = output.parent / f"{output.name}-http-status.jsonl"
    if output.exists() or audit.exists():
        raise ValueError("fresh prerequisite evidence required")
    cfg = qualification.trusted_configuration()
    if cfg.safe_fetch_proxy_sha256 != EXPECTED_PROXY:
        raise ValueError("authorized proxy identity changed")
    from benchmarks.product_baseline import load_dataset
    from benchmarks.product_baseline_experiment import embedding_revision
    from deepchoice.contracts.api import ResearchRequest
    from deepchoice.contracts.manifest import build_core_asset_registry, build_run_manifest
    from deepchoice.utils.llm import TIERS
    dependencies = qualification.dependency_records()
    dependency_hash = hashlib.sha256(
        (json.dumps(dependencies, ensure_ascii=False, indent=2) + "\n").encode()).hexdigest()
    model = TIERS["deepseek-flash"]
    dataset, dataset_hash = load_dataset(
        frozen_root / "benchmarks/product-baseline-v1.json", require_frozen=True)
    manifests = {case["id"]: build_run_manifest(
        ResearchRequest.model_validate(case["request"]).model_dump(exclude_none=True)
    ).manifest_id for case in dataset["cases"]}
    if (dependency_hash != EXPECTED_DEPENDENCIES
            or qualification.configuration_sha256(cfg) != EXPECTED_CONFIGURATION
            or hashlib.sha256(model["base"].encode()).hexdigest() != EXPECTED_ENDPOINT
            or embedding_revision() != EXPECTED_EMBEDDING_REVISION
            or build_core_asset_registry().registry_id != EXPECTED_ASSET_REGISTRY
            or dataset_hash != EXPECTED_DATASET
            or manifests != EXPECTED_MANIFEST_BY_CASE):
        raise ValueError("frozen PR1 identity changed before prerequisite dispatch")
    original = httpx.AsyncClient._send_single_request
    ordinal = 0
    paid_tavily_posts = 0
    sources = {"api.tavily.com": "tavily", "api.github.com": "github",
               "export.arxiv.org": "arxiv", "api.stackexchange.com": "community",
               "pypi.org": "official"}
    async def observed(self, request):
        nonlocal ordinal, paid_tavily_posts
        ordinal += 1
        source = sources.get(request.url.host, "other")
        if source == "tavily" and request.method == "POST":
            paid_tavily_posts += 1
        if ordinal > 20 or paid_tavily_posts > 1:
            raise RuntimeError("prerequisite HTTP bound exceeded")
        entry = {"ordinal": ordinal, "method": request.method, "source": source,
                 "started_at": qualification.now()}
        started = time.monotonic()
        try:
            response = await original(self, request)
            retry_after = throttle.retry_after(response.headers, default=-1)
            entry.update(status=response.status_code,
                         retry_after_present="retry-after" in response.headers,
                         retry_after_seconds=retry_after if retry_after >= 0 else None)
            return response
        except BaseException as exc:
            entry["error_type"] = type(exc).__name__
            raise
        finally:
            entry.update(ended_at=qualification.now(),
                         elapsed_ms=round((time.monotonic() - started) * 1000))
            with audit.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
    httpx.AsyncClient._send_single_request = observed
    try:
        result = await qualification.preflight(output, cfg, commit=EXPECTED_COMMIT)
        result["observed_http_requests"] = ordinal
        result["observed_paid_tavily_posts"] = paid_tavily_posts
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0 if result["passed"] else 1
    finally:
        httpx.AsyncClient._send_single_request = original

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frozen-root", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(_main(args.output.resolve(),
                                           args.frozen_root.resolve(),
                                           args.env_file.resolve())))
    except Exception as exc:
        print(json.dumps({"error_type": type(exc).__name__,
                          "research_runs_submitted": 0}), flush=True)
        raise SystemExit(1)
