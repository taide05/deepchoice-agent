import pytest

from deepchoice.contracts.errors import DeepChoiceError
from deepchoice.contracts.manifest import RunManifest, _expected_manifest_id, build_run_manifest, ensure_run_manifest_compatible
from deepchoice.formats.what_why_how import render


def test_moderate_only_report_retains_requested_candidates_and_visible_gaps():
    report = render({
        "task": {"query": "选 SQLite 还是 PostgreSQL？", "candidate_techs": ["SQLite", "PostgreSQL"]},
        "evidence_chains": [{"conclusion": "Limited evidence", "evidence_strength": "moderate", "sources": []}],
        "knowledge_gaps": ["备份方案待核实"],
        "final_recommendation": {"unresolved_questions": ["备份方案待核实", "写入锁等待需观测"]},
    })
    what = report.split("## What:", 1)[1].split("## Why:", 1)[0]
    assert "SQLite, PostgreSQL" in what and "尚无强证据链" in what
    assert "Limited evidence" not in what and "[Source:" not in what
    assert report.count("- 备份方案待核实") == 1
    assert "- 写入锁等待需观测" in report


def test_legacy_report_without_explicit_candidates_uses_existing_option_labels():
    report = render({"task": {"query": "Select a database"},
                     "final_recommendation": {"ranked_options": [{"name": "SQLite", "rank": 1}]}})
    what = report.split("## What:", 1)[1].split("## Why:", 1)[0]
    assert "Candidates:** SQLite" in what and "No strong evidence" in what


@pytest.mark.parametrize("asset", ["scoring", "template", "synthesis", "scan"])
def test_previous_candidate_assets_remain_readable_but_cannot_resume(asset):
    task = {"report_format": "what_why_how"}
    manifest = build_run_manifest(task)
    if asset == "scoring":
        old = manifest.model_copy(update={"scoring_policy_version": "source-score-v2"})
    elif asset == "template":
        old = manifest.model_copy(update={"report": manifest.report.model_copy(update={"template_version": "what-why-how-v2"})})
    else:
        prompt_id = {"synthesis": "conclusion_synthesizer.synthesis_prompt",
                     "scan": "conflict_detector.contradiction_scan_system",
                     "arbitration": "conflict_detector.arbitration_system"}[asset]
        prompts = tuple(prompt.model_copy(update={"version": "v2" if asset == "synthesis" else "v1"})
                        if prompt.prompt_id == prompt_id else prompt for prompt in manifest.prompts)
        old = manifest.model_copy(update={"prompts": prompts})
    old = old.model_copy(update={"manifest_id": _expected_manifest_id(old)})
    restored = RunManifest.model_validate_json(old.model_dump_json())
    assert restored.manifest_id == _expected_manifest_id(restored)
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, task)
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"
