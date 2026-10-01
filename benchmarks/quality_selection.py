"""Single-use, serial quality-selection collection over the durable collector.

This is an experiment adapter, not a product endpoint or a quality judge.
Preparation/server launch must freeze and verify the binding before collection.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import closing, contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid
from typing import Any

import httpx

from benchmarks.product_baseline import (
    CollectionOptions, DurableBaselineCollector, SUCCESS_STATUSES, TERMINAL_STATUSES,
)
from deepchoice.contracts.api import ResearchRequest

PROTOCOL = "quality-selection-v1"
BASE_USED = 114
HARD_TOTAL = 156
PHASE_LIMITS = {"baseline": 4, "candidate": 4, "followup": 4, "repair_baseline": 4, "reviewed_candidate": 4, "delivery_candidate": 4, "acceptance": 24}
REPAIR_PURPOSE = "restore-audited-seed-runtime-files"
DATASETS = {
    "development": ("quality-selection-development-v1", "e230c6e28e117a7e1216e6e507431a90712013dd2a51655f2396ea0525bfc3b0"),
    "holdout": ("quality-selection-holdout-v1", "bd30ee3844834983fa72e2d7d1631bf26155bda719b9d3fe7e952c467b7ff7ca"),
}
RUN_LIMITS = {"total_tokens": 60000, "llm_calls": 96, "retrieval_calls": 72, "active_milliseconds": 900000}
ORDINARY_CALL_FAILURES = frozenset({
    "rate_limited", "provider_timeout", "provider_error", "transport_error",
    "provider_unavailable", "knowledge_base_unavailable",
    "json_parse_error", "json_schema_error", "output_truncated",
})
STOP_POLICY = {
    "id": "quality-selection-stop-v1",
    "ordinary_call_failures": sorted(ORDINARY_CALL_FAILURES),
    "ordinary_run_failures": ["run_timeout", "cancelled"],
    "all_other_failures": "stop",
    "missing_final_observation": "stop",
    "budget_denial_or_unsettled_reservation": "stop",
    "artifact_mismatch": "stop",
    "content_review": "separate-no-automatic-quality-pass",
}
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any, *, exclusive: bool = False) -> None:
    with path.open("x" if exclusive else "w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _hash(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _time(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value)
    _require(timestamp.tzinfo is not None, "timestamps must include timezone")
    return timestamp


def load_cases(specs: list[dict], *, allow_holdout: bool = False) -> dict[str, dict]:
    """Project the two independently frozen shapes without editing either."""
    cases: dict[str, dict] = {}
    seen_splits: set[str] = set()
    for spec in specs:
        split = spec["split"]
        _require(split in DATASETS and split not in seen_splits, "invalid/duplicate dataset split")
        _require(split != "holdout" or allow_holdout, "holdout requires a locked acceptance candidate")
        seen_splits.add(split)
        expected_id, expected_hash = DATASETS[split]
        path = Path(spec["path"])
        _require(spec["sha256"] == expected_hash and file_digest(path) == expected_hash, "frozen dataset drift")
        data = json.loads(path.read_text(encoding="utf-8"))
        _require(data["dataset_id"] == expected_id and data["version"] == "1.0.0"
                 and data["status"] == "frozen" and data["protocol"] == PROTOCOL, "invalid frozen dataset")
        _require(len(data["cases"]) == 4, "each frozen split must contain four cases")
        for item in data["cases"]:
            case_id = item["case_id"] if split == "development" else item["id"]
            _require(isinstance(case_id, str) and ID_PATTERN.fullmatch(case_id) is not None
                     and case_id not in cases, "invalid/duplicate case identity")
            request = item["request"]
            ResearchRequest.model_validate(request)
            request_hash = digest(request)
            if split == "development":
                _require(item["request_sha256"] == request_hash, "original request drift")
            cases[case_id] = {
                "id": case_id, "split": split, "request": request,
                "request_sha256": request_hash, "hitl": item.get("hitl"),
            }
    return cases


def validate_hitl(value: dict) -> None:
    _require(isinstance(value, dict) and not set(value) - {"action", "repeat_action", "supplemental_input"},
             "invalid HITL policy fields")
    actions = {"provide_context", "limited_report", "cancel"}
    _require(value.get("action") in actions and value.get("repeat_action", value.get("action")) in actions,
             "invalid fixed HITL action")
    text = value.get("supplemental_input")
    needs_text = "provide_context" in {value["action"], value.get("repeat_action")}
    _require(not needs_text or isinstance(text, str) and bool(text.strip()), "fixed context is missing")
    # Use the production request bound, not a separate truncation rule.
    _require(needs_text or text is None, "unexpected fixed supplemental context")
    if needs_text:
        from deepchoice.hitl import DecisionResolution
        DecisionResolution.model_validate({"action": "provide_context", "supplemental_input": text})



def validate_repair_purpose(value: dict | None) -> dict:
    """One reserve allocation for the recorded runtime-seed omission, not retries."""
    _require(isinstance(value, dict) and value.get("id") == REPAIR_PURPOSE,
             "repair purpose is required")
    ref = value.get("incident", {})
    _require(_hash(ref.get("sha256")) and isinstance(ref.get("path"), str), "repair incident is required")
    path = Path(ref["path"])
    _require(file_digest(path) == ref["sha256"], "repair incident drift")
    incident = json.loads(path.read_text(encoding="utf-8"))
    _require(incident.get("old_roots_closed") is True and incident.get("research_used") == 119
             and incident.get("original_audited_index_entries") == 234
             and incident.get("prepared_audited_index_entries") == 0,
             "repair incident does not establish the stopped seed fault")
    control = value.get("original_baseline_binding", {})
    _require(_hash(control.get("sha256")) and isinstance(control.get("path"), str),
             "original baseline binding is required")
    control_path = Path(control["path"])
    _require(file_digest(control_path) == control["sha256"], "original baseline binding drift")
    raw = json.loads(control_path.read_text(encoding="utf-8"))
    _require(raw.get("phase") == "baseline", "repair must reference the original baseline")
    return load_binding(control_path, require_current=False)[0]

def validate_development_authorization(ref: dict | None, ledger_identity: dict) -> dict:
    """Audit the explicit one-time four-case grant; never infer it from capacity."""
    _require(isinstance(ref, dict) and isinstance(ref.get("path"), str) and _hash(ref.get("sha256")),
             "development authorization is required")
    path = Path(ref["path"])
    _require(file_digest(path) == ref["sha256"], "development authorization drift")
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {"protocol": PROTOCOL, "phase": "reviewed_candidate", "approved": True,
                "starting_used": 127, "maximum_new_research_admissions": 4,
                "maximum_after_development": 131, "conditional_final_cells": 24,
                "maximum_with_final": 155, "ledger_identity_sha256": digest(ledger_identity),
                "case_order": ["P01", "P04", "P08", "P02"]}
    _require(all(type(value.get(key)) is type(expected) and value[key] == expected
                 for key, expected in required.items()), "development authorization scope mismatch")
    _require(value.get("user_confirmation") == "明确授权", "explicit user confirmation is missing")
    return value


def validate_budget_extension(ref: dict | None, ledger_identity: dict) -> dict:
    """One explicit 2026-10-01 grant, independent of the immutable v1 identity."""
    _require(isinstance(ref, dict) and isinstance(ref.get("path"), str) and _hash(ref.get("sha256")),
             "budget extension authorization is required")
    path = Path(ref["path"])
    _require(file_digest(path) == ref["sha256"], "budget extension authorization drift")
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {"protocol": PROTOCOL, "phase": "delivery_candidate", "approved": True,
                "starting_used": 131, "maximum_new_research_admissions": 4,
                "maximum_after_development": 135, "conditional_final_cells": 24,
                "previous_hard_total": 156, "maximum_with_final": 159,
                "ledger_identity_sha256": digest(ledger_identity),
                "case_order": ["P01", "P04", "P08", "P02"],
                "user_confirmation": "确认。以及解释为什么最终是24次？"}
    _require(all(type(value.get(key)) is type(expected) and value[key] == expected
                 for key, expected in required.items()) and _hash(value.get("prior_admissions_sha256")),
             "budget extension authorization scope mismatch")
    return value


def _delivery_allocation(rows: list) -> None:
    prior = {phase: sum(row[3] == phase for row in rows)
             for phase in PHASE_LIMITS if phase not in {"delivery_candidate", "acceptance"}}
    _require(prior == {"baseline": 4, "candidate": 1, "followup": 4,
                       "repair_baseline": 4, "reviewed_candidate": 4},
             "delivery development requires the reconciled 131-admission history")


def _reviewed_allocation(rows: list) -> None:
    prior = {phase: sum(row[3] == phase for row in rows) for phase in PHASE_LIMITS
             if phase not in {"reviewed_candidate", "delivery_candidate"}}
    _require(prior == {"baseline": 4, "candidate": 1, "followup": 4,
                       "repair_baseline": 4, "acceptance": 0},
             "reviewed development requires the reconciled 127-admission history")


def load_binding(path: Path, *, require_current: bool = True) -> tuple[dict, dict[str, dict]]:
    binding = json.loads(path.read_text(encoding="utf-8"))
    _require(binding.get("schema_version") == 1 and binding.get("protocol") == PROTOCOL, "invalid binding")
    phase = binding.get("phase")
    _require(phase in PHASE_LIMITS and binding.get("stop_policy") == STOP_POLICY, "unsupported phase/stop policy")
    _require(binding.get("run_limits") == RUN_LIMITS, "run limits drift")
    identity = binding.get("identity", {})
    for field in ("production_commit", "runner_commit"):
        _require(isinstance(identity.get(field), str) and re.fullmatch(r"[a-f0-9]{40}", identity[field]) is not None,
                 "missing commit identity")
    for field in ("core_asset_registry_id", "environment_sha256", "source_policy_sha256"):
        _require(_hash(identity.get(field)), "missing frozen environment/asset identity")
    _require(identity["environment_sha256"] == digest(binding.get("environment"))
             and identity["source_policy_sha256"] == digest(binding.get("source_policy")), "frozen metadata drift")
    if phase == "reviewed_candidate":
        validate_development_authorization(binding.get("development_authorization"), binding.get("ledger_identity", {}))
        _require(binding.get("starting_used") == 127
                 and binding.get("comparison_mode") == "historical-baseline-different-collector-v1",
                 "reviewed development allocation/comparison mismatch")
    extended = phase == "delivery_candidate" or binding.get("budget_extension") is not None
    if extended:
        _require(phase in {"delivery_candidate", "acceptance"}, "extension cannot reopen an old phase")
        validate_budget_extension(binding.get("budget_extension"), binding.get("ledger_identity", {}))
        _require(binding.get("starting_used") == (131 if phase == "delivery_candidate" else 135),
                 "extended allocation starting count mismatch")
    if phase == "delivery_candidate":
        _require(binding.get("comparison_mode") == "historical-baseline-different-collector-v1",
                 "delivery comparison mode mismatch")
    repair_control = None
    if phase == "repair_baseline":
        repair_control = validate_repair_purpose(binding.get("repair_purpose"))
        _require(type(binding.get("starting_used")) is int and binding["starting_used"] >= 119,
                 "repair requires reconciled prior admissions")
        _require(binding["environment"].get("knowledge_audit", {}).get("index_entries") == 234,
                 "repair requires restored audited seed")
    locked_candidate = None
    if phase == "acceptance":
        locked_candidate = load_candidate_lock(binding.get("candidate_lock"), identity["production_commit"])
        if binding.get("starting_used", 0) >= 127:
            _require(binding["starting_used"] == (135 if extended else 131)
                     and locked_candidate["phase"] == ("delivery_candidate" if extended else "reviewed_candidate")
                     and binding.get("budget_extension") == locked_candidate.get("budget_extension"),
                     "acceptance must lock the newly reviewed four-case candidate")
        verify_comparison(binding, locked_candidate)
        _require(identity["core_asset_registry_id"] == locked_candidate["identity"]["core_asset_registry_id"],
                 "locked candidate assets drift")
    cases = load_cases(binding["datasets"], allow_holdout=phase == "acceptance")
    _require(len(cases) == (8 if phase == "acceptance" else 4), "wrong case denominator")
    schedule = binding["cells"]
    _require(isinstance(schedule, list) and len(schedule) == PHASE_LIMITS[phase], "wrong cell denominator")
    seen: set[tuple[str, int]] = set()
    ids: set[str] = set()
    for cell in schedule:
        case = cases[cell["case_id"]]
        _require(ID_PATTERN.fullmatch(cell["cell_id"]) is not None and cell["cell_id"] not in ids,
                 "invalid/duplicate cell identity")
        ids.add(cell["cell_id"])
        rep = cell["repetition"]
        _require(type(rep) is int and rep in (range(1, 4) if phase == "acceptance" else (1,)), "invalid repetition")
        key = (case["id"], rep)
        _require(key not in seen, "duplicate case/repetition")
        seen.add(key)
        _require(cell["request_sha256"] == case["request_sha256"] and _hash(cell["manifest_id"]), "request/manifest drift")
        validate_hitl(cell["hitl"])
        if case["hitl"] is not None:
            _require(cell["hitl"] == case["hitl"], "sealed HITL policy drift")
    if repair_control is not None:
        _require(identity["production_commit"] == repair_control["identity"]["production_commit"],
                 "repair control production drift")
        original = {c["case_id"]: c for c in repair_control["cells"]}
        _require(all(all(c[key] == original[c["case_id"]][key] for key in
                         ("request_sha256", "manifest_id", "hitl")) for c in schedule),
                 "repair control request/manifest/HITL drift")
        _require(binding["ledger_identity"] == repair_control["ledger_identity"], "repair ledger drift")
        fixed = ("configuration_sha256", "dependency_snapshot_sha256", "embedding_revision",
                 "settings", "model_id", "endpoint_sha256", "tavily_state_path")
        _require(all(binding["environment"][key] == repair_control["environment"][key] for key in fixed),
                 "repair control configuration drift")
    if phase == "acceptance":
        # Each pass covers every case before the next repetition begins.
        for rep in range(1, 4):
            group = schedule[(rep - 1) * 8:rep * 8]
            _require({c["case_id"] for c in group} == set(cases)
                     and all(c["repetition"] == rep for c in group), "acceptance must interleave complete passes")
    start, end = _time(binding["frozen_at"]), _time(binding["valid_until"])
    _require(0 < (end - start).total_seconds() <= 7 * 86400, "comparison window exceeds seven days")
    if require_current:
        _require(start <= datetime.now(UTC) <= end, "binding is outside its frozen window")
    _require(type(binding.get("starting_used")) is int and BASE_USED <= binding["starting_used"] <= (159 if extended else HARD_TOTAL) - len(schedule),
             "research ledger would exceed hard cap")
    _require(binding.get("ledger_base_used") == BASE_USED
             and binding.get("ledger_identity", {}).get("protocol") == PROTOCOL
             and binding["ledger_identity"].get("base_used") == BASE_USED
             and binding["ledger_identity"].get("hard_total") == HARD_TOTAL, "invalid ledger binding")
    if phase in {"candidate", "followup", "reviewed_candidate", "delivery_candidate"}:
        ref = binding["baseline_binding"]
        baseline_path = Path(ref["path"])
        _require(file_digest(baseline_path) == ref["sha256"], "baseline binding drift")
        # Check phase before recursion; a malformed reference cannot form a cycle.
        baseline_raw = json.loads(baseline_path.read_text(encoding="utf-8"))
        _require((phase == "delivery_candidate" and baseline_raw.get("phase") == "reviewed_candidate")
                 or (phase != "delivery_candidate" and (baseline_raw.get("phase") == "baseline"
                     or phase in {"followup", "reviewed_candidate"} and baseline_raw.get("phase") == "repair_baseline")),
                 "comparison requires the correct historical baseline binding")
        baseline, _ = load_binding(baseline_path, require_current=False)
        verify_comparison(binding, baseline)
        if phase in {"reviewed_candidate", "delivery_candidate"}:
            expected_baseline = "reviewed_candidate" if phase == "delivery_candidate" else "repair_baseline"
            _require(baseline_raw.get("phase") == expected_baseline, "development requires the correct historical baseline")
            _require(binding["ledger_identity"] == baseline["ledger_identity"], "reviewed development ledger drift")
            _require([c["case_id"] for c in schedule] == ["P01", "P04", "P08", "P02"], "reviewed development order drift")
        _require(end <= _time(baseline["frozen_at"]) + timedelta(days=7),
                 "comparison window exceeds baseline window")
        prior_cells = {c["case_id"]: c for c in baseline["cells"]}
        _require(all(c["request_sha256"] == prior_cells[c["case_id"]]["request_sha256"]
                     and c["hitl"] == prior_cells[c["case_id"]]["hitl"] for c in schedule),
                 "comparison request/HITL drift")
    if locked_candidate is not None:
        frozen_dev = {c["case_id"]: c for c in locked_candidate["cells"]}
        policies = {}
        for cell in schedule:
            case_id = cell["case_id"]
            _require(case_id not in policies or policies[case_id] == cell["hitl"], "repeated HITL policy drift")
            policies[case_id] = cell["hitl"]
            if cases[case_id]["split"] == "development":
                prior = frozen_dev[case_id]
                _require(cell["request_sha256"] == prior["request_sha256"] and cell["hitl"] == prior["hitl"],
                         "locked development request/HITL drift")
    return binding, cases


def verify_comparison(binding: dict, baseline: dict) -> None:
    keys = ("configuration_sha256", "dependency_snapshot_sha256", "knowledge_sha256",
            "embedding_revision", "settings", "model_id", "endpoint_sha256")
    _require(Path(binding["environment"]["tavily_state_path"]).resolve()
             == Path(baseline["environment"]["tavily_state_path"]).resolve(), "shared key-state path drift")
    historical = ((binding.get("phase"), baseline.get("phase")) in {
                    ("reviewed_candidate", "repair_baseline"), ("delivery_candidate", "reviewed_candidate")}
                  and binding.get("comparison_mode") == "historical-baseline-different-collector-v1")
    _require(historical or binding["identity"]["runner_commit"] == baseline["identity"]["runner_commit"],
             "comparison runner drift")
    _require(binding["environment"].get("knowledge_audit") == baseline["environment"].get("knowledge_audit"),
             "comparison audit identity drift")
    _require(all(binding["environment"][key] == baseline["environment"][key] for key in keys)
             and binding["source_policy"] == baseline["source_policy"], "comparison environment drift")


def load_candidate_lock(lock: dict | None, production_commit: str) -> dict:
    _require(isinstance(lock, dict) and lock.get("production_commit") == production_commit
             and _hash(lock.get("development_review_sha256")), "acceptance requires candidate/review lock")
    lock_path = Path(lock["path"])
    _require(file_digest(lock_path) == lock["development_review_sha256"], "candidate lock drift")
    review = json.loads(lock_path.read_text(encoding="utf-8"))
    _require(review.get("accepted") is True and review.get("candidate_commit") == production_commit,
             "candidate review is not accepted")
    ref = review["candidate_binding"]
    candidate_path = Path(ref["path"])
    _require(file_digest(candidate_path) == ref["sha256"], "reviewed candidate binding drift")
    raw = json.loads(candidate_path.read_text(encoding="utf-8"))
    _require(raw.get("phase") in {"candidate", "followup", "reviewed_candidate", "delivery_candidate"}, "review requires a development candidate")
    candidate, _ = load_binding(candidate_path, require_current=False)
    _require(candidate["identity"]["production_commit"] == production_commit, "reviewed candidate identity drift")
    if candidate["phase"] in {"reviewed_candidate", "delivery_candidate"}:
        ref = review.get("development_matrix", {})
        _require(isinstance(ref.get("path"), str) and _hash(ref.get("sha256")), "closed development matrix is required")
        matrix_path = Path(ref["path"])
        _require(file_digest(matrix_path) == ref["sha256"], "development matrix drift")
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        _require(matrix.get("binding_sha256") == digest(candidate) and matrix.get("state") == "closed"
                 and matrix.get("planned") == matrix.get("admitted_or_uncertain") == 4
                 and matrix.get("stop_reason") is None, "development matrix is not complete and safe")
        cells = matrix.get("cells", [])
        _require(len(cells) == 4 and [c.get("cell_id") for c in cells] == [c["cell_id"] for c in candidate["cells"]]
                 and all(c.get("status") in TERMINAL_STATUSES for c in cells), "development matrix cells drift")
        summary = review.get("development_summary", {})
        usable = summary.get("usable_and_supported")
        _require(type(usable) is int and 3 <= usable <= 4
                 and type(matrix.get("completed_consistent")) is int and usable <= matrix["completed_consistent"] <= 4
                 and type(summary.get("critical_errors")) is int and summary["critical_errors"] == 0
                 and summary.get("no_material_regression") is True
                 and summary.get("independent_review_passed") is True, "development promotion gate not met")
    return candidate


class ResearchLedger:
    """Append-only experiment admissions; uncertain dispatches are never refunded."""

    @classmethod
    def initialize(cls, path: Path, reconciliation: Path) -> "ResearchLedger":
        """Explicit first-use reconciliation; never called by freeze/collect."""
        proof = json.loads(reconciliation.read_text(encoding="utf-8"))
        _require(proof.get("protocol") == PROTOCOL and proof.get("used") == BASE_USED
                 and proof.get("new_protocol_admissions") == 0 and proof.get("reviewed") is True
                 and _hash(proof.get("evidence_sha256")), "initial research reconciliation required")
        evidence_path = Path(proof["evidence_path"]).resolve()
        _require(file_digest(evidence_path) == proof["evidence_sha256"], "research reconciliation evidence drift")
        path.parent.mkdir(parents=True, exist_ok=True)
        marker = path.with_suffix(".identity.json")
        # A failed initialization leaves its marker and requires manual reconciliation.
        identity = {"protocol": PROTOCOL, "ledger_id": uuid.uuid4().hex,
                    "base_used": BASE_USED, "hard_total": HARD_TOTAL,
                    "reconciliation_sha256": file_digest(reconciliation),
                    "evidence_path": str(evidence_path), "evidence_sha256": proof["evidence_sha256"]}
        _require(not path.exists(), "research ledger already exists")
        write_json(marker, identity, exclusive=True)
        with path.open("xb"):
            pass
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE identity (value TEXT NOT NULL)")
            db.execute("INSERT INTO identity VALUES (?)", (json.dumps(identity, sort_keys=True),))
            db.execute("CREATE TABLE admissions (ordinal INTEGER PRIMARY KEY, batch TEXT NOT NULL,"
                       "cell TEXT NOT NULL, phase TEXT NOT NULL, at TEXT NOT NULL, UNIQUE(batch, cell))")
        with path.with_suffix(".admissions.jsonl").open("x", encoding="utf-8"):
            pass
        return cls(path)

    def __init__(self, path: Path):
        self.path = path.resolve()
        self.identity = json.loads(path.with_suffix(".identity.json").read_text(encoding="utf-8"))
        _require(self.identity.get("protocol") == PROTOCOL
                 and self.identity.get("base_used") == BASE_USED
                 and self.identity.get("hard_total") == HARD_TOTAL, "invalid research ledger identity")
        self.used()

    @contextmanager
    def _connect(self):
        # mode=rw never creates a missing database; context managers commit AND close.
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=5)) as db, db:
            yield db

    def _extension(self, db) -> dict | None:
        table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='budget_extensions'").fetchone()
        rows = db.execute("SELECT value FROM budget_extensions").fetchall() if table else []
        witness = self.path.with_suffix(".extension.json")
        if not table and not witness.exists():
            return None
        _require(len(rows) == 1 and witness.exists(), "budget extension witness mismatch")
        ref = json.loads(rows[0][0])
        _require(json.loads(witness.read_text(encoding="utf-8")) == ref, "budget extension witness mismatch")
        validate_budget_extension(ref, self.identity)
        return ref

    def authorize_extension(self, ref: dict) -> None:
        """Explicit grant installation; never called automatically by freeze/collect."""
        grant = validate_budget_extension(ref, self.identity)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = self._checked_rows(db)
            _require(self._extension(db) is None, "budget extension already installed")
            _delivery_allocation(rows)
            _require(BASE_USED + len(rows) == 131 and digest(rows) == grant["prior_admissions_sha256"],
                     "budget extension historical admissions mismatch")
            db.execute("CREATE TABLE IF NOT EXISTS budget_extensions (value TEXT NOT NULL)")
            db.execute("INSERT INTO budget_extensions VALUES (?)", (json.dumps(ref, sort_keys=True),))
            write_json(self.path.with_suffix(".extension.json"), ref, exclusive=True)

    def extension_ref(self) -> dict | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._checked_rows(db)
            return self._extension(db)

    def _checked_rows(self, db) -> list:
        identities = db.execute("SELECT value FROM identity").fetchall()
        _require(len(identities) == 1 and json.loads(identities[0][0]) == self.identity,
                 "research ledger identity drift")
        rows = db.execute("SELECT ordinal,batch,cell,phase,at FROM admissions ORDER BY ordinal").fetchall()
        journal = [json.loads(line) for line in self.path.with_suffix(".admissions.jsonl")
                   .read_text(encoding="utf-8").splitlines()]
        _require([list(row) for row in rows] == journal
                 and [row[0] for row in rows] == list(range(BASE_USED + 1, BASE_USED + len(rows) + 1)),
                 "research ledger/journal mismatch; reconcile before admission")
        extension = self._extension(db)
        _require(all(row[3] in PHASE_LIMITS for row in rows), "unknown research phase")
        if extension is None:
            _require(not any(row[3] == "delivery_candidate" for row in rows)
                     and BASE_USED + len(rows) <= HARD_TOTAL, "budget extension is missing")
        else:
            grant = validate_budget_extension(extension, self.identity)
            _require(len(rows) >= 17 and digest(rows[:17]) == grant["prior_admissions_sha256"]
                     and BASE_USED + len(rows) <= 159, "budget extension history drift")
        return rows

    def used(self) -> int:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return BASE_USED + len(self._checked_rows(db))

    def require_unused_phase(self, phase: str, count: int, *, budget_extension: dict | None = None) -> None:
        """Preparation only; actual admission remains serialized in reserve()."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = self._checked_rows(db)
            extension = self._extension(db)
            if phase == "delivery_candidate" or extension is not None:
                _require(extension is not None and budget_extension == extension, "budget extension binding mismatch")
                _require(phase in {"delivery_candidate", "acceptance"}, "extension cannot reopen an old phase")
                _delivery_allocation(rows)
            if phase == "acceptance":
                candidate_phase = "delivery_candidate" if extension else "reviewed_candidate"
                _require(sum(r[3] == candidate_phase for r in rows) == 4, "reviewed development is incomplete")
            _require(phase in PHASE_LIMITS and count == PHASE_LIMITS[phase], "invalid phase allocation")
            if phase == "reviewed_candidate":
                _reviewed_allocation(rows)
            _require(not any(row[3] == phase for row in rows), "phase already belongs to a frozen batch")
            _require(BASE_USED + len(rows) + count <= (159 if extension else HARD_TOTAL), "research allocation exhausted")

    def reserve(self, batch: str, cell: str, phase: str, *, expected_used: int,
                budget_extension: dict | None = None) -> int:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = self._checked_rows(db)
            used = BASE_USED + len(rows)
            phase_used = sum(row[3] == phase for row in rows)
            extension = self._extension(db)
            if phase == "delivery_candidate" or extension is not None:
                _require(extension is not None and budget_extension == extension, "budget extension binding mismatch")
                _require(phase in {"delivery_candidate", "acceptance"}, "extension cannot reopen an old phase")
                _delivery_allocation(rows)
                if phase == "delivery_candidate":
                    _require(used == 131 + phase_used, "delivery allocation history mismatch")
            if phase == "acceptance":
                candidate_phase = "delivery_candidate" if extension else "reviewed_candidate"
                start = 135 if extension else 131
                _require(sum(r[3] == candidate_phase for r in rows) == 4
                         and used == start + phase_used, "reviewed development is incomplete")
            _require(phase in PHASE_LIMITS, "unallocated research phase")
            _require(used == expected_used, "research ledger changed; reconcile before admission")
            _require(used < (159 if extension else HARD_TOTAL) and phase_used < PHASE_LIMITS[phase], "research allocation exhausted")
            _require(all(row[1] == batch for row in rows if row[3] == phase),
                     "phase allocation is limited to one frozen batch")
            if phase == "reviewed_candidate":
                _reviewed_allocation(rows)
                _require(used + (4 - phase_used) + 24 <= 155, "final acceptance allocation must remain reserved")
            if phase == "repair_baseline":
                _require(used >= 119, "repair requires a reconciled batch")
            row = (used + 1, batch, cell, phase, datetime.now(UTC).isoformat())
            db.execute("INSERT INTO admissions VALUES (?,?,?,?,?)", row)
            # Write ahead to a separate witness. A crash or failed DB commit fails
            # closed on the next read, instead of refunding a possibly dispatched call.
            with self.path.with_suffix(".admissions.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(row) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return used + 1


def classify_record(record: dict) -> tuple[str, str | None]:
    """Known source/model failures can degrade; authority and unknowns stop."""
    if record.get("error_code") or record.get("collector_timeout"):
        return "safety_stop", record.get("error_code") or "COLLECTOR_TIMEOUT"
    if record.get("status") not in TERMINAL_STATUSES:
        return "safety_stop", "NONTERMINAL_RESULT"
    observation = record.get("observability") or {}
    if not record.get("observability_final") or observation.get("availability") != "available":
        return "safety_stop", "FINAL_OBSERVATION_UNAVAILABLE"
    failure = observation.get("run_failure_category")
    if record["status"] == "failed" or failure not in {None, "run_timeout", "cancelled"}:
        return "safety_stop", "RUN_FAILURE_REQUIRES_RECONCILIATION"
    budget = observation.get("budget") or {}
    if (budget.get("availability") != "available" or budget.get("policy_version") != "standard-enforced-v1"
            or budget.get("enforcement_mode") != "enforced" or budget.get("admission_denied") is not False):
        return "safety_stop", "BUDGET_AUTHORITY_OR_DENIAL"
    for resource, limit in RUN_LIMITS.items():
        row = budget.get("resources", {}).get(resource) or {}
        if (row.get("availability") != "available" or row.get("hard_limit") != limit
                or row.get("reserved") != 0):
            return "safety_stop", "BUDGET_STATE_UNVERIFIED"
    for row in budget.get("resources", {}).values():
        if row.get("reserved") not in (0, None):
            return "safety_stop", "BUDGET_STATE_UNVERIFIED"
    expected_failure = {"timed_out": "run_timeout", "cancelled": "cancelled"}.get(record["status"])
    if failure != expected_failure:
        return "safety_stop", "RUN_FAILURE_REQUIRES_RECONCILIATION"
    degraded = False
    for call in observation.get("calls", []):
        category = call.get("failure_category")
        if category is not None:
            if category not in ORDINARY_CALL_FAILURES and category != expected_failure:
                return "safety_stop", "UNCLASSIFIED_OR_AUTHORITY_CALL_FAILURE"
            degraded = True
        elif call.get("status") != "succeeded":
            return "safety_stop", "UNCLASSIFIED_CALL_FAILURE"
    if record["status"] not in SUCCESS_STATUSES:
        return "runtime_failed", None
    if record.get("artifact_consistent") is not True:
        return "safety_stop", "RESULT_ARTIFACT_INCONSISTENT"
    if record["status"] == "completed_with_warnings":
        return "restricted_or_degraded", None
    source = record.get("source_projection") or {}
    degraded = degraded or bool(source.get("partial_failure_count")) or bool(source.get("non_success_source_count"))
    if degraded:
        return "source_or_model_degraded", None
    # Artifact completion makes no claim that best-effort Trace captured every call.
    return "artifact_complete", None


def source_projection(snapshot: dict) -> dict:
    partial = snapshot.get("partial_failures")
    results = snapshot.get("search_results")
    counts = (snapshot.get("citation_verification") or {}).get("status_counts")
    return {
        "partial_failure_count": len(partial) if isinstance(partial, list) else None,
        "non_success_source_count": sum(item.get("status") != "success" for item in results
                                        if isinstance(item, dict)) if isinstance(results, list) else None,
        "citation_status_counts": {key: counts.get(key) for key in ("verified", "unsupported", "unreachable", "unknown")
                                   if type(counts.get(key)) is int and counts[key] >= 0} if isinstance(counts, dict) else None,
        "trace_completeness": "unknown-best-effort",
    }


class QualityCollector(DurableBaselineCollector):
    def __init__(self, *args, binding_hash: str, claim, **kwargs):
        super().__init__(*args, **kwargs)
        self.binding_hash = binding_hash
        self.claim = claim
        self._raw_report: str | None = None
        self._raw_snapshot: dict | None = None

    async def _healthy(self) -> bool:
        response, identity = await self._request_json("GET", "/evaluation/identity")
        if response.status_code != 200 or identity != {"binding_sha256": self.binding_hash}:
            self._abort_reason = "EVALUATION_SERVER_IDENTITY_MISMATCH"
            return False
        return await super()._healthy()

    async def _journal(self, record: dict, event: str) -> None:
        if event == "submission_started":
            record["research_ordinal"] = self.claim()
        await super()._journal(record, event)

    async def _request_json(self, method: str, path: str, **kwargs):
        response, payload = await super()._request_json(method, path, **kwargs)
        if response.status_code == 200 and payload:
            if path.endswith("/report"):
                self._raw_report = payload.get("report")
            elif path.endswith("/snapshot"):
                self._raw_snapshot = payload
        return response, payload

    async def _collect_artifacts(self, record: dict) -> None:
        await super()._collect_artifacts(record)
        if record.get("error_code") or record["status"] not in SUCCESS_STATUSES:
            return
        response = await self.client.get(f"/api/v1/tasks/{record['task_id']}/export", params={"format": "md"})
        if response.status_code != 200:
            record["error_code"] = "MARKDOWN_EXPORT_UNAVAILABLE"
            return
        record["source_projection"] = source_projection(self._raw_snapshot or {})
        exported = response.content.decode("utf-8")
        report = self._raw_report
        snapshot_report = (self._raw_snapshot or {}).get("report")
        record["artifact_consistent"] = (
            isinstance(report, str) and bool(report.strip()) and report == snapshot_report == exported)
        relative = Path(record["split"]) / "reports" / f"{record['case_id']}.export.md"
        (self.output_dir / relative).write_bytes(response.content)
        record["export_path"] = relative.as_posix()
        record["report_sha256"] = hashlib.sha256(report.encode()).hexdigest() if isinstance(report, str) else None
        if not record["artifact_consistent"]:
            record["error_code"] = "RESULT_ARTIFACT_INCONSISTENT"


async def collect_batch(binding: dict, cases: dict[str, dict], root: Path,
                        ledger: ResearchLedger, client: httpx.AsyncClient) -> dict:
    """One serial pass. A claimed directory is never resumed or overwritten."""
    if binding["phase"] == "reviewed_candidate":
        validate_development_authorization(binding.get("development_authorization"), binding["ledger_identity"])
    if binding["phase"] == "delivery_candidate" or binding.get("budget_extension") is not None:
        validate_budget_extension(binding.get("budget_extension"), binding["ledger_identity"])
    _require(ledger.extension_ref() == binding.get("budget_extension"), "budget extension binding mismatch")
    binding_hash = digest(binding)
    _require(ledger.identity == binding["ledger_identity"], "research ledger identity drift")
    _require(ledger.used() == binding["starting_used"], "stale starting research ledger")
    root.mkdir(parents=True, exist_ok=False)
    write_json(root / "binding.json", binding, exclusive=True)
    summary = {
        "schema_version": 1, "protocol": PROTOCOL, "binding_sha256": binding_hash,
        "state": "running", "planned": len(binding["cells"]), "admitted_or_uncertain": 0,
        "completed_consistent": 0, "quality_review": "not_evaluated", "stop_reason": None,
        "cells": [{"cell_id": c["cell_id"], "case_id": c["case_id"], "repetition": c["repetition"],
                   "status": "not_submitted", "reason": "not_reached"} for c in binding["cells"]],
    }
    write_json(root / "matrix.json", summary)
    try:
        for index, cell in enumerate(binding["cells"]):
            _require(datetime.now(UTC) <= _time(binding["valid_until"]), "binding expired before admission")
            directory = root / "cells" / cell["cell_id"]
            directory.mkdir(parents=True)
            case = deepcopy(cases[cell["case_id"]])
            case["hitl"] = deepcopy(cell["hitl"])
            options = CollectionOptions(profile=binding["phase"], repetition=cell["repetition"],
                                        concurrency=1, poll_interval_seconds=1, case_timeout_seconds=1800,
                                        expected_manifest_id=cell["manifest_id"])
            def claim():
                if binding["phase"] == "reviewed_candidate":
                    validate_development_authorization(binding.get("development_authorization"), ledger.identity)
                ordinal = ledger.reserve(binding_hash, cell["cell_id"], binding["phase"],
                                         expected_used=binding["starting_used"] + index,
                                         budget_extension=binding.get("budget_extension"))
                # Persist uncertainty before allowing the POST, including cancellation.
                summary["cells"][index].update(status="admitted_or_uncertain",
                                               reason="submission_requires_reconciliation",
                                               research_ordinal=ordinal)
                summary["admitted_or_uncertain"] += 1
                write_json(root / "matrix.json", summary)
                return ordinal
            collector = QualityCollector(client, directory, experiment_id=binding_hash,
                                         dataset_hash=digest(binding["datasets"]), options=options,
                                         binding_hash=binding_hash, claim=claim)
            record = (await collector.collect([case]))[0]
            outcome, stop = classify_record(record)
            summary["cells"][index].update(status=record["status"], reason=stop, outcome=outcome,
                                           record_path=(directory / "runs.jsonl").relative_to(root).as_posix(),
                                           task_id=record.get("task_id"), run_id=record.get("run_id"))
            summary["admitted_or_uncertain"] = ledger.used() - binding["starting_used"]
            if record.get("artifact_consistent") is True and record["status"] in SUCCESS_STATUSES:
                summary["completed_consistent"] += 1
            write_json(root / "matrix.json", summary)
            if stop or collector._abort_reason:
                summary["stop_reason"] = stop or collector._abort_reason
                break
    except BaseException as exc:
        summary["stop_reason"] = type(exc).__name__
        raise
    finally:
        try:
            summary["admitted_or_uncertain"] = ledger.used() - binding["starting_used"]
        except (ValueError, OSError, sqlite3.Error):
            summary["admitted_or_uncertain"] = None
            summary["stop_reason"] = "RESEARCH_LEDGER_REQUIRES_RECONCILIATION"
        summary["state"] = "closed"
        summary["ended_at"] = datetime.now(UTC).isoformat()
        for cell in summary["cells"]:
            if cell["status"] == "not_submitted":
                cell["reason"] = summary["stop_reason"] or "not_reached"
        write_json(root / "matrix.json", summary)
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "collect"])
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--execute-paid-runs", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "collect" and not args.execute_paid_runs:
        parser.error("collect requires --execute-paid-runs")
    binding, cases = load_binding(args.binding)
    if args.command == "validate":
        print(json.dumps({"binding_sha256": digest(binding), "cells": len(binding["cells"]), "passed": True}))
        return 0
    _require(args.output is not None, "collection requires a fresh output directory")
    parsed = httpx.URL(args.api_base)
    _require(parsed.scheme == "http" and parsed.host == "127.0.0.1" and not parsed.username
             and not parsed.password and not parsed.query and not parsed.fragment and parsed.path == "/", "only local evaluation API is supported")
    from benchmarks.quality_selection_runtime import verify_runner
    verify_runner(binding)
    # One shared ledger in the runner checkout, including baseline-server runs.
    ledger = ResearchLedger(Path(__file__).resolve().parents[1] / "outputs/quality-selection-v1-ledger.sqlite3")

    async def run():
        async with httpx.AsyncClient(base_url=args.api_base, timeout=30) as client:
            return await collect_batch(binding, cases, args.output, ledger, client)

    summary = asyncio.run(run())
    print(json.dumps({k: summary[k] for k in ("state", "planned", "admitted_or_uncertain",
                                             "completed_consistent", "stop_reason")}))
    return 1 if summary["stop_reason"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
