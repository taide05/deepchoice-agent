"""Offline counts of recorded O1 judgments; no model, network or research calls."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ("P01-r1", "P01-r2", "P06-r1", "P06-r2", "P07-r1", "P07-r2")
SUPPORT = {"supported", "partial", "unsupported", "unknown", "uncited"}
QUALITY = {"eligible", "ineligible", "unknown"}


def audit(contract: dict, claims: list[dict], bindings: dict) -> dict:
    """Validate recorded identity/structure, not semantic judgment correctness."""
    if contract.get("policy") != "key-claim-occurrence-v1":
        raise ValueError("unsupported claim policy")
    if contract.get("dataset_hash") != bindings.get("dataset_hash"):
        raise ValueError("dataset identity mismatch")
    if tuple(contract.get("reports", {})) != REPORTS:
        raise ValueError("only six authorized development reports are allowed")
    bound = {f"{r['case_id']}-r{r['repetition']}": r for r in bindings["rows"]}
    if set(bound) != set(REPORTS) or len(bindings["rows"]) != 6:
        raise ValueError("invalid report bindings")
    counts = {key: Counter() for key in REPORTS}
    lines = {key: set() for key in REPORTS}
    atoms: Counter = Counter()
    previous = (-1, -1)
    for row in claims:
        key = row["report"]
        if key not in counts:
            raise ValueError("unauthorized report")
        line, atom = int(row["line"]), int(row["atom"])
        position = (REPORTS.index(key), line)
        if line <= 0 or position < previous:
            raise ValueError("claims must follow report occurrence order")
        previous = position
        atoms[key, line] += 1
        if atom != atoms[key, line]:
            raise ValueError("duplicate or nonsequential atom")
        if not row["claim"].strip() or row["basis"] not in contract["bases"]:
            raise ValueError("missing claim or evidence basis")
        if row["support"] not in SUPPORT or row["quality"] not in QUALITY:
            raise ValueError("invalid judgment")
        refs = row["citations"].split(";") if row["citations"] else []
        if len(refs) != len(set(refs)) or any(ref not in contract["citations"] for ref in refs):
            raise ValueError("invalid citation reference")
        if (row["support"] == "uncited") != (not refs):
            raise ValueError("uncited must have no valid citation")
        if row["quality"] == "eligible" and row["support"] != "supported":
            raise ValueError("eligible requires fully applicable supporting evidence")
        if row["issue"] and row["issue"] not in contract["issues"]:
            raise ValueError("unknown fact-check issue")
        lines[key].add(line)
        counts[key]["claims"] += 1
        counts[key][row["support"]] += 1
        counts[key][f"quality_{row['quality']}"] += 1
    reports = {}
    for key in REPORTS:
        spec, count = contract["reports"][key], counts[key]
        if spec["run_id"] != bound[key]["run_id"]:
            raise ValueError("run identity mismatch")
        if lines[key] != set(spec["claim_lines"]):
            raise ValueError("claim-line coverage mismatch")
        if {str(line): atoms[key, line] for line in lines[key]} != spec["atom_counts"]:
            raise ValueError("atomic occurrence coverage mismatch")
        if not count["claims"]:
            raise ValueError("empty denominator")
        reports[key] = {
            "run_id": bound[key]["run_id"], "manifest_id": bound[key]["manifest_id"],
            "report_sha256": bound[key]["report_sha256"],
            "claims": count["claims"],
            "support_counts": {s: count[s] for s in sorted(SUPPORT)},
            "quality_counts": {s: count[f"quality_{s}"] for s in sorted(QUALITY)},
            "citation_support_rate": count["supported"] / count["claims"],
            "source_quality_rate": count["quality_eligible"] / count["claims"],
        }
    total = sum(r["claims"] for r in reports.values())
    supported = sum(r["support_counts"]["supported"] for r in reports.values())
    eligible = sum(r["quality_counts"]["eligible"] for r in reports.values())
    return {
        "evaluation_timestamp": datetime.now(UTC).isoformat(),
        "review_date": contract["review_date"],
        "dataset_id": bindings["dataset_id"], "dataset_version": bindings["dataset_version"],
        "dataset_hash": bindings["dataset_hash"], "dataset_freeze_date": bindings["dataset_freeze_date"],
        "measured_candidate_commit": bindings["measured_candidate_commit"],
        "core_asset_registry_id": bindings["core_asset_registry_id"],
        "policy": contract["policy"], "review_mode": "assistant_review",
        "blind": False, "human_calibration": "not_run",
        "measured_source_health": bindings["source_health"], "current_source_health": "not_run",
        "overall_o1": "incomplete", "reports": reports,
        "aggregate": {
            "reports": 6, "claims": total, "supported": supported, "eligible": eligible,
            "citation_micro": supported / total, "quality_micro": eligible / total,
            "citation_macro": sum(r["citation_support_rate"] for r in reports.values()) / 6,
            "quality_macro": sum(r["source_quality_rate"] for r in reports.values()) / 6,
        },
    }


def verify_local(root: Path, bindings: dict, claims: list[dict], contract: dict) -> None:
    """Read exact bound development originals only, never enumerate outputs."""
    for binding in bindings["rows"]:
        key = f"{binding['case_id']}-r{binding['repetition']}"
        if key not in REPORTS:
            raise ValueError("unauthorized local report")
        relative = Path(binding["report_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe report path")
        report = (root / relative).resolve()
        if not report.is_relative_to((root / "outputs").resolve()):
            raise ValueError("report outside local outputs")
        if relative.parts[-3:] != ("development", "reports", f"{binding['case_id']}.md"):
            raise ValueError("not a development report")
        snapshot = (report.parent.parent / "snapshots" / f"{binding['case_id']}.json").resolve()
        if not snapshot.is_relative_to((root / "outputs").resolve()):
            raise ValueError("snapshot outside local outputs")
        for path, expected in ((report, binding["report_sha256"]), (snapshot, binding["snapshot_sha256"])):
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f"original hash mismatch: {key}")
        report_lines = report.read_text(encoding="utf-8").splitlines()
        for row in (r for r in claims if r["report"] == key):
            line = int(row["line"])
            if line <= 0 or line > len(report_lines):
                raise ValueError("claim outside report")
            for ref in filter(None, row["citations"].split(";")):
                if not any(title in report_lines[line - 1] for title in contract["citations"][ref]):
                    raise ValueError(f"citation absent at occurrence: {key}:{line}:{ref}")


def load_review(root: Path = ROOT) -> tuple[dict, list[dict], dict]:
    contract = json.loads((root / "docs/o1a-evaluation-contract.json").read_text(encoding="utf-8"))
    path = root / "docs/o1-development-review-bindings.json"
    if hashlib.sha256(path.read_bytes()).hexdigest() != contract["bindings_sha256"]:
        raise ValueError("historical binding file changed")
    bindings = json.loads(path.read_text(encoding="utf-8"))
    with (root / "docs/o1a-development-claims.csv").open(encoding="utf-8", newline="") as handle:
        claims = list(csv.DictReader(handle))
    return contract, claims, bindings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-local", action="store_true")
    args = parser.parse_args()
    contract, claims, bindings = load_review()
    result = audit(contract, claims, bindings)
    if args.verify_local:
        verify_local(ROOT, bindings, claims, contract)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
