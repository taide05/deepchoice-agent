"""Fail-closed tests for the development official-source intake plan."""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import benchmarks.product_optimization_official_intake as intake
from benchmarks.product_optimization_official_intake import (
    DEFAULT_PLAN_PATH,
    OfficialIntakePlanError,
    _parse_plan_bytes,
    load_official_intake_plan,
)


def _payload() -> dict:
    return json.loads(DEFAULT_PLAN_PATH.read_text(encoding="utf-8"))


def _bytes(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=True, indent=2) + "\n").encode("utf-8")


def _refreeze(payload: dict, monkeypatch: pytest.MonkeyPatch) -> bytes:
    canonical = intake._canonical_plan_sha256(payload)
    payload["canonical_plan_sha256"] = canonical
    monkeypatch.setattr(intake, "CANONICAL_PLAN_SHA256", canonical)
    return _bytes(payload)


def test_loads_exact_v3_plan_bound_to_v2_and_development_fixture() -> None:
    plan = load_official_intake_plan()

    assert plan.plan_id == "product-optimization-official-intake-v3"
    assert plan.parent_plan_id == "product-optimization-official-intake-v2"
    assert plan.development_fixture_id == "product-optimization-dev-requests-v1"
    assert plan.byte_sha256 == intake.PLAN_BYTES_SHA256
    assert len(plan.targets) == 15
    assert len({target.target_id for target in plan.targets}) == 15
    assert len({target.url for target in plan.targets}) == 15
    assert {case_id for target in plan.targets for case_id in target.case_ids} == {
        "P01",
        "P04",
        "P08",
    }
    assert all(target.locator_label_unverified for target in plan.targets)


def test_historical_v1_and_v2_plan_bytes_remain_unchanged() -> None:
    v1 = DEFAULT_PLAN_PATH.with_name("product-optimization-official-intake-v1.json")
    v2 = DEFAULT_PLAN_PATH.with_name("product-optimization-official-intake-v2.json")
    assert hashlib.sha256(v1.read_bytes()).hexdigest() == intake.HISTORICAL_V1_PLAN_BYTES_SHA256
    assert hashlib.sha256(v2.read_bytes()).hexdigest() == intake.PARENT_PLAN_BYTES_SHA256


def test_loader_only_opens_the_fixed_v3_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    original_open = Path.open
    opened: list[Path] = []

    def guarded_open(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        opened.append(self)
        if self.name in {
            "product-optimization-official-intake-v1.json",
            "product-optimization-official-intake-v2.json",
            "product-optimization-dev-requests-v1.json",
            "product-baseline-v1.json",
            "cases_200.json",
            "learned_docs.json",
        } or "snapshots" in self.parts or "blogs" in self.parts:
            raise AssertionError(f"forbidden input opened: {self}")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    plan = load_official_intake_plan()
    assert len(plan.targets) == 15
    assert opened == [DEFAULT_PLAN_PATH]


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/docs",
        "https://10.0.0.1/docs",
        "https://[::1]/docs",
        "https://localhost/docs",
        "https://service.local/docs",
        "https://internal/docs",
        "https://docs.example.test/docs?token=secret",
        "https://docs.example.test/docs#secret",
        "https://docs.example.test/a/../private",
        "https://docs.example.test/a\\private",
    ],
)
def test_url_validator_rejects_unsafe_literal_or_locator(url: str) -> None:
    with pytest.raises(OfficialIntakePlanError, match="safe HTTPS identity"):
        intake._validate_url_identity(url)


def test_url_validator_allows_public_canonical_deep_link() -> None:
    assert (
        intake._validate_url_identity("https://docs.example.test/guide/")
        == "docs.example.test"
    )


@pytest.mark.parametrize("mode", [stat.S_IFLNK, stat.S_IFREG])
def test_fixed_path_rejects_symlink_or_reparse_component(
    monkeypatch: pytest.MonkeyPatch, mode: int
) -> None:
    original_lstat = Path.lstat

    def fake_lstat(self: Path):
        if self == DEFAULT_PLAN_PATH:
            attributes = 0x0400 if mode == stat.S_IFREG else 0
            return SimpleNamespace(st_mode=mode, st_file_attributes=attributes)
        return original_lstat(self)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    with pytest.raises(OfficialIntakePlanError, match="symlink or reparse"):
        load_official_intake_plan()


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (
            lambda payload: payload["targets"][0].update(
                {"url": "http://127.0.0.1/private"}
            ),
            "safe HTTPS identity",
        ),
        (
            lambda payload: payload["targets"][0].update(
                {"url": "https://evil.example/private"}
            ),
            "parent catalog hostname",
        ),
        (
            lambda payload: payload["targets"][0].update(
                {"parent_catalog_key": "redis"}
            ),
            "case or parent binding",
        ),
        (
            lambda payload: payload["targets"][0].update(
                {"case_ids": ["P08"]}
            ),
            "case or parent binding",
        ),
        (
            lambda payload: payload["targets"][0].update(
                {"evidence_topics": ["invented-topic"]}
            ),
            "evidence topics",
        ),
        (
            lambda payload: payload["targets"].append(dict(payload["targets"][0])),
            "exactly 15",
        ),
    ],
)
def test_private_cross_scope_or_drifted_target_fails_closed(
    monkeypatch: pytest.MonkeyPatch, mutation, match: str  # type: ignore[no-untyped-def]
) -> None:
    payload = _payload()
    mutation(payload)

    with pytest.raises(OfficialIntakePlanError, match=match):
        _parse_plan_bytes(_refreeze(payload, monkeypatch))


def test_missing_required_topic_coverage_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload()
    for target_id in ("p01-sqlite-backup", "p01-postgresql-backup"):
        target = next(
            item for item in payload["targets"] if item["target_id"] == target_id
        )
        target["evidence_topics"] = ["operational-complexity"]

    with pytest.raises(OfficialIntakePlanError, match="P01 evidence topic coverage"):
        _parse_plan_bytes(_refreeze(payload, monkeypatch))


def test_duplicate_json_keys_fail_closed() -> None:
    with pytest.raises(OfficialIntakePlanError, match="duplicate JSON object key"):
        _parse_plan_bytes(b'{"schema_version": 3, "schema_version": 3}')


def test_catalog_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    drifted = dict(intake.TECH_DOCS)
    drifted["unapproved"] = {
        "url": "https://unapproved.example",
        "title": "Unapproved — Official Documentation",
    }
    monkeypatch.setattr(intake, "TECH_DOCS", drifted)

    with pytest.raises(OfficialIntakePlanError, match="catalog payload drifted"):
        _parse_plan_bytes(_bytes(_payload()))


def test_public_loader_rejects_old_data_path_before_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_plan = DEFAULT_PLAN_PATH.with_name("product-optimization-official-intake-v2.json")
    monkeypatch.setattr(intake, "DEFAULT_PLAN_PATH", old_plan)

    def forbidden_open(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("misconfigured path must be rejected before open")

    monkeypatch.setattr(Path, "open", forbidden_open)
    with pytest.raises(OfficialIntakePlanError, match="path is not approved"):
        load_official_intake_plan()


def test_public_loader_rejects_byte_drift_after_fixed_path_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(intake, "PLAN_BYTES_SHA256", "0" * 64)

    with pytest.raises(OfficialIntakePlanError, match="byte SHA changed"):
        load_official_intake_plan()
