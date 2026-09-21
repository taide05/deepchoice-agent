from __future__ import annotations

from copy import deepcopy
import json

import pytest

from benchmarks import product_optimization_s1 as s1


@pytest.fixture(autouse=True)
def frozen_repository(monkeypatch):
    """Exercise identity checks without requiring historical objects in shallow CI.

    The operational CLI still checks real Git. Unit tests model both historical
    arms so unrelated future product changes do not break this frozen fixture.
    """
    frozen = json.loads(s1.PROTOCOL_PATH.read_text(encoding="utf-8"))
    identities = frozen["identities"]
    refs = {item["anchor_commit"]: item for item in identities.values()}
    refs["HEAD"] = identities["candidate"]
    refs["814131f849f417fbcf4f00cfe071d95ccf2b3878"] = identities["baseline"]

    def git(*args):
        if args[0] == "status":
            return ""
        assert args[0] == "rev-parse"
        ref, path = args[1].split(":", 1)
        objects = [*refs[ref]["source_objects"],
                   *identities["controller"]["source_objects"]]
        return next(item["git_object"] for item in objects if item["path"] == path)

    monkeypatch.setattr(s1, "_git", git)


def _write_protocol(tmp_path, protocol):
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(protocol, ensure_ascii=False), encoding="utf-8")
    return path


def test_frozen_s1_protocol_is_complete_and_repository_bound():
    protocol, digest = s1.load_protocol()
    assert protocol["protocol_id"] == s1.PROTOCOL_ID
    assert len(digest) == 64
    assert len(protocol["design"]["schedule"]) == 12
    assert {cell["case_id"] for cell in protocol["design"]["schedule"]} == {
        "P01",
        "P04",
        "P08",
    }
    assert protocol["budgets"]["research_ledger"]["projected_used"] == 103
    assert protocol["review"]["holdout_reports_accessed"] is False


def test_schedule_is_deterministic_balanced_and_blinded():
    schedule = s1.build_schedule()
    assert schedule == s1.build_schedule(20260922)
    assert [cell["order"] for cell in schedule] == list(range(1, 13))
    assert len({cell["blind_label"] for cell in schedule}) == 12
    assert {
        (cell["case_id"], cell["arm"], cell["repetition"]) for cell in schedule
    } == {
        (case_id, arm, repetition)
        for case_id in ("P01", "P04", "P08")
        for arm in ("baseline", "candidate")
        for repetition in (1, 2)
    }


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value["dataset"].update(sha256="0" * 64), "dataset identity"),
        (
            lambda value: value["design"].update(formal_research_runs=11),
            "design",
        ),
        (lambda value: value["design"]["schedule"].reverse(), "schedule"),
        (
            lambda value: value["budgets"]["research_ledger"].update(hard_cap=135),
            "ledger",
        ),
        (
            lambda value: value["acceptance"]["targets"].update(
                candidate_major_errors=1
            ),
            "acceptance",
        ),
        (
            lambda value: value["stopping"].update(
                ordinary_citation_http_5xx="warning"
            ),
            "stop policy",
        ),
        (
            lambda value: value["review"].update(holdout_reports_accessed=True),
            "review",
        ),
        (
            lambda value: value["scope"]["excluded_claims"].pop(),
            "scope",
        ),
        (
            lambda value: value["environment"].update(cache_enabled=False),
            "environment",
        ),
        (
            lambda value: value["stopping"].update(
                preserve_all_admitted_denominators=False
            ),
            "stop policy",
        ),
    ],
)
def test_protocol_drift_fails_closed(tmp_path, mutate, message):
    protocol, _ = s1.load_protocol(verify_repository=False)
    candidate = deepcopy(protocol)
    mutate(candidate)
    with pytest.raises(ValueError, match=message):
        s1.load_protocol(
            _write_protocol(tmp_path, candidate), verify_repository=False
        )


def test_source_object_drift_fails_closed(tmp_path):
    protocol, _ = s1.load_protocol(verify_repository=False)
    candidate = deepcopy(protocol)
    candidate["identities"]["candidate"]["source_objects"][0][
        "git_object"
    ] = "0" * 40
    with pytest.raises(ValueError, match="source object drift"):
        s1.load_protocol(_write_protocol(tmp_path, candidate))


def test_execution_arm_check_rejects_candidate_checkout_as_baseline():
    with pytest.raises(ValueError, match="frozen baseline"):
        s1.load_protocol(execution_arm="baseline")


def test_known_post_controller_baseline_ref_passes_source_checks():
    protocol, _ = s1.load_protocol(
        execution_arm="baseline",
        execution_ref="814131f849f417fbcf4f00cfe071d95ccf2b3878",
    )
    assert (
        protocol["identities"]["baseline"]["anchor_commit"]
        == s1.BASELINE_COMMIT
    )


def test_cli_is_offline_and_reports_no_paid_execution(capsys):
    assert s1.main([]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "frozen"
    assert output["paid_execution_started"] is False
    assert output["formal_research_runs"] == 12
    assert output["execution_arm_checked"] == "candidate"
    assert output["execution_ref_checked"] == "HEAD"


def test_structure_only_cli_does_not_claim_repository_verification(capsys):
    assert s1.main(["--skip-repository-checks"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["execution_arm_checked"] is None
    assert output["execution_ref_checked"] is None
