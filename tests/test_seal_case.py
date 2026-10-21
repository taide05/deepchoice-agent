"""Simple case sealing: copy once, verify hashes, never overwrite."""
import json
import pathlib

import pytest

from scripts.seal_case import FROZEN_EVALUATION_ENV, seal_case, verify_seal


def _payload(path: pathlib.Path):
    path.write_text(json.dumps({"query": "which sandbox", "scene_context": "x",
                                "candidate_techs": ["A", "B"]},
                               ensure_ascii=False), encoding="utf-8")
    return path


def test_seal_copies_case_and_verifies_hashes(tmp_path):
    source = tmp_path / "case"
    source.mkdir()
    payload = _payload(source / "run_payload_v9.json")
    proposal = source / "proposal.json"
    proposal.write_text('{"case_id": "x"}', encoding="utf-8")
    seal_dir = tmp_path / "seal"
    manifest = seal_case([proposal], seal_dir, payload_path=payload)
    assert manifest["payload_name"] == "run_payload_v9.json"
    assert (seal_dir / "run_payload_v9.json").read_bytes() == payload.read_bytes()
    assert (seal_dir / "proposal.json").read_bytes() == proposal.read_bytes()
    assert manifest["frozen_evaluation_env"] == FROZEN_EVALUATION_ENV
    assert verify_seal(seal_dir)["ok"] is True
    # The source files are untouched by sealing.
    assert proposal.read_text(encoding="utf-8") == '{"case_id": "x"}'


def test_seal_refuses_to_overwrite_an_existing_seal(tmp_path):
    source = tmp_path / "case"
    source.mkdir()
    payload = _payload(source / "run_payload_v9.json")
    seal_dir = tmp_path / "seal"
    seal_dir.mkdir()
    with pytest.raises(FileExistsError):
        seal_case([payload], seal_dir, payload_path=payload)


def test_post_run_addendum_outside_seal_does_not_change_it(tmp_path):
    source = tmp_path / "case"
    source.mkdir()
    payload = _payload(source / "run_payload_v9.json")
    seal_dir = tmp_path / "seal"
    seal_case([payload], seal_dir, payload_path=payload)
    # Post-run notes belong outside the seal directory.
    (tmp_path / "run_addendum.md").write_text("post-run note", encoding="utf-8")
    assert verify_seal(seal_dir)["ok"] is True


def test_tampered_sealed_file_is_detected(tmp_path):
    source = tmp_path / "case"
    source.mkdir()
    payload = _payload(source / "run_payload_v9.json")
    seal_dir = tmp_path / "seal"
    seal_case([payload], seal_dir, payload_path=payload)
    (seal_dir / "run_payload_v9.json").write_text(
        json.dumps({"query": "changed"}), encoding="utf-8")
    result = verify_seal(seal_dir)
    assert result["ok"] is False
    assert any("hash mismatch" in error for error in result["errors"]) or \
        any("query hash" in error for error in result["errors"])
