"""Copy a prepared case into an independent seal and verify it later.

This is deliberately a small, offline handoff helper, not an evaluation platform.
The preparer finishes writing first. The executor then calls `seal_case` once to
copy the complete case into a new directory and record every file's bytes/hash.
Research output and post-run notes are written elsewhere; the sealed copies are
never edited. `verify_seal` recomputes the recorded hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from datetime import datetime, timezone

FROZEN_EVALUATION_ENV = {
    "LEARNED_DOCS_READONLY": "1",
    "RETRIEVAL_CACHE_ENABLED": "0",
}


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")).hexdigest()


def seal_case(files, seal_dir, *, payload_path=None, notes: str = "") -> dict:
    """Copy files into a new seal and return the manifest.

    `seal_dir` must not exist. The source files are only read. The manifest is the
    last file written; a post-run addendum must go outside `seal_dir`.
    """
    files = [pathlib.Path(path) for path in files]
    seal = pathlib.Path(seal_dir)
    if seal.exists():
        raise FileExistsError(f"seal directory already exists: {seal}")
    if not files:
        raise ValueError("at least one case file is required")
    names = [path.name for path in files]
    if len(set(names)) != len(names):
        raise ValueError("case file names must be unique")
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(path)
    payload = None
    if payload_path is not None:
        payload_path = pathlib.Path(payload_path)
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        if not isinstance(payload.get("query"), str):
            raise ValueError("payload has no query")
        if payload_path not in files:
            files.append(payload_path)
            names.append(payload_path.name)
            if len(set(names)) != len(names):
                raise ValueError("case file names including payload must be unique")

    seal.mkdir(parents=True)
    entries = []
    for source in files:
        target = seal / source.name
        data = source.read_bytes()
        target.write_bytes(data)
        entries.append({
            "name": source.name,
            "source_path": str(source),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    manifest = {
        "seal_version": "case-seal-v1",
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "sealed_files": entries,
        "payload_name": payload_path.name if payload_path is not None else None,
        "payload_file_sha256": next(
            (entry["sha256"] for entry in entries
             if payload_path is not None and entry["name"] == payload_path.name), None),
        "payload_canonical_sha256": (_canonical_sha256(payload)
                                     if payload is not None else None),
        "query_sha256": (hashlib.sha256(payload["query"].encode("utf-8")).hexdigest()
                         if payload is not None else None),
        "frozen_evaluation_env": dict(FROZEN_EVALUATION_ENV),
        "notes": notes,
    }
    (seal / "seal_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def verify_seal(seal_dir) -> dict:
    """Recompute every sealed file hash and the payload identity."""
    seal = pathlib.Path(seal_dir)
    manifest_path = seal / "seal_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for entry in manifest.get("sealed_files") or []:
        path = seal / entry["name"]
        if not path.is_file():
            errors.append(f"missing: {entry['name']}")
            continue
        if path.stat().st_size != entry["bytes"]:
            errors.append(f"size mismatch: {entry['name']}")
        if _sha256(path) != entry["sha256"]:
            errors.append(f"hash mismatch: {entry['name']}")
    allowed = {entry["name"] for entry in manifest.get("sealed_files") or []}
    allowed.add("seal_manifest.json")
    for path in seal.iterdir():
        if path.is_file() and path.name not in allowed:
            errors.append(f"unexpected file in seal: {path.name}")
    payload_entry = next(
        (entry for entry in manifest.get("sealed_files") or []
         if entry["name"] == manifest.get("payload_name")), None)
    if payload_entry:
        payload = json.loads((seal / payload_entry["name"]).read_text(encoding="utf-8"))
        if _canonical_sha256(payload) != manifest.get("payload_canonical_sha256"):
            errors.append("payload canonical hash mismatch")
        if hashlib.sha256(payload["query"].encode("utf-8")).hexdigest() != \
                manifest.get("query_sha256"):
            errors.append("query hash mismatch")
    if manifest.get("frozen_evaluation_env") != FROZEN_EVALUATION_ENV:
        errors.append("frozen evaluation env mismatch")
    return {"ok": not errors, "errors": errors, "seal_dir": str(seal)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Seal a prepared research case")
    parser.add_argument("--seal-dir", required=True)
    parser.add_argument("--payload", required=True)
    parser.add_argument("--file", action="append", default=[],
                        help="additional frozen case file (repeatable)")
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)
    manifest = seal_case(args.file, args.seal_dir, payload_path=args.payload,
                         notes=args.notes)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise sys.exit(main())
