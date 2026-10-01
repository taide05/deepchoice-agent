"""Source-addressed analysis: deterministic provenance, never semantic proof."""
from copy import deepcopy
import json
from unittest.mock import AsyncMock

import pytest

from deepchoice.agents import conclusion_synthesizer as synth
from deepchoice.formats.decision import render_decision_details
from deepchoice.security.html import render_safe_report_html
from deepchoice.utils.decision_analysis import (
    bind_decision_analysis, calibrate_decision_analysis, inspect_synthesis_bindings,
)


FACTS = [
    {"id": "F1", "evidence_id": 1, "saved_text": "Writers take turns. This does not establish workload latency.",
     "source_title": "Writer mechanism", "status": "verified"},
    {"id": "F2", "evidence_id": 2, "saved_text": "The index supports text search.",
     "source_title": "Search mechanism", "status": "verified"},
    {"id": "F3", "evidence_id": 3, "saved_text": "Uncoordinated file copying can produce an inconsistent backup. The backup interface copies a consistent database image.",
     "source_title": "Backup mechanism", "status": "verified"},
]
REQS = [{"id": "Q1", "kind": "frozen_sub_question", "requirement": "What supports backups?"}]
CHAINS = [{"sources": [{"title": f["source_title"], "snippet": f["saved_text"],
                       "url": f"https://example.org/source-{index}"} for index, f in enumerate(FACTS)]}]


def proposal():
    return {"winner": "context_dependent", "source_facts": deepcopy(FACTS), "decision_analysis": [{
        "kind": "answer", "option": "", "requirement_ids": ["Q1"],
        "fact_ids": ["F1", "F2"],  # A stale coarse list cannot override explicit source addresses.
        "basis": [{"fact_id": "F3", "sentence_ids": [1, 2]}],
        "reasoning": "A consistent backup mechanism is available; validate its integration before use.",
        "assumptions": ["The application can use that interface."],
        "change_condition": "Reconsider if integration or restore validation fails.",
        "review_status": "verified"}]}


def test_explicit_basis_rebuilds_refs_and_prose_then_renders_beside_judgment():
    before = proposal()
    bound = bind_decision_analysis(before, REQS, [], require_basis=True)
    item = bound["decision_analysis"][0]
    assert before == proposal()
    assert item["fact_ids"] == ["F3"]
    assert item["basis"][0]["source_sentences"] == [
        "Uncoordinated file copying can produce an inconsistent backup.",
        "The backup interface copies a consistent database image."]
    assert item["review_status"] == "not_checked"
    assert "FORGED_QUOTE" not in json.dumps(bound)
    rec = calibrate_decision_analysis(bound)
    report = "\n".join(render_decision_details(rec, "en"))
    assert report.index("Source sentences") < report.index("The backup interface") < report.index("Model judgment")
    assert "Backup mechanism" in report and "Writer mechanism" not in report
    assert rec["winner"] == "context_dependent"
    assert item["review_status"] == "human_review_required"


@pytest.mark.parametrize("indexes", [[0], [-1], [3], [True], [1.0], ["1"], [1, 1], [], [1, 2, 1, 2]])
def test_invalid_sentence_addresses_reject_entire_analysis(indexes):
    rec = proposal()
    rec["decision_analysis"][0]["basis"][0]["sentence_ids"] = indexes
    stats = {}
    bound = bind_decision_analysis(rec, REQS, [], diagnostics=stats, require_basis=True)
    assert bound["decision_analysis"] == []
    assert stats["rejected"] == {"basis_invalid_sentences": 1}
    assert "backup" not in json.dumps(stats).lower()


def test_legacy_read_does_not_bypass_current_synthesis_basis_requirement():
    rec = proposal()
    rec["decision_analysis"][0].pop("basis")
    assert bind_decision_analysis(rec, REQS, [])["decision_analysis"]
    bound, stats = inspect_synthesis_bindings(rec, CHAINS, REQS, [])
    assert bound["decision_analysis"] == []
    assert stats["errors"] == {"analysis_basis_missing_or_invalid": 1}


def test_prompt_sentence_addresses_match_runtime_and_keep_qualifiers():
    text, _ = synth._summarize_chains(CHAINS)
    assert "s1: Writers take turns." in text
    assert "s2: This does not establish workload latency." in text
    assert "s2: The backup interface copies a consistent database image." in text



def test_calibration_keeps_source_uncertainty_and_renderer_rejects_forged_quote():
    bound = bind_decision_analysis(proposal(), REQS, [], require_basis=True)
    bound["source_facts"][2]["status"] = "unknown"
    assert calibrate_decision_analysis(bound)["decision_analysis"] == []
    bound = calibrate_decision_analysis(bind_decision_analysis(proposal(), REQS, [], require_basis=True))
    bound["decision_analysis"][0]["basis"][0]["source_sentences"] = ["<img src=x onerror=alert(1)>"]
    rendered = "\n".join(render_decision_details(bound, "zh"))
    assert "<img" not in render_safe_report_html(rendered)
    assert "A consistent backup mechanism is available" not in rendered
    bound["decision_analysis"][0]["basis"][0]["sentence_ids"] = [99]
    assert "A consistent backup mechanism is available" not in "\n".join(render_decision_details(bound, "en"))


async def test_missing_basis_gets_only_existing_bounded_correction(monkeypatch):
    missing = proposal()
    missing["decision_analysis"][0].pop("basis")
    model = AsyncMock(return_value=missing)
    monkeypatch.setattr(synth, "call_model", model)
    task = {"query": "What supports backups?", "candidate_techs": [],
            "sub_questions": ["What supports backups?"]}
    result = await synth.ConclusionSynthesizerAgent().run({"task": task, "evidence_chains": CHAINS})
    assert model.await_count == 2
    assert result["final_recommendation"]["decision_analysis"] == []
    signal = result["quality_signals"][0]["structure_correction"]
    assert signal["outcome"] == "invalid" and signal["attempted"] == 1
    assert "consistent backup" not in json.dumps(signal)


@pytest.mark.parametrize('saved_quote,visible', [
    (['.'], False),  # v13 s2 was a single dot; v14 s2 is the following sentence.
    (['The backup interface copies a consistent database image.'], True),
    (['FORGED_QUOTE'], False),
])
def test_historical_sentence_addresses_cannot_silently_change_quote(saved_quote, visible):
    rec = proposal()
    rec['source_facts'][2]['saved_text'] = (
        'Uncoordinated copying is unsafe... The backup interface copies a consistent database image.')
    item = rec['decision_analysis'][0]
    item.update(fact_ids=['F3'], review_status='human_review_required')
    item['basis'] = [{'fact_id': 'F3', 'sentence_ids': [2], 'source_sentences': saved_quote}]
    original = deepcopy(rec)
    rendered = '\n'.join(render_decision_details(rec, 'en'))
    assert ('A consistent backup mechanism is available' in rendered) is visible
    assert rec == original
    stats = {}
    bound = bind_decision_analysis(rec, REQS, [], require_basis=True, diagnostics=stats)
    assert bool(bound['decision_analysis']) is visible
    if not visible:
        assert stats['rejected'] == {'basis_source_sentences_mismatch': 1}
