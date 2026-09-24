"""Fail-closed tests for content-reviewed official development sources."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from benchmarks import product_optimization_source_review as review_module
from benchmarks.product_optimization_official_intake import (
    CANONICAL_PLAN_SHA256,
    FIXTURE_ID,
    PLAN_BYTES_SHA256,
    PLAN_ID,
    OfficialIntakePlan,
    OfficialIntakeTarget,
)


def _json_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=True, indent=2) + "\n").encode("utf-8")


def _fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    text: bytes = b"Official product behavior and an explicit caveat.",
    capture_plan_id: str = PLAN_ID,
) -> tuple[dict, Path, OfficialIntakePlan]:
    target = OfficialIntakeTarget(
        target_id="p01-sqlite-guide",
        parent_catalog_key="sqlite",
        case_ids=("P01",),
        evidence_topics=("backup",),
        url="https://sqlite.org/guide.html",
        locator_label_unverified="SQLite Guide",
    )
    plan = OfficialIntakePlan(
        plan_id=PLAN_ID,
        freeze_date="2026-09-24",
        parent_plan_id="product-optimization-official-intake-v2",
        development_fixture_id=FIXTURE_ID,
        canonical_plan_sha256=CANONICAL_PLAN_SHA256,
        byte_sha256=PLAN_BYTES_SHA256,
        targets=(target,),
    )
    root = tmp_path / "captures"
    directory = root / "p01-sqlite-guide-demo"
    directory.mkdir(parents=True)
    raw = b"<html><body><p>Official product behavior.</p></body></html>"
    (directory / "response.html").write_bytes(raw)
    (directory / "body.txt").write_bytes(text)
    byte_sha, canonical_sha = review_module._CAPTURE_PLAN_IDENTITIES[capture_plan_id]
    receipt = {
        "schema_version": 2,
        "status": "candidate_unapproved",
        "plan_id": capture_plan_id,
        "plan_byte_sha256": byte_sha,
        "plan_canonical_sha256": canonical_sha,
        "development_fixture_id": FIXTURE_ID,
        "target_id": target.target_id,
        "parent_catalog_key": target.parent_catalog_key,
        "case_ids": list(target.case_ids),
        "evidence_topics": list(target.evidence_topics),
        "locator_label_unverified": target.locator_label_unverified,
        "start_url": target.url,
        "final_url": target.url,
        "http_status": 200,
        "content_type": "text/html",
        "captured_at": "2026-09-24T12:00:00+00:00",
        "raw_bytes": len(raw),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "extractor_id": "stdlib-html-text-v1",
        "text_bytes": len(text),
        "text_sha256": hashlib.sha256(text).hexdigest(),
    }
    receipt_bytes = _json_bytes(receipt)
    (directory / "receipt.json").write_bytes(receipt_bytes)
    payload = {
        "schema_version": review_module.REVIEW_SCHEMA_VERSION,
        "review_id": review_module.REVIEW_ID,
        "status": review_module.REVIEW_STATUS,
        "review_date": review_module.REVIEW_DATE,
        "reviewer_mode": review_module.REVIEWER_MODE,
        "plan": {
            "plan_id": plan.plan_id,
            "byte_sha256": plan.byte_sha256,
            "canonical_sha256": plan.canonical_plan_sha256,
        },
        "evidence_policy": dict(review_module._EVIDENCE_POLICY),
        "canonical_review_sha256": "0" * 64,
        "approved_sources": [{
            "target_id": target.target_id,
            "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
            "publisher": "SQLite Project",
            "approved_topics": ["backup"],
            "scope_note": "bounded-test-scope",
        }],
        "excluded_candidates": [],
    }
    monkeypatch.setattr(
        review_module, "_SCOPE_NOTES", {target.target_id: "bounded-test-scope"}
    )
    monkeypatch.setattr(review_module, "_EXCLUSIONS", {})
    _refreeze(payload, monkeypatch)
    return payload, root, plan


def _refreeze(payload: dict, monkeypatch: pytest.MonkeyPatch) -> bytes:
    canonical = review_module._canonical_sha(payload)
    payload["canonical_review_sha256"] = canonical
    monkeypatch.setattr(review_module, "CANONICAL_REVIEW_SHA256", canonical)
    return _json_bytes(payload)


@pytest.mark.parametrize(
    "capture_plan_id",
    ["product-optimization-official-intake-v2", PLAN_ID],
)
def test_review_accepts_exact_current_or_unchanged_predecessor_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capture_plan_id: str
) -> None:
    payload, root, plan = _fixture(
        tmp_path, monkeypatch, capture_plan_id=capture_plan_id
    )

    approved = review_module._parse_review_bytes(
        _json_bytes(payload), root, plan=plan
    )

    assert approved.plan_id == PLAN_ID
    assert approved.total_text_bytes == len(
        b"Official product behavior and an explicit caveat."
    )
    assert len(approved.sources) == 1
    source = approved.sources[0]
    assert source.target_id == "p01-sqlite-guide"
    assert source.content.startswith("Official product behavior")
    assert "Official product behavior" not in repr(source)


def test_review_rejects_replaced_predecessor_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload, root, plan = _fixture(
        tmp_path,
        monkeypatch,
        capture_plan_id="product-optimization-official-intake-v2",
    )
    directory = next(root.iterdir())
    receipt = json.loads((directory / "receipt.json").read_text(encoding="utf-8"))
    receipt["target_id"] = "p01-replaced-v2-target"
    replaced = _json_bytes(receipt)
    (directory / "receipt.json").write_bytes(replaced)
    payload["approved_sources"][0]["receipt_sha256"] = hashlib.sha256(replaced).hexdigest()

    with pytest.raises(review_module.SourceReviewError, match="approved target"):
        review_module._parse_review_bytes(
            _refreeze(payload, monkeypatch), root, plan=plan
        )


def test_review_rejects_body_drift_without_leaking_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload, root, plan = _fixture(tmp_path, monkeypatch)
    secret = b"PRIVATE-BODY-SENTINEL"
    (next(root.iterdir()) / "body.txt").write_bytes(secret)

    with pytest.raises(review_module.SourceReviewError, match="body hashes") as caught:
        review_module._parse_review_bytes(_json_bytes(payload), root, plan=plan)

    assert secret.decode() not in str(caught.value)


def test_review_rejects_benchmark_template_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload, root, plan = _fixture(
        tmp_path, monkeypatch, text=b"Expected Winner: SQLite\n"
    )

    with pytest.raises(review_module.SourceReviewError, match="benchmark marker"):
        review_module._parse_review_bytes(_json_bytes(payload), root, plan=plan)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (
            lambda payload: payload["plan"].update({"byte_sha256": "0" * 64}),
            "plan binding",
        ),
        (
            lambda payload: payload["approved_sources"][0].update(
                {"approved_topics": ["write-concurrency"]}
            ),
            "scope changed",
        ),
        (
            lambda payload: payload["approved_sources"][0].update(
                {"scope_note": "broader-claim"}
            ),
            "scope changed",
        ),
        (
            lambda payload: payload["approved_sources"][0].update(
                {"publisher": "Unknown"}
            ),
            "scope changed",
        ),
    ],
)
def test_review_rejects_plan_or_approval_scope_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation,  # type: ignore[no-untyped-def]
    match: str,
) -> None:
    payload, root, plan = _fixture(tmp_path, monkeypatch)
    mutation(payload)

    with pytest.raises(review_module.SourceReviewError, match=match):
        review_module._parse_review_bytes(_refreeze(payload, monkeypatch), root, plan=plan)


def test_review_rejects_duplicate_receipt_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload, root, plan = _fixture(tmp_path, monkeypatch)
    original = next(root.iterdir())
    duplicate = root / "duplicate"
    duplicate.mkdir()
    for name in ("receipt.json", "response.html", "body.txt"):
        (duplicate / name).write_bytes((original / name).read_bytes())

    with pytest.raises(review_module.SourceReviewError, match="duplicated"):
        review_module._parse_review_bytes(_json_bytes(payload), root, plan=plan)


def test_review_rejects_unavailable_required_exclusion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload, root, plan = _fixture(tmp_path, monkeypatch)
    digest = "a" * 64
    monkeypatch.setattr(
        review_module,
        "_EXCLUSIONS",
        {digest: ("p01-old", "superseded-by-substantive-v3-page")},
    )
    payload["excluded_candidates"] = [{
        "target_id": "p01-old",
        "receipt_sha256": digest,
        "reason": "superseded-by-substantive-v3-page",
    }]

    with pytest.raises(review_module.SourceReviewError, match="unavailable"):
        review_module._parse_review_bytes(_refreeze(payload, monkeypatch), root, plan=plan)


def test_public_loader_rejects_nonfixed_review_path_before_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wrong = tmp_path / "review.json"
    wrong.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(review_module, "DEFAULT_REVIEW_PATH", wrong)

    with pytest.raises(review_module.SourceReviewError, match="path is not approved"):
        review_module.load_approved_source_review()


def test_fixed_file_wraps_missing_file_without_local_path(tmp_path: Path) -> None:
    missing = tmp_path / "PRIVATE-LOCAL-PATH.json"

    with pytest.raises(review_module.SourceReviewError, match="unavailable") as caught:
        review_module._fixed_file(missing, missing, 1024, "source review")

    assert "PRIVATE-LOCAL-PATH" not in str(caught.value)


def test_capture_scan_wraps_os_error_without_local_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload, root, plan = _fixture(tmp_path, monkeypatch)
    original = review_module.Path.iterdir

    def broken_iterdir(path):  # type: ignore[no-untyped-def]
        if path == root:
            raise OSError("PRIVATE-LOCAL-PATH")
        return original(path)

    monkeypatch.setattr(review_module.Path, "iterdir", broken_iterdir)
    with pytest.raises(review_module.SourceReviewError, match="could not be scanned") as caught:
        review_module._parse_review_bytes(_json_bytes(payload), root, plan=plan)

    assert "PRIVATE-LOCAL-PATH" not in str(caught.value)
