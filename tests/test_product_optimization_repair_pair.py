from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from benchmarks import product_optimization_repair_pair as pair


def test_frozen_repair_pair_protocol_loads_with_conservative_boundaries():
    frozen = pair.load_repair_pair_protocol()
    payload = frozen.payload

    assert frozen.byte_sha256 == pair._file_sha256(pair.PROTOCOL_PATH)
    assert payload["dataset"]["case_ids"] == ["P01", "P04", "P08"]
    assert payload["dataset"]["holdout_access"] == "forbidden"
    assert payload["design"]["formal_research_runs"] == 12
    assert payload["design"]["independent_single_case_qualification"] is False
    assert payload["design"]["paired_p01_replaces_qualification"] is True
    assert payload["status"] == "frozen"
    assert payload["freeze_date"] == "2026-09-26"
    assert payload["authorization"]["status"] == "approved"
    assert payload["authorization"]["effective_hard_total"] == 155
    assert payload["controller"]["research_admission"] == (
        "open-after-offline-runner-acceptance"
    )
    assert payload["environment"]["hitl_mode"] == "stop-at-hitl-no-auto-resolution"
    assert payload["environment"]["endpoint_sha256"] == (
        "12b8deaccc34b32757dbb1497e029da0c2e7b26ffa86b9c926c08cb4692f4508"
    )
    assert payload["environment"]["configuration_sha256"] == (
        "4240dcd933e728eff05ea91d27cc5a57056c6c87404d20fa3b946cef50d9c474"
    )
    assert payload["environment"]["safe_fetch_proxy_sha256"] == (
        "813477bf51a0efb3b5926c3759f01d02cdf25cd70e6cfc7fa186d9d5e1e1d118"
    )
    assert payload["stopping"]["ordinary_citation_http_5xx"] == "stop-new-admission"
    assert payload["budgets"]["research_ledger"] == {
        "starting_used": 95,
        "local_pair_max": 12,
        "final_concurrency_reserve": 48,
        "hard_total": 155,
        "unallocated": 0,
    }


def test_protocol_covers_each_development_cell_once():
    review = pair.load_repair_pair_protocol().payload["design"]["blind_review_order"]
    assert len(review) == 12
    assert len({(item["case_id"], item["arm"], item["repetition"])
                for item in review}) == 12
    assert all(item["case_id"] in {"P01", "P04", "P08"} for item in review)
    assert [item["blind_label"] for item in review] == [
        f"RP4-{index:02d}" for index in range(1, 13)
    ]


def test_parent_dataset_content_is_never_opened(monkeypatch):
    payload = copy.deepcopy(pair.load_repair_pair_protocol().payload)
    hashed: list[Path] = []
    original = pair._file_sha256

    def observed(path: Path) -> str:
        hashed.append(path)
        return original(path)

    monkeypatch.setattr(pair, "_file_sha256", observed)
    pair._validate_protocol(payload)

    parent_path = pair.ROOT / "benchmarks/product-baseline-v1.json"
    assert parent_path not in hashed
    assert payload["dataset"]["parent_bytes_sha256"] == pair.PARENT_DATASET_BYTES_SHA256
    assert payload["dataset"]["parent_sha256"] == pair.PARENT_DATASET_SHA256
    assert payload["dataset"]["parent_git_object"] == pair.PARENT_DATASET_GIT_OBJECT


def test_protocol_binds_runtime_helpers_for_both_arms():
    identities = pair.load_repair_pair_protocol().payload["identities"]
    expected = [
        "benchmarks/__init__.py",
        "benchmarks/product_baseline.py",
        "benchmarks/product_baseline_experiment.py",
        "benchmarks/product_baseline_server.py",
    ]
    assert [item["path"] for item in identities["baseline"]["runtime_objects"]] == expected
    assert [item["path"] for item in identities["candidate"]["runtime_objects"]] == expected


def test_protocol_rejects_missing_or_changed_controller(monkeypatch):
    payload = copy.deepcopy(pair.load_repair_pair_protocol().payload)
    runner = pair.ROOT / "scripts/product_optimization_repair_pair.py"
    original = pair._file_sha256

    def changed(path: Path) -> str:
        if path == runner:
            return "0" * 64
        return original(path)

    monkeypatch.setattr(pair, "_file_sha256", changed)
    with pytest.raises(pair.RepairPairProtocolError, match="controller file identity changed"):
        pair._validate_protocol(payload)


def test_protocol_rejects_any_holdout_case_in_review():
    payload = copy.deepcopy(pair.load_repair_pair_protocol().payload)
    payload["design"]["blind_review_order"][0]["case_id"] = "P09"

    with pytest.raises(pair.RepairPairProtocolError, match="blind review order changed"):
        pair._validate_protocol(payload)


def test_protocol_json_has_no_placeholder_hashes():
    payload = json.loads(pair.PROTOCOL_PATH.read_text(encoding="utf-8"))
    assert all(item["sha256"] != "0" * 64
               for item in payload["controller"]["required_files"])
