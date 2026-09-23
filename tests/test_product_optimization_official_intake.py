"""Fail-closed tests for the offline official-source intake plan."""

from __future__ import annotations

import json
import stat
from types import SimpleNamespace
from pathlib import Path

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


def test_loads_exact_frozen_plan_and_deduplicates_catalog_aliases() -> None:
    plan = load_official_intake_plan()

    assert plan.plan_id == "product-optimization-official-intake-v1"
    assert plan.catalog_git_object == intake.CATALOG_GIT_OBJECT
    assert plan.byte_sha256 == intake.PLAN_BYTES_SHA256
    assert len(plan.entries) == 93
    assert len({entry.url for entry in plan.entries}) == 93
    assert plan.entries[9].catalog_key == "node.js"
    assert plan.entries[51].catalog_key == "chroma"
    assert plan.entries[74].catalog_key == "pydantic"
    assert all(entry.catalog_label_unverified for entry in plan.entries)


def test_loader_only_opens_the_fixed_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    original_open = Path.open
    opened: list[Path] = []

    def guarded_open(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        opened.append(self)
        if self.name in {
            "product-baseline-v1.json",
            "cases_200.json",
            "learned_docs.json",
        } or "snapshots" in self.parts or "blogs" in self.parts:
            raise AssertionError(f"forbidden input opened: {self}")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    plan = load_official_intake_plan()
    assert len(plan.entries) == 93
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
    ],
)
def test_url_validator_rejects_unsafe_literal_or_locator(url: str) -> None:
    with pytest.raises(OfficialIntakePlanError, match="safe HTTPS identity"):
        intake._validate_url_identity(url)


def test_url_validator_allows_global_ip_literal_but_plan_mapping_still_binds() -> None:
    intake._validate_url_identity("https://8.8.8.8/docs")


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
    "mutation",
    [
        lambda payload: payload["entries"][0].update({"url": "http://127.0.0.1/private"}),
        lambda payload: payload["entries"][0].update({"url": "https://evil.example"}),
        lambda payload: payload["entries"][0].update({"catalog_key": "nodejs"}),
        lambda payload: payload["entries"].append(payload["entries"][0]),
    ],
)
def test_malicious_private_alias_or_duplicate_url_fails_closed(mutation) -> None:  # type: ignore[no-untyped-def]
    payload = _payload()
    mutation(payload)

    with pytest.raises(OfficialIntakePlanError):
        _parse_plan_bytes(_bytes(payload))


def test_duplicate_json_keys_fail_closed() -> None:
    with pytest.raises(OfficialIntakePlanError, match="duplicate JSON object key"):
        _parse_plan_bytes(b'{"schema_version": 1, "schema_version": 1}')


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
    old_dataset = DEFAULT_PLAN_PATH.parent / "product-baseline-v1.json"
    monkeypatch.setattr(intake, "DEFAULT_PLAN_PATH", old_dataset)

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
