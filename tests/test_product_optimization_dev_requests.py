"""Contract tests for the isolated development request projection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import benchmarks.product_optimization_dev_requests as projection
from benchmarks.product_optimization_dev_requests import (
    DEFAULT_FIXTURE_PATH,
    DevelopmentRequestFixtureError,
    EXPECTED_CASE_IDS,
    FIXTURE_BYTES_SHA256,
    _parse_fixture_bytes,
    load_dev_requests,
)


def _fixture_payload() -> dict:
    return json.loads(DEFAULT_FIXTURE_PATH.read_text(encoding="utf-8"))


def _fixture_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def test_loads_exact_frozen_development_requests() -> None:
    fixture = load_dev_requests()

    assert fixture.fixture_id == "product-optimization-dev-requests-v1"
    assert fixture.byte_sha256 == FIXTURE_BYTES_SHA256
    assert tuple(case.case_id for case in fixture.cases) == EXPECTED_CASE_IDS
    assert [case.role for case in fixture.cases] == ["regression", "target", "target"]
    assert fixture.cases[0].request.query.startswith("为个人维护")
    assert fixture.cases[1].request.candidate_techs == ["FastAPI BackgroundTasks", "Celery"]
    assert fixture.cases[2].request.candidate_techs == ["Redis", "Memcached"]


def test_loader_never_opens_old_dataset_or_source_snapshots(monkeypatch: pytest.MonkeyPatch) -> None:
    original_open = Path.open

    def guarded_open(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.name == "product-baseline-v1.json" or "snapshots" in self.parts:
            raise AssertionError(f"forbidden input opened: {self}")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    fixture = load_dev_requests()

    assert len(fixture.cases) == 3


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload.update({"unexpected": True}), "fixture keys changed"),
        (
            lambda payload: payload["cases"][0].update({"unexpected": True}),
            "keys changed",
        ),
        (
            lambda payload: payload["cases"][0]["request"].update({"unexpected": True}),
            "keys changed",
        ),
        (
            lambda payload: payload["cases"][1]["request"].update(
                {"query": "漂移后的请求"}
            ),
            "does not match the frozen request",
        ),
        (
            lambda payload: payload["cases"][2].update(
                {"source_snapshot_sha256": "0" * 64}
            ),
            "does not match the frozen binding",
        ),
        (
            lambda payload: payload["cases"].__setitem__(
                2, {**payload["cases"][2], "case_id": "P09"}
            ),
            "case IDs must be exactly",
        ),
    ],
)
def test_malicious_or_drifted_projection_fails_closed(
    mutation, message: str
) -> None:  # type: ignore[no-untyped-def]
    payload = _fixture_payload()
    mutation(payload)

    with pytest.raises(DevelopmentRequestFixtureError, match=message):
        _parse_fixture_bytes(_fixture_bytes(payload))


def test_invalid_json_fails_closed() -> None:
    with pytest.raises(DevelopmentRequestFixtureError, match="fixture must be an object"):
        _parse_fixture_bytes(b"[]")


def test_duplicate_json_keys_fail_closed() -> None:
    with pytest.raises(DevelopmentRequestFixtureError, match="duplicate JSON object key"):
        _parse_fixture_bytes(b'{"schema_version": 1, "schema_version": 1}')


def test_oversized_fixture_fails_closed() -> None:
    with pytest.raises(DevelopmentRequestFixtureError, match="exceeds 65536 bytes"):
        _parse_fixture_bytes(b"{" + b" " * (64 * 1024) + b"}")


def test_freeze_date_and_projection_identity_are_exact() -> None:
    payload = _fixture_payload()
    payload["freeze_date"] = "2026-09-24"
    with pytest.raises(DevelopmentRequestFixtureError, match="freeze_date changed"):
        _parse_fixture_bytes(_fixture_bytes(payload))

    payload = _fixture_payload()
    payload["projection"]["source_kind"] = "other"
    with pytest.raises(DevelopmentRequestFixtureError, match="projection contract changed"):
        _parse_fixture_bytes(_fixture_bytes(payload))


def test_public_entry_rejects_old_dataset_path_before_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_dataset = DEFAULT_FIXTURE_PATH.parent / "product-baseline-v1.json"
    monkeypatch.setattr(projection, "DEFAULT_FIXTURE_PATH", old_dataset)

    def forbidden_open(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("the misconfigured path must be rejected before open")

    monkeypatch.setattr(Path, "open", forbidden_open)
    with pytest.raises(DevelopmentRequestFixtureError, match="path is not approved"):
        load_dev_requests()


def test_public_entry_rejects_byte_drift_after_fixed_path_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(projection, "FIXTURE_BYTES_SHA256", "0" * 64)

    with pytest.raises(DevelopmentRequestFixtureError, match="byte SHA changed"):
        load_dev_requests()


def test_private_parser_does_not_need_old_dataset() -> None:
    payload = _fixture_payload()
    loaded = _parse_fixture_bytes(_fixture_bytes(payload))

    assert tuple(case.case_id for case in loaded.cases) == EXPECTED_CASE_IDS
