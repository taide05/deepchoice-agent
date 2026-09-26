from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from scripts import o1_pr2b_child as child
from scripts import o1_pr2b_control as control
from scripts import o1_pr2b_preflight as preflight
from scripts import o1_pr2b_prepare as prepare
from scripts import o1_pr2b_review_pack as review
from scripts import o1_pr2b_round_gate as gate


def _write_collection(root: Path, profile: str) -> Path:
    output = root / "collections" / profile
    output.mkdir(parents=True)
    experiment = f"exp-{profile}"
    metadata = {
        "schema_version": 1,
        "experiment_id": experiment,
        "dataset_hash": review.DATASET_HASH,
        "git_commit": review.EXPECTED_COMMIT,
        "case_denominator": 12,
        "admitted_run_denominator": 12,
        "environment_hash": "e" * 64,
        "core_asset_registry_id": gate.EXPECTED_ASSET,
    }
    (output / "experiment.json").write_text(
        json.dumps(metadata), encoding="utf-8")
    records = []
    for number in range(1, 13):
        case_id = f"P{number:02d}"
        split = "development" if number <= 8 else "holdout"
        report_path = Path(split) / "reports" / f"{case_id}.md"
        snapshot_path = Path(split) / "snapshots" / f"{case_id}.json"
        (output / report_path).parent.mkdir(parents=True, exist_ok=True)
        (output / snapshot_path).parent.mkdir(parents=True, exist_ok=True)
        (output / report_path).write_text(
            f"synthetic report {profile} {case_id}\n", encoding="utf-8")
        (output / snapshot_path).write_text("{}", encoding="utf-8")
        records.append({
            "case_id": case_id,
            "status": "completed",
            "report_path": report_path.as_posix(),
            "snapshot_path": snapshot_path.as_posix(),
            "run_id": f"{profile}-run-{number}",
            "manifest_id": review.EXPECTED_MANIFEST_BY_CASE[case_id],
            "experiment_id": experiment,
            "profile": "serial" if profile.startswith("serial") else "concurrent",
            "requested_concurrency": 1 if profile.startswith("serial") else 12,
            "dataset_hash": review.DATASET_HASH,
            "repetition": int(profile[-1]),
        })
    (output / "runs.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    return output


def _complete_review(template: dict, *, finding: bool, independent: bool) -> dict:
    value = dict(template)
    value["review_status"] = "complete"
    value["reviewer_qualification"] = "synthetic-offline-check"
    value["ledger_complete"] = True
    value["claim_occurrences"] = [{
        "occurrence_id": "occ-1",
        "line": 1,
        "atom": "synthetic atom",
        "support": "supported",
        "quality": "eligible",
        "source_refs": ["ref-1"],
        "notes": "synthetic evidence",
    }]
    for field in ("must_answer", "conflict_points"):
        value[field] = [
            {**entry, "score": 2, "notes": "synthetic scoring"}
            for entry in value[field]
        ]
    value["major_errors"] = (
        [{"id": "me-1", "evidence": "synthetic finding"}]
        if finding and not independent else []
    )
    value["disputed_refs"] = []
    value["claimed_improvements"] = []
    if independent:
        value["independent_coverage"] = (
            [{
                "kind": "major_errors",
                "id": "me-1",
                "covered": True,
                "evidence": "independent check",
            }]
            if finding else []
        )
    return value


def _prepare_review(root: Path, repository: Path) -> tuple[Path, Path]:
    serial = _write_collection(root, "serial-r1")
    concurrent = _write_collection(root, "concurrent-r1")
    review_root = root / "review" / "round-1"
    package = review_root / "package"
    mapping = review_root / "mapping.json"
    review.generate(Namespace(
        serial=str(serial),
        concurrent=str(concurrent),
        dataset=str(repository / "benchmarks/product-baseline-v1.json"),
        output=str(package),
        mapping=str(mapping),
        seed=20260919,
    ))
    templates = review.read_json(package / "review-template.json")
    mains = [
        _complete_review(item, finding=index == 0, independent=False)
        for index, item in enumerate(templates)
    ]
    independents = [
        _complete_review(item, finding=index == 0, independent=True)
        for index, item in enumerate(templates)
    ]
    main_path = review_root / "main-review.json"
    independent_path = review_root / "independent-review.json"
    main_path.write_text(json.dumps(mains), encoding="utf-8")
    independent_path.write_text(json.dumps(independents), encoding="utf-8")
    lock = review_root / "review-lock.json"
    review.lock_reviews(Namespace(
        package=str(package),
        main=str(main_path),
        independent=str(independent_path),
        lock=str(lock),
    ))
    joined = review_root / "joined"
    review.join_reviews(Namespace(
        package=str(package),
        mapping=str(mapping),
        lock=str(lock),
        main=str(main_path),
        independent=str(independent_path),
        output=str(joined),
    ))
    return serial, concurrent


def _write_control_evidence(root: Path, profile: str, tool_hashes: dict) -> None:
    destination = root / profile / "control"
    destination.mkdir(parents=True)
    (destination / "profile-control-result.json").write_text(json.dumps({
        "execution_succeeded": True,
        "profile": profile,
        "observed_records": 12,
        "report_count": 12,
        "metrics_complete": True,
        "stop_final_observability_complete": True,
        "active_budget_metrics_complete": True,
        "process_cleanup_unresolved": False,
        "graceful_service_exit": True,
    }), encoding="utf-8")
    (destination / "controller-identity.json").write_text(json.dumps({
        "git_commit": control.EXPECTED_COMMIT,
        "dataset_hash": control.EXPECTED_DATASET,
        "controller_sha256": control.file_hash(
            Path(control.__file__).resolve()),
        "child_sha256": control.file_hash(
            Path(control.__file__).with_name("o1_pr2b_child.py")),
        "pr2_tool_hashes": tool_hashes,
    }), encoding="utf-8")


def test_pr2b_control_chain_is_complete_and_current():
    assert prepare.PR2B_CONTROL_CHAIN == (
        "o1_pr2b_preflight.py",
        "o1_pr2b_prepare.py",
        "o1_pr2b_child.py",
        "o1_pr2b_control.py",
        "o1_pr2b_review_pack.py",
        "o1_pr2b_round_gate.py",
    )


def test_pr2b_candidate_binding_is_consistent():
    expected = "d23c9480b9f368f8ec75ec44ee7e25c64146d4be"
    assert {
        preflight.EXPECTED_COMMIT,
        prepare.EXPECTED_COMMIT,
        control.EXPECTED_COMMIT,
        review.EXPECTED_COMMIT,
        gate.EXPECTED_COMMIT,
    } == {expected}


def test_pr2b_blind_review_and_round_gate_reject_tampering(tmp_path):
    repository = Path(__file__).resolve().parents[1]
    tools = repository / "scripts"
    tool_hashes = {
        name: control.file_hash(tools / name)
        for name in prepare.PR2B_CONTROL_CHAIN
    }
    (tmp_path / "environment.json").write_text(json.dumps({
        "notes": {"pr2_tool_hashes": tool_hashes}
    }), encoding="utf-8")
    serial, _ = _prepare_review(tmp_path, repository)
    for profile in ("serial-r1", "concurrent-r1"):
        _write_control_evidence(tmp_path, profile, tool_hashes)

    result = gate.main(tmp_path, repository, 1)
    assert result["passed"] is True
    assert result["completed_report_count"] == 24
    assert result["independent_review_complete"] is True

    (tmp_path / "round-1-gate.json").unlink()
    (tmp_path / "review/round-1/comparison.json").unlink()
    report = serial / "development/reports/P01.md"
    report.write_text("tampered report\n", encoding="utf-8")
    with pytest.raises(ValueError, match="private mapping no longer matches"):
        gate.main(tmp_path, repository, 1)


def _write_telemetry(path: Path, *events: dict) -> None:
    path.write_text(
        "".join(json.dumps({
            "schema_version": 1,
            **event,
        }) + "\n" for event in events),
        encoding="utf-8",
    )


def test_pr2b_safe_fetch_context_marks_source_aware_dynamic_requests():
    get_request = httpx.Request("GET", "https://example.com/public-citation")
    head_request = httpx.Request("HEAD", "https://docs.example.com/")
    assert child._observed_operation(get_request, "api.deepseek.com") == "other"

    token = child._SAFE_FETCH_SOURCE.set("safe_fetch_public")
    try:
        assert (
            child._observed_operation(get_request, "api.deepseek.com")
            == "safe_fetch_public"
        )
        assert (
            child._observed_operation(head_request, "api.deepseek.com")
            == "safe_fetch_public"
        )
    finally:
        child._SAFE_FETCH_SOURCE.reset(token)

    token = child._SAFE_FETCH_SOURCE.set("safe_fetch_official")
    try:
        assert (
            child._observed_operation(get_request, "api.deepseek.com")
            == "safe_fetch_official"
        )
        assert (
            child._observed_operation(head_request, "api.deepseek.com")
            == "safe_fetch_official"
        )
    finally:
        child._SAFE_FETCH_SOURCE.reset(token)

    citation_token = child._SAFE_FETCH_SOURCE.set(
        "citation_safe_fetch_official"
    )
    try:
        assert (
            child._observed_operation(get_request, "api.deepseek.com")
            == "citation_safe_fetch_official"
        )
    finally:
        child._SAFE_FETCH_SOURCE.reset(citation_token)

    assert child._safe_fetch_operation("official") == "safe_fetch_official"
    citation_token = child._CITATION_FETCH.set(True)
    try:
        assert (
            child._safe_fetch_operation("official")
            == "citation_safe_fetch_official"
        )
        assert child._safe_fetch_operation("github") == "safe_fetch_public"
    finally:
        child._CITATION_FETCH.reset(citation_token)

    assert child._observed_source("safe_fetch_official") == "official"
    assert child._observed_source("citation_safe_fetch_official") == "citation"
    assert child._observed_source("safe_fetch_public") == "safe_fetch"
    assert child._observed_source("tavily_business") == "tavily"
    forward_endpoint = child._endpoint_identity("https://forward.example.com/v1/relay")
    assert forward_endpoint is not None
    forward_request = httpx.Request(
        "POST", "https://forward.example.com/v1/relay"
    )
    assert child._observed_operation(
        forward_request, "api.deepseek.com", forward_endpoint
    ) == "self_forward"
    assert child._observed_operation(
        httpx.Request("GET", "https://forward.example.com/v1/relay"),
        "api.deepseek.com", forward_endpoint,
    ) == "other"
    assert child._observed_operation(
        httpx.Request("POST", "https://forward.example.com/v1/other"),
        "api.deepseek.com", forward_endpoint,
    ) == "other"
    for value in (
        "http://forward.example.com/v1/relay",
        "https://other.example.com/v1/relay",
        "https://forward.example.com:444/v1/relay",
        "https://forward.example.com/v1/relay?mode=other",
        "https://user@forward.example.com/v1/relay",
    ):
        assert child._observed_operation(
            httpx.Request("POST", value), "api.deepseek.com", forward_endpoint,
        ) == "other"
    assert child._endpoint_identity(
        "https://user@forward.example.com/v1/relay"
    ) is None
    assert child._observed_source("self_forward") == "forward"
    assert child._observed_source("github") == "github"


def test_pr2b_child_exposes_only_known_safe_fetch_failure_values():
    known = RuntimeError("redacted")
    known.failure = SimpleNamespace(value="route_unsupported")
    assert child._safe_fetch_failure(known) == "route_unsupported"

    unknown = RuntimeError("redacted")
    unknown.failure = SimpleNamespace(value="unexpected")
    assert child._safe_fetch_failure(unknown) is None
    assert child._safe_fetch_failure(RuntimeError("redacted")) is None


@pytest.mark.parametrize(
    "error_type", (httpx.StreamClosed, httpx.StreamConsumed, httpx.ResponseNotRead)
)
def test_pr2b_child_normalizes_only_dispatched_response_stream_failures(error_type):
    from deepchoice.security.urls import SafeFetchFailure, UnsafeUrlError

    original = error_type()
    assert child._bounded_stream_failure(original, "before_http") is original
    for phase in ("http_dispatch", "response_received"):
        normalized = child._bounded_stream_failure(original, phase)
        assert isinstance(normalized, UnsafeUrlError)
        assert normalized.failure is SafeFetchFailure.RESPONSE_REJECTED
        assert normalized.__cause__ is None


@pytest.mark.parametrize(
    "error", (httpx.StreamClosed(), httpx.StreamConsumed(), httpx.ResponseNotRead())
)
def test_pr2b_child_preserves_bounded_stream_error_types(error):
    assert child._error_type(error) == type(error).__name__
    assert child._error_type(httpx.ProxyError("redacted")) == "TransportError"


def test_pr2b_self_forward_response_requires_exact_frozen_context(tmp_path):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {"event": "external_http_response", "operation": "self_forward",
         "source": "forward", "method": "POST", "status_code": 200},
    )
    assert control.telemetry_state(telemetry)["anomaly"] is False

    for change in (
        {"source": "other"},
        {"method": "GET"},
        {"status_code": 500},
    ):
        event = {"event": "external_http_response", "operation": "self_forward",
                 "source": "forward", "method": "POST", "status_code": 200}
        event.update(change)
        _write_telemetry(telemetry, {"event": "telemetry_ready"}, event)
        state = control.telemetry_state(telemetry)
        assert state["anomaly"] is True
        assert state["reason"] == "self_forward_failed"


def test_pr2b_safe_fetch_accepts_exact_transport_unknown_pair(tmp_path):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {"event": "external_http_failure", "operation": "safe_fetch_official",
         "source": "official", "method": "GET", "error_type": "TransportError",
         "failure": None},
        {"event": "safe_fetch_failure", "status": "failure",
         "error_type": "TransportError", "failure": None},
    )
    assert control.telemetry_state(telemetry)["anomaly"] is False


def test_pr2b_citation_safe_fetch_accepts_exact_transport_unknown_pair(tmp_path):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {"event": "external_http_failure",
         "operation": "citation_safe_fetch_official",
         "source": "citation", "method": "GET",
         "error_type": "TransportError", "failure": None},
        {"event": "safe_fetch_failure", "status": "failure",
         "operation": "citation_safe_fetch_official", "source": "citation",
         "error_type": "TransportError", "failure": None},
    )
    assert control.telemetry_state(telemetry)["anomaly"] is False


@pytest.mark.parametrize(
    "error_type", ("StreamClosed", "StreamConsumed", "ResponseNotRead")
)
def test_pr2b_citation_safe_fetch_accepts_dispatched_response_stream_failure(
    tmp_path, error_type,
):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {"event": "external_http_failure",
         "operation": "citation_safe_fetch_official", "source": "citation",
         "method": "GET", "error_type": error_type, "failure": None,
         "safe_fetch_phase": "http_dispatch"},
        {"event": "safe_fetch_failure", "status": "failure",
         "operation": "citation_safe_fetch_official", "source": "citation",
         "error_type": "UnsafeUrlError", "failure": "response_rejected",
         "safe_fetch_phase": "http_dispatch"},
    )
    assert control.telemetry_state(telemetry)["anomaly"] is False


@pytest.mark.parametrize(
    "operation,source,phase",
    [
        ("safe_fetch_official", "official", "http_dispatch"),
        ("citation_safe_fetch_official", "citation", "before_http"),
    ],
)
def test_pr2b_response_stream_failure_remains_narrowly_scoped(
    tmp_path, operation, source, phase,
):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {"event": "external_http_failure", "operation": operation,
         "source": source, "method": "GET", "error_type": "StreamClosed",
         "failure": None, "safe_fetch_phase": phase},
    )
    assert control.telemetry_state(telemetry)["anomaly"] is True


@pytest.mark.parametrize(
    "failure",
    [
        "safety_rejected",
        "route_unavailable",
        "route_unsupported",
        "dns_uncertain",
        "timeout",
        "response_rejected",
    ],
)
def test_pr2b_public_safe_fetch_accepts_bounded_policy_failures(tmp_path, failure):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {
            "event": "external_http_failure",
            "operation": "safe_fetch_public",
            "source": "safe_fetch",
            "method": "GET",
            "error_type": "UnsafeUrlError",
            "failure": failure,
        },
    )

    assert control.telemetry_state(telemetry)["anomaly"] is False


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_pr2b_official_safe_fetch_accepts_bounded_policy_failures(
        tmp_path, method):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {
            "event": "external_http_failure",
            "operation": "safe_fetch_official",
            "source": "official",
            "method": method,
            "error_type": "UnsafeUrlError",
            "failure": "route_unsupported",
        },
    )

    assert control.telemetry_state(telemetry)["anomaly"] is False


@pytest.mark.parametrize(
    "event",
    [
        {
            "source": "safe_fetch",
            "method": "GET",
            "error_type": "UnsafeUrlError",
        },
        {
            "source": "safe_fetch",
            "method": "GET",
            "error_type": "UnsafeUrlError",
            "failure": "unknown_failure",
        },
        {
            "source": "safe_fetch",
            "method": "GET",
            "error_type": "ConnectError",
            "failure": "route_unsupported",
        },
        {
            "source": "other",
            "method": "GET",
            "error_type": "UnsafeUrlError",
            "failure": "route_unsupported",
        },
        {
            "source": "safe_fetch",
            "method": "HEAD",
            "error_type": "UnsafeUrlError",
            "failure": "route_unsupported",
        },
    ],
)
def test_pr2b_public_safe_fetch_failure_requires_exact_bounded_context(
        tmp_path, event):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {
            "event": "external_http_failure",
            "operation": "safe_fetch_public",
            **event,
        },
    )

    state = control.telemetry_state(telemetry)
    assert state["anomaly"] is True
    assert state["reason"] == "safe_fetch_public_failed"


@pytest.mark.parametrize("status_code", [200, 302, 403, 404, 429])
def test_pr2b_public_safe_fetch_get_accepts_bounded_2xx_through_4xx(
        tmp_path, status_code):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {
            "event": "external_http_response",
            "operation": "safe_fetch_public",
            "source": "safe_fetch",
            "method": "GET",
            "status_code": status_code,
        },
    )

    assert control.telemetry_state(telemetry)["anomaly"] is False


@pytest.mark.parametrize(
    ("method", "status_code"),
    [
        ("HEAD", 200),
        ("HEAD", 302),
        ("HEAD", 405),
        ("HEAD", 429),
        ("HEAD", 501),
        ("GET", 200),
        ("GET", 206),
        ("GET", 404),
    ],
)
def test_pr2b_official_safe_fetch_accepts_product_contract(
        tmp_path, method, status_code):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {
            "event": "external_http_response",
            "operation": "safe_fetch_official",
            "source": "official",
            "method": method,
            "status_code": status_code,
        },
    )

    assert control.telemetry_state(telemetry)["anomaly"] is False


@pytest.mark.parametrize(
    "event",
    [
        {
            "operation": "safe_fetch_public",
            "source": "safe_fetch",
            "method": "GET",
            "status_code": 500,
        },
        {
            "operation": "safe_fetch_public",
            "source": "safe_fetch",
            "method": "HEAD",
            "status_code": 403,
        },
        {
            "operation": "safe_fetch_public",
            "source": "other",
            "method": "GET",
            "status_code": 403,
        },
    ],
)
def test_pr2b_safe_fetch_5xx_and_invalid_context_fail_closed(tmp_path, event):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {"event": "external_http_response", **event},
    )

    state = control.telemetry_state(telemetry)
    assert state["anomaly"] is True
    assert state["reason"] == "safe_fetch_public_failed"


@pytest.mark.parametrize(
    "event",
    [
        {
            "source": "official",
            "method": "HEAD",
            "error_type": "ConnectError",
            "failure": "route_unsupported",
        },
        {
            "source": "official",
            "method": "POST",
            "error_type": "UnsafeUrlError",
            "failure": "route_unsupported",
        },
        {
            "source": "safe_fetch",
            "method": "HEAD",
            "error_type": "UnsafeUrlError",
            "failure": "route_unsupported",
        },
    ],
)
def test_pr2b_official_safe_fetch_failure_context_remains_fail_closed(
        tmp_path, event):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {
            "event": "external_http_failure",
            "operation": "safe_fetch_official",
            **event,
        },
    )

    state = control.telemetry_state(telemetry)
    assert state["anomaly"] is True
    assert state["reason"] == "safe_fetch_official_failed"


@pytest.mark.parametrize(
    "event",
    [
        {"source": "official", "method": "HEAD", "status_code": 500},
        {"source": "official", "method": "GET", "status_code": 501},
        {"source": "official", "method": "POST", "status_code": 200},
        {"source": "safe_fetch", "method": "HEAD", "status_code": 200},
    ],
)
def test_pr2b_official_safe_fetch_response_context_remains_fail_closed(
        tmp_path, event):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {
            "event": "external_http_response",
            "operation": "safe_fetch_official",
            **event,
        },
    )

    state = control.telemetry_state(telemetry)
    assert state["anomaly"] is True
    assert state["reason"] == "safe_fetch_official_failed"


@pytest.mark.parametrize(
    ("operation", "source", "method"),
    [
        ("safe_fetch_public", "safe_fetch", "GET"),
        ("safe_fetch_official", "official", "GET"),
        ("safe_fetch_official", "official", "HEAD"),
    ],
)
def test_pr2b_safe_fetch_transport_cancel_pairs_with_typed_timeout(
        tmp_path, operation, source, method):
    telemetry = tmp_path / "telemetry.jsonl"
    observed_at = "2026-09-21T11:13:25.881335+00:00"
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {
            "event": "external_http_failure",
            "timestamp": observed_at,
            "run_id": "run-1",
            "operation": operation,
            "source": source,
            "method": method,
            "error_type": "CancelledError",
        },
        {
            "event": "safe_fetch_failure",
            "timestamp": "2026-09-21T11:13:25.881840+00:00",
            "run_id": "run-1",
            "status": "failure",
            "error_type": "UnsafeUrlError",
            "failure": "timeout",
        },
    )

    assert control.telemetry_state(telemetry)["anomaly"] is False


def test_pr2b_safe_fetch_cancel_rejects_late_typed_timeout(tmp_path):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {
            "event": "external_http_failure",
            "timestamp": "2026-09-21T11:13:25+00:00",
            "run_id": "run-1",
            "operation": "safe_fetch_official",
            "source": "official",
            "method": "GET",
            "error_type": "CancelledError",
        },
        {
            "event": "safe_fetch_failure",
            "timestamp": "2026-09-21T11:13:26+00:00",
            "run_id": "run-1",
            "status": "failure",
            "error_type": "UnsafeUrlError",
            "failure": "timeout",
        },
    )

    state = control.telemetry_state(telemetry)
    assert state["anomaly"] is True
    assert state["reason"] == "external_http_cancelled"


def test_pr2b_safe_fetch_cancel_waits_for_immediate_typed_outcome(tmp_path):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {
            "event": "external_http_failure",
            "timestamp": control.stamp(),
            "run_id": "run-1",
            "operation": "safe_fetch_official",
            "source": "official",
            "method": "GET",
            "error_type": "CancelledError",
        },
    )

    assert control.telemetry_state(telemetry)["anomaly"] is False


def test_pr2b_final_state_rejects_recent_unpaired_safe_fetch_cancel(tmp_path):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {
            "event": "external_http_failure",
            "timestamp": control.stamp(),
            "run_id": "run-1",
            "operation": "safe_fetch_official",
            "source": "official",
            "method": "GET",
            "error_type": "CancelledError",
        },
        {"event": "service_stopped"},
        {"event": "asyncio_runner_returned"},
    )

    state = control.telemetry_state(
        telemetry, require_stopped=True, require_runner_returned=True
    )
    assert state["anomaly"] is True
    assert state["reason"] == "external_http_cancelled"


@pytest.mark.parametrize(
    "typed_event",
    [
        {
            "run_id": "run-2",
            "status": "failure",
            "error_type": "UnsafeUrlError",
            "failure": "timeout",
        },
        {
            "run_id": "run-1",
            "status": "failure",
            "error_type": "CancelledError",
            "failure": None,
        },
        {
            "run_id": "run-1",
            "status": "failure",
            "error_type": "UnsafeUrlError",
            "failure": "unknown_failure",
        },
    ],
)
def test_pr2b_unpaired_safe_fetch_cancel_remains_fail_closed(
        tmp_path, typed_event):
    telemetry = tmp_path / "telemetry.jsonl"
    timestamp = control.stamp()
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {
            "event": "external_http_failure",
            "timestamp": timestamp,
            "run_id": "run-1",
            "operation": "safe_fetch_official",
            "source": "official",
            "method": "GET",
            "error_type": "CancelledError",
        },
        {"event": "safe_fetch_failure", "timestamp": timestamp, **typed_event},
        {"event": "service_stopped"},
        {"event": "asyncio_runner_returned"},
    )

    state = control.telemetry_state(
        telemetry, require_stopped=True, require_runner_returned=True
    )
    assert state["anomaly"] is True
    assert state["reason"] == "external_http_cancelled"


def test_pr2b_health_loss_precedes_secondary_cancelled_http_failures(tmp_path):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {
            "event": "external_http_failure",
            "operation": "github",
            "source": "github",
            "method": "GET",
            "error_type": "CancelledError",
        },
    )

    assert control.polling_stop_reason(
        health_safe=False, telemetry_path=telemetry
    ) == "PR2_RESOURCE_OR_LEASE_STOP"
    assert control.telemetry_state(telemetry)["reason"] == "external_http_cancelled"
    assert control.polling_stop_reason(
        health_safe=True, telemetry_path=telemetry
    ) == "PR2_EXTERNAL_HTTP_STOP"

    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {
            "event": "external_http_failure",
            "operation": "github",
            "source": "github",
            "method": "GET",
            "error_type": "CancelledError",
        },
        {
            "event": "external_http_response",
            "operation": "tavily_business",
            "source": "tavily",
            "method": "POST",
            "status_code": 500,
        },
    )
    assert control.polling_stop_reason(
        health_safe=False, telemetry_path=telemetry
    ) == "PR2_EXTERNAL_HTTP_STOP"


@pytest.mark.parametrize("error_type", ["RemoteProtocolError", "ReadError"])
def test_pr2b_github_response_interruption_waits_for_bounded_retry(
        tmp_path, error_type):
    telemetry = tmp_path / "telemetry.jsonl"
    interrupted = {
        "event": "external_http_failure",
        "run_id": "run-1",
        "operation": "github",
        "source": "github",
        "method": "GET",
        "error_type": error_type,
    }
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        interrupted,
        interrupted,
    )

    assert control.telemetry_state(telemetry)["anomaly"] is False

    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        interrupted,
        interrupted,
        {
            "event": "external_http_response",
            "run_id": "run-1",
            "operation": "github",
            "source": "github",
            "method": "GET",
            "status_code": 200,
        },
        interrupted,
        interrupted,
    )
    assert control.telemetry_state(telemetry)["anomaly"] is False


def test_pr2b_github_response_interruption_exhaustion_fails_closed(tmp_path):
    telemetry = tmp_path / "telemetry.jsonl"
    interrupted = {
        "event": "external_http_failure",
        "run_id": "run-1",
        "operation": "github",
        "source": "github",
        "method": "GET",
        "error_type": "RemoteProtocolError",
    }
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        interrupted,
        interrupted,
        interrupted,
    )

    state = control.telemetry_state(telemetry)
    assert state["anomaly"] is True
    assert state["reason"] == "external_http_failure"


@pytest.mark.parametrize(
    "event",
    [
        {"run_id": "", "source": "github", "method": "GET"},
        {"run_id": "run-1", "source": "github", "method": "POST"},
        {"run_id": "run-1", "source": "arxiv", "method": "GET"},
        {"run_id": "run-1", "source": "github", "method": "GET",
         "error_type": "ConnectError"},
    ],
)
def test_pr2b_nonqualified_github_failure_remains_fail_closed(tmp_path, event):
    telemetry = tmp_path / "telemetry.jsonl"
    payload = {
        "event": "external_http_failure",
        "operation": "github",
        "source": "github",
        "method": "GET",
        "error_type": "RemoteProtocolError",
        **event,
    }
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        payload,
    )

    state = control.telemetry_state(telemetry)
    assert state["anomaly"] is True
    assert state["reason"] == "external_http_failure"


@pytest.mark.asyncio
async def test_pr2b_cleanup_waits_beyond_old_30_second_poll_count(
        tmp_path, monkeypatch):
    state = {"get_count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"task": {"status": "cancelling"}})
        state["get_count"] += 1
        status = "cancelled" if state["get_count"] > 36 else "cancelling"
        if state["get_count"] == 1:
            status = "running"
        return httpx.Response(200, json={"task": {"status": status}})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://local.test",
    )
    monkeypatch.setattr(control.httpx, "AsyncClient", lambda **_kwargs: client)
    monkeypatch.setattr(
        control.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(
            available=control.STOP_MINIMUM_AVAILABLE_BYTES + 1
        ),
    )

    result = await control.settle(
        "http://unused",
        ["task-1"],
        tmp_path / "journal.jsonl",
        True,
        timeout_seconds=5,
        poll_interval_seconds=0.0001,
    )

    assert state["get_count"] > 30
    assert result["attempted"] == 1
    assert result["settled"] == 1
    assert result["unresolved"] == []
    assert result["resource_stop"] is False


@pytest.mark.asyncio
async def test_pr2b_cleanup_keeps_memory_stop_line(tmp_path, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        status = "cancelling" if request.method == "POST" else "running"
        return httpx.Response(200, json={"task": {"status": status}})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://local.test",
    )
    monkeypatch.setattr(control.httpx, "AsyncClient", lambda **_kwargs: client)
    monkeypatch.setattr(
        control.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(
            available=control.STOP_MINIMUM_AVAILABLE_BYTES - 1
        ),
    )

    result = await control.settle(
        "http://unused",
        ["task-1"],
        tmp_path / "journal.jsonl",
        True,
        timeout_seconds=5,
        poll_interval_seconds=0.0001,
    )

    assert result["settled"] == 0
    assert result["unresolved"] == ["task-1"]
    assert result["resource_stop"] is True


@pytest.mark.asyncio
async def test_pr2b_cleanup_cancels_all_tasks_before_polling(tmp_path, monkeypatch):
    sequence = []
    initial_gets = set()

    def handler(request: httpx.Request) -> httpx.Response:
        task_id = request.url.path.split("/")[-1]
        if task_id == "cancel":
            task_id = request.url.path.split("/")[-2]
        sequence.append((request.method, task_id))
        if request.method == "POST":
            return httpx.Response(200, json={"task": {"status": "cancelling"}})
        if task_id not in initial_gets:
            initial_gets.add(task_id)
            return httpx.Response(200, json={"task": {"status": "running"}})
        return httpx.Response(200, json={"task": {"status": "cancelled"}})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://local.test",
    )
    monkeypatch.setattr(control.httpx, "AsyncClient", lambda **_kwargs: client)
    monkeypatch.setattr(
        control.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(
            available=control.STOP_MINIMUM_AVAILABLE_BYTES + 1
        ),
    )

    result = await control.settle(
        "http://unused",
        ["task-1", "task-2"],
        tmp_path / "journal.jsonl",
        True,
        timeout_seconds=5,
        poll_interval_seconds=0.0001,
    )

    assert sequence[:4] == [
        ("GET", "task-1"),
        ("POST", "task-1"),
        ("GET", "task-2"),
        ("POST", "task-2"),
    ]
    assert result["attempted"] == 2
    assert result["settled"] == 2
    assert result["unresolved"] == []


def _six_source_snapshot(*, failed_source: str | None = None,
                         partial_failures: list[str] | None = None) -> dict:
    return {
        "partial_failures": partial_failures or [],
        "search_results": [
            {
                "source": source,
                "status": "failed" if source == failed_source else "success",
            }
            for source in sorted(control._EXPECTED_SOURCES)
        ],
    }


def test_pr2b_source_health_allows_non_source_limited_report_marker():
    snapshot = _six_source_snapshot(
        partial_failures=["evidence_insufficient_user_limited"],
    )

    assert control.source_anomaly(snapshot) is False


@pytest.mark.parametrize(
    "snapshot",
    [
        _six_source_snapshot(failed_source="github"),
        {"search_results": []},
        {
            "search_results": [
                {"source": "tavily", "status": "success"},
            ] * 6,
        },
        None,
    ],
)
def test_pr2b_source_health_requires_six_distinct_success_envelopes(snapshot):
    assert control.source_anomaly(snapshot) is True
