"""Runtime views reduce model coordinates without relaxing source boundaries."""
from copy import deepcopy
import json

import pytest
from tests.staged_synthesis_helpers import run_staged

from deepchoice.utils import fact_selection as selection
from deepchoice.utils.call_diagnostics import output_shape_valid
from deepchoice.utils.conflict_scope import make_conflict_scope
from deepchoice.utils.evidence_choices import bind_evidence_choices


def chains(text="Alpha queues writes when writers can wait. Restart recovery is not guaranteed."):
    return [{"evidence_strength": "moderate", "sources": [{"title": "Alpha guide",
        "url": "https://alpha.example/docs", "snippet": text}]}]


def select(ids, menu, source):
    return selection.bind_selected_views({"source_view_ids": ids}, menu, source, ["Alpha", "Beta"], [])


def test_runtime_ids_preserve_sources_when_model_fact_identity_would_clear_them():
    original = chains() + [{"sources": [{"title": "Beta guide", "url": "https://beta.example/docs",
        "snippet": "Beta requires a separate service. Its service needs a durable store."}]}]
    before = deepcopy(original)
    malformed = {"source_facts": [{"id": "F1", "evidence_id": 1}, {"id": "F1", "evidence_id": 2}]}
    assert not bind_evidence_choices(malformed, original, [], [])["source_facts"]
    packet, menu = selection.selection_view_packet(original)
    selected = {"source_view_ids": ["S2", "S1", "S2"], **malformed, "source_ranges": []}
    facts = selection.bind_selected_views(selected, menu, original, ["Alpha", "Beta"], [])
    assert [(f["id"], f["evidence_id"]) for f in facts] == [("F1", 2), ("F2", 1)]
    assert facts[0]["saved_text"] == original[1]["sources"][0]["snippet"]
    assert facts[1]["saved_text"] == original[0]["sources"][0]["snippet"]
    assert all(f["status"] == "unknown" for f in facts)
    assert original == before and '"id":"S1"' in packet
    assert json.loads(packet.splitlines()[0])["source_host"] == "alpha.example"
    assert "https://alpha.example/docs" not in packet


def test_long_views_bind_displayed_context_once_and_preserve_far_material():
    sentences = [f"Section {i} requires administrators to retain the complete recovery prerequisites and configuration history." for i in range(17)]
    original = chains(" ".join(sentences))
    before = deepcopy(original)
    packet, menu = selection.selection_view_packet(original)
    assert len(menu) >= 2 and all("source_ranges" in v["reference"] for v in menu.values())
    visible = json.loads(packet)
    for view in visible["views"]:
        fact = select([view["id"]], menu, original)[0]
        first, stop = view["included_sentence_range"]
        assert fact["saved_text"] == " ".join(sentences[first:stop])
        assert len(fact["saved_text"]) <= 1200 and stop - first <= 16
        assert fact["source_ranges"] == menu[view["id"]]["reference"]["source_ranges"]
    assert sentences[-1] in select([visible["views"][-1]["id"]], menu, original)[0]["saved_text"]
    assert original == before


def test_repeated_short_focus_must_not_hide_a_valid_longer_window():
    text = "Alpha retains records. The primary retention condition must be configured explicitly. "
    text += " ".join(f"Section {i} explains separate storage administration responsibilities and recovery prerequisites." for i in range(14))
    text += " Alpha retains records. A secondary deployment has distinct retention conditions."
    original = chains(text)
    assert 1200 < len(text) <= 2000
    assert selection.selected_passages(original[0]["sources"][0], [[0, 1]]) is None
    _, menu = selection.selection_view_packet(original)
    first = menu["S1W1"]["reference"]["source_ranges"][0]
    assert first[0] == 0 and first[1] > 1
    assert "primary retention condition" in select(["S1W1"], menu, original)[0]["saved_text"]


def test_scoped_conflict_views_exclude_dispute_and_neighbors_without_clearing_flag():
    text = "Alpha permits one writer. Contention depends on the workload. "
    text += "Administrators retain configuration history. Recovery needs a separate owner. "
    text += "Alpha stores encrypted snapshots. Restoration requires the original key. Validate restoration in isolation."
    original = chains(text)
    source = original[0]["sources"][0]
    source["conflict_scope"] = make_conflict_scope(source, [[0, 1], [2, 3]])
    original[0]["disputed"] = True
    before = deepcopy(original)
    packet, menu = selection.selection_view_packet(original)
    assert menu and "S1" not in menu
    for view in json.loads(packet)["views"]:
        first, stop = view["included_sentence_range"]
        assert first >= 3 and stop <= 7
    facts = select(list(menu)[:5], menu, original)
    assert facts and all("original key" in fact["saved_text"] for fact in facts)
    assert original == before and original[0]["disputed"]
    source["conflict_scope"]["identity_sha256"] = "0" * 64
    assert not selection.selection_view_packet(original)[1]
    assert not select(list(menu), menu, original)


def test_disjoint_locations_remain_whole_views_and_source_mutation_fences_selection():
    passages = ["Alpha retains encrypted snapshots.", "Restoration requires the original key."]
    original = chains(" ".join(passages)); original[0]["sources"][0]["passages"] = passages
    packet, menu = selection.selection_view_packet(original)
    row = json.loads(packet)
    assert row["separate_locations"] and [s["location"] for s in row["sentences"]] == [1, 2]
    assert set(menu) == {"S1"}
    assert select(["S1"], menu, original)[0]["saved_passages"] == passages
    original[0]["sources"][0]["url"] = "https://other.example/docs"
    assert not select(["S1"], menu, original)


def test_long_source_tail_mutation_cannot_change_an_already_displayed_view():
    text = " ".join(f"Section {i} documents complete storage configuration and operational prerequisites for administrators." for i in range(17))
    original = chains(text); _, menu = selection.selection_view_packet(original)
    assert select(["S1W1"], menu, original)
    original[0]["sources"][0]["snippet"] += " A distant required condition changes."
    assert not select(["S1W1"], menu, original)


@pytest.mark.parametrize("ids", [None, "S1", [], [True, 1, {}, "S999"], ["S1"] * 6])
def test_invalid_or_oversized_selection_never_guesses_or_truncates(ids):
    original = chains(); _, menu = selection.selection_view_packet(original)
    assert not select(ids, menu, original)


def test_menu_caps_drop_entire_rows_and_only_advertised_ids_can_bind(monkeypatch):
    original = chains() + [{"sources": [{"title": "Beta guide", "url": "https://beta.example/docs",
        "snippet": "Beta retains records. Configuration determines retention."}]}]
    first, _ = selection.selection_view_packet(original[:1])
    monkeypatch.setattr(selection, "MAX_PACKET_BYTES", len(first.encode("utf-8")))
    packet, menu = selection.selection_view_packet(original)
    assert packet == first and set(menu) == {"S1"}
    assert not select(["S2"], menu, original)
    monkeypatch.setattr(selection, "MAX_PACKET_BYTES", 24000)
    monkeypatch.setattr(selection, "MAX_PACKET_SOURCES", 1)
    assert set(selection.selection_view_packet(original)[1]) == {"S1"}


def test_profile_observes_view_ids_and_keeps_historical_range_profile_readable():
    assert output_shape_valid("conclusion_synthesizer", {"source_view_ids": ["S1"]}, profile="fact-view-selection-v1")
    assert not output_shape_valid("conclusion_synthesizer", {"source_view_ids": [1]}, profile="fact-view-selection-v1")
    assert output_shape_valid("conclusion_synthesizer", {"source_facts": [{"id": "F1", "evidence_id": 1,
        "source_ranges": [[0, 2]]}]}, profile="fact-selection-v2")


def test_unusable_legacy_row_does_not_hide_later_whole_source(monkeypatch):
    unusable = " ".join(["Storage administrators retain configuration history before changing operational requirements."] * 17)
    original = chains(unusable) + [{"sources": [{"title": "Beta guide", "url": "https://beta.example/docs",
        "snippet": "Beta retains records. Configuration determines retention."}]}]
    monkeypatch.setattr(selection, "MAX_PACKET_BYTES", 2200)
    assert selection.selection_packet(original)[1] == {2}
    packet, menu = selection.selection_view_packet(original)
    assert set(menu) == {"S2"} and len(packet.encode("utf-8")) <= selection.MAX_PACKET_BYTES
    assert select(["S2"], menu, original)[0]["saved_text"] == original[1]["sources"][0]["snippet"]


def test_view_metadata_overflow_uses_one_admission_for_both_projections(monkeypatch):
    text = " ".join(f"Section {i} explains complete storage administration and recovery configuration requirements." for i in range(17))
    original = chains(text) + [{"sources": [{"title": "Beta guide", "url": "https://beta.example/docs",
        "snippet": "Beta retains records. Configuration determines retention."}]}]
    original += [{"sources": [{"title": "Later range guide", "url": "https://later.example/docs", "snippet": text}]}]
    legacy_first, _ = selection.selection_packet(original[:1])
    monkeypatch.setattr(selection, "MAX_PACKET_BYTES", len(legacy_first.encode("utf-8")))
    assert selection.selection_packet(original)[1] == {2}
    packet, menu = selection.selection_view_packet(original)
    assert set(menu) == {"S2"} and len(packet.encode("utf-8")) <= selection.MAX_PACKET_BYTES
    # Range binding uses the same final admission as both displayed projections.
    assert not bind_evidence_choices({"source_facts": [{"id": "F1", "evidence_id": 3,
        "source_ranges": [[0, 2]]}]}, original, [], [])["source_facts"]


@pytest.mark.parametrize("long_tail", [False, True])
def test_final_menu_preserves_candidates_after_source_count_and_byte_caps(long_tail):
    original = []
    for index in range(25):
        product = "Alpha" if index < 24 else "Beta"
        text = f"{product} retains records. Retention requires configuration."
        if long_tail:
            text += " " + " ".join(f"Section {n} describes independent storage administration responsibilities and recovery prerequisites." for n in range(14))
        original.append({"sources": [{"title": f"{product} guide {index}",
            "url": f"https://docs.example/guide/{index}", "snippet": text}]})
    candidates = ["continue using Alpha", "switch to Beta"]
    before = deepcopy(original)
    packet, menu = selection.selection_view_packet(original, candidates)
    numeric_packet, numbers = selection.selection_packet(original, candidates)
    assert 25 in numbers and 1 in numbers and len(numbers) <= 24
    assert numbers == {view["reference"]["evidence_id"] for view in menu.values()}
    assert max(len(packet.encode("utf-8")), len(numeric_packet.encode("utf-8"))) <= 24000
    chosen = next(key for key, view in menu.items() if view["reference"]["evidence_id"] == 25)
    facts = selection.bind_selected_views({"source_view_ids": [chosen]}, menu, original, candidates, [])
    assert len(facts) == 1 and "Retention requires configuration." in facts[0]["saved_text"]
    assert bind_evidence_choices({"source_facts": facts}, original, candidates, [])["source_facts"] == facts
    assert original == before


def test_unbindable_candidate_row_does_not_consume_reserved_opportunity():
    original = [chains()[0] for _ in range(24)]
    for i, chain in enumerate(original):
        chain["sources"][0].update(title=f"Alpha guide {i}", url=f"https://alpha.example/{i}")
    bad = {"disputed": True, "sources": [{"title": "Beta invalid", "url": "https://beta.example/bad",
        "snippet": "Beta retains records."}]}
    good = {"sources": [{"title": "Beta guide", "url": "https://beta.example/good",
        "snippet": "Beta retains records. Configuration determines retention."}]}
    original.extend([bad, good])
    _, menu = selection.selection_view_packet(original, ["Alpha", "Beta"])
    assert "S26" in menu and "S25" not in menu and len(menu) == 24


def test_overlapping_products_and_same_product_actions_share_literal_identity(monkeypatch):
    original = []
    for i, title in enumerate(["Alpha Pro guide", "Alpha Pro comparison with Alpha", "Alpha guide", "Beta guide"]):
        original.append({"sources": [{"title": title, "url": f"https://docs.example/{i}",
            "snippet": "Retained records require configuration."}]})
    monkeypatch.setattr(selection, "MAX_PACKET_SOURCES", 3)
    candidates = ["continue using Alpha", "switch to Alpha", "Alpha Pro", "Beta"]
    _, menu = selection.selection_view_packet(original, candidates)
    assert set(menu) == {"S1", "S3", "S4"}


def test_forged_offered_mapping_cannot_admit_a_source_outside_final_menu(monkeypatch):
    original = chains() + [{"sources": [{"title": "Beta guide", "url": "https://beta.example/docs",
        "snippet": "Beta retains records. Configuration determines retention."}]}]
    _, forged = selection.selection_view_packet(original, ["Alpha", "Beta"])
    forged["S999"] = None
    assert not selection.bind_selected_views({"source_view_ids": ["S999"]}, forged, original, ["Alpha", "Beta"], [])
    monkeypatch.setattr(selection, "MAX_PACKET_SOURCES", 1)
    assert not selection.bind_selected_views({"source_view_ids": ["S2"]}, forged, original, ["Alpha", "Beta"], [])


@pytest.mark.parametrize("candidates", [[], ["Alpha", "Beta"], ["Alpha", "Beta", "Gamma"]])
def test_capacity_gaps_do_not_raise_limits_or_truncate_qualifiers(candidates, monkeypatch):
    original = chains() + [{"sources": [{"title": "Beta guide", "url": "https://beta.example/docs",
        "snippet": "Beta retains records. Configuration determines retention."}]}]
    monkeypatch.setattr(selection, "MAX_PACKET_SOURCES", 1)
    packet, menu = selection.selection_view_packet(original, candidates)
    numeric, numbers = selection.selection_packet(original, candidates)
    assert set(menu) == {"S1"} and numbers == {1}
    assert original[0]["sources"][0]["snippet"].split(". ")[-1] in packet
    assert len(numeric.encode("utf-8")) <= 24000


async def test_default_menu_range_survives_citation_review_and_rejects_unoffered_range(monkeypatch):
    from unittest.mock import AsyncMock
    import httpx
    from deepchoice.agents import conclusion_synthesizer as synth
    from deepchoice.agents.citation_validator import CitationValidatorAgent
    from deepchoice.citations.verifier import verify_citations
    from deepchoice.contracts.manifest import build_run_manifest
    from deepchoice.utils.analysis_review import prepare_analysis_review

    tail = " ".join(f"Section {n} describes independent storage administration responsibilities and recovery prerequisites." for n in range(14))
    original = []
    for i in range(3):
        product = "Alpha" if i < 2 else "Beta"
        original.append({"evidence_strength": "moderate", "sources": [{"title": f"{product} guide {i}",
            "url": f"https://docs.example/{i}",
            "snippet": f"{product} retains records. Retention requires configuration. Administrators retain a recovery log. " + tail}]})
    monkeypatch.setattr(selection, "MAX_PACKET_SOURCES", 2)
    task = {"query": "Choose Alpha or Beta under retention constraints.", "candidate_techs": ["Alpha", "Beta"]}
    model = AsyncMock(return_value={**{"source_view_ids": ["S1W1", "S3W1"],
        "source_facts": [{"id": "F1", "evidence_id": 2}]}, **{"decision_analysis": [{
            "kind": "answer", "option": "", "question_id": "R0", "basis_refs": ["S1W1B1", "S1W1B2"],
            "reasoning": "Retention depends on configuration.", "assumptions": [],
            "change_condition": "Reconsider if retention expires."}]}})
    monkeypatch.setattr(synth, "call_model", model)
    state = {"task": task, "evidence_chains": deepcopy(original)}
    state.update(await run_staged(synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(task)), state))
    assert model.await_count == 1
    assert '"id":"S3W1"' in model.await_args_list[0].args[0][0]["content"]
    assert [f["evidence_id"] for f in state["final_recommendation"]["source_facts"]] == [1, 3]
    async def fetch(*args, **kwargs):
        i = int(args[1].rsplit("/", 1)[1])
        return httpx.Response(200, text=original[i]["sources"][0]["snippet"], headers={"content-type": "text/plain"})
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    state.update(await CitationValidatorAgent().run(state))
    assert {f["status"] for f in state["final_recommendation"]["source_facts"]} == {"verified"}
    assert len(prepare_analysis_review(state).slots) == 1
    assert all("source_ranges" in f for f in state["final_recommendation"]["source_facts"])
    raw = {"source_facts": [{"id": "F1", "evidence_id": 2, "source_ranges": [[0, 2]]}]}
    assert not bind_evidence_choices(raw, original, task["candidate_techs"], [])["source_facts"]
    # A fact legitimately bound under another menu is not authority for this task menu.
    foreign = bind_evidence_choices(raw, original, [], [])
    assert len(foreign["source_facts"]) == 1
    verification, _ = await verify_citations(foreign, original, candidates=task["candidate_techs"])
    assert {c.status.value for c in verification.checks} == {"unknown"}
    assert {c.reason.value for c in verification.checks} == {"content_insufficient"}
    assert [c["sources"][0]["snippet"] for c in state["evidence_chains"]] == [c["sources"][0]["snippet"] for c in original]


OMITTED_SHORT_TEXT = (
    "Alpha stores retained records. Only retained records can be replayed. "
    "A consumer can request an earlier offset. Replays preserve order within a partition. "
    "Different partitions may proceed independently. Operators must choose a retention period. "
    "[...] Other sections describe deployment."
)


def test_short_omitted_source_offers_complete_ranges_with_original_coordinates():
    original = chains(OMITTED_SHORT_TEXT)
    before = deepcopy(original)
    packet, menu = selection.selection_view_packet(original, ["Alpha"])
    assert "S1" in menu and len(menu) > 1
    assert "[...]" in packet  # Preserve the full saved input; never splice the source.
    assert any("source_ranges" in view["reference"] for view in menu.values())
    rows = json.loads(packet)
    for view in rows["views"]:
        fact = menu[view["id"]]["fact"]
        first, stop = view["included_sentence_range"]
        assert tuple(s["text"] for s in rows["sentences"][first:stop]) == selection.selection_sentences({"snippet": fact["saved_text"]})
        if "source_ranges" in menu[view["id"]]["reference"]:
            assert "[...]" not in fact["saved_text"]
        assert bind_evidence_choices({"source_facts": [fact]}, original, ["Alpha"], [])["source_facts"] == [fact]
    assert any(view["reference"].get("source_ranges") == [[2, 4]] for view in menu.values())
    assert original == before
    # Whole numeric compatibility input still earns no location/support by binding.
    whole = bind_evidence_choices({"source_facts": [{"id": "F1", "evidence_id": 1}]}, original, ["Alpha"], [])
    assert whole["source_facts"][0]["saved_text"] == OMITTED_SHORT_TEXT
    assert whole["source_facts"][0]["status"] == "unknown"


@pytest.mark.parametrize("text", [
    "Callable[..., T] defines a callback signature.",
    "The expression array[..., 0] selects a dimension.",
    "Alpha replays records. [...] Only retained records can be replayed.",
])
def test_short_literal_or_adjacent_ellipsis_without_safe_range_retains_whole_view(text):
    original = chains(text)
    _, menu = selection.selection_view_packet(original)
    assert set(menu) == {"S1"}
    assert menu["S1"]["fact"]["saved_text"] == text
    assert "source_ranges" not in menu["S1"]["reference"]


def test_literal_code_ellipsis_with_safe_remote_context_does_not_change_source_text():
    text = OMITTED_SHORT_TEXT.replace("[...]", "The expression array[..., 0] selects a dimension.")
    original = chains(text)
    _, menu = selection.selection_view_packet(original)
    assert "S1" in menu and len(menu) > 1
    assert menu["S1"]["fact"]["saved_text"] == text
    assert all("..." not in view["fact"]["saved_text"] for view in menu.values() if "source_ranges" in view["reference"])
    assert original[0]["sources"][0]["snippet"] == text


def test_whole_fallback_waits_for_successful_range_binding(monkeypatch):
    from deepchoice.utils import evidence_choices

    bind = evidence_choices.bind_source_fact
    def reject_ranges(item, binding):
        return None if "source_ranges" in item else bind(item, binding)
    monkeypatch.setattr(evidence_choices, "bind_source_fact", reject_ranges)
    original = chains(OMITTED_SHORT_TEXT)
    _, menu = selection.selection_view_packet(original)
    assert set(menu) == {"S1"}
    assert menu["S1"]["fact"]["saved_text"] == OMITTED_SHORT_TEXT


async def test_short_omitted_menu_analysis_survives_default_citation_review_and_render(monkeypatch):
    from unittest.mock import AsyncMock
    import httpx
    from deepchoice.agents import conclusion_synthesizer as synth, self_reviewer as review
    from deepchoice.agents.citation_validator import CitationValidatorAgent
    from deepchoice.agents.report_generator import FORMAT_RENDERERS
    from deepchoice.contracts.manifest import build_run_manifest
    from tests.test_self_review import reviewed

    original = chains(OMITTED_SHORT_TEXT)
    _, menu = selection.selection_view_packet(original, ["Alpha"])
    chosen = next((key for key, view in menu.items()
                   if view["reference"].get("source_ranges") == [[2, 4]]), "S1")
    reasoning = "Replay depends on retained records and preserves order only within a partition."
    model = AsyncMock(return_value={**{"source_view_ids": [chosen]}, **{"decision_analysis": [{
        "kind": "answer", "option": "", "question_id": "R0", "basis_refs": [f"{chosen}B1", f"{chosen}B2"],
        "reasoning": reasoning, "assumptions": [],
        "change_condition": "Reassess if the required records have expired."}]}})
    monkeypatch.setattr(synth, "call_model", model)
    page = OMITTED_SHORT_TEXT.replace("[...]", "Details about unrelated clients appear in this section.")
    fetch = AsyncMock(return_value=httpx.Response(200, text=page, headers={"content-type": "text/plain"}))
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    task = {"query": "How can Alpha consumers replay records?", "candidate_techs": ["Alpha"]}
    state = {"task": task, "evidence_chains": deepcopy(original)}
    state.update(await run_staged(synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(task)), state))
    state.update(await CitationValidatorAgent().run(state))
    reviewed_model = AsyncMock(return_value=reviewed([{
        "analysis_id": "A1", "action": "keep", "source_checks": [["F1", "supports", [1, 2]]]}]))
    monkeypatch.setattr(review, "call_model", reviewed_model)
    state.update(await review.SelfReviewerAgent().run(state))
    assert len(state["final_recommendation"]["decision_analysis"]) == 1
    assert reviewed_model.await_count == 1 and model.await_count == 1 and fetch.await_count == 1
    assert state["final_recommendation"]["source_facts"][0]["source_ranges"] == [[2, 4]]
    for render in FORMAT_RENDERERS.values():
        assert reasoning in render(state)
    assert state["evidence_chains"][0]["sources"][0]["snippet"] == OMITTED_SHORT_TEXT
    # A mismatching live page must still withdraw the same bound analysis.
    fetch.return_value = httpx.Response(200, text="Alpha is an unrelated language.", headers={"content-type": "text/plain"})
    state.update(await CitationValidatorAgent().run(state))
    assert state["final_recommendation"]["decision_analysis"] == []
    assert state["final_recommendation"]["source_facts"][0]["status"] == "unknown"


async def test_whole_and_local_same_source_keep_separate_citation_eligibility(monkeypatch):
    import httpx
    from deepchoice.citations.verifier import verify_citations
    from deepchoice.utils.evidence_choices import calibrate_evidence_choices

    original = chains(OMITTED_SHORT_TEXT)
    _, menu = selection.selection_view_packet(original)
    local = next(key for key, value in menu.items() if value["reference"].get("source_ranges") == [[2, 4]])
    facts = select(["S1", local], menu, original)
    assert [f["id"] for f in facts] == ["F1", "F2"]
    assert len({f["canonical_url"] for f in facts}) == 1
    async def fetch(*args, **kwargs):
        page = OMITTED_SHORT_TEXT.replace("[...]", "Details about unrelated clients appear here.")
        return httpx.Response(200, text=page, headers={"content-type": "text/plain"})
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    verification, _ = await verify_citations({"source_facts": facts}, original)
    calibrated = calibrate_evidence_choices({"source_facts": facts}, verification)
    assert [f["status"] for f in calibrated["source_facts"]] == ["unknown", "verified"]
    assert calibrated["source_facts"][0]["review_availability"] == "sentence_scoped"
    assert calibrated["source_facts"][0]["reviewable_sentence_ids"] == [1, 2, 3, 4, 5]


def test_extra_view_metadata_obeys_shared_capacity_without_partial_source(monkeypatch):
    import re

    original = chains(OMITTED_SHORT_TEXT)
    with monkeypatch.context() as context:
        context.setattr(selection, "_OMISSION", re.compile(r"(?!)"))
        old_packet, _ = selection.selection_view_packet(original)
        old_numeric, _ = selection.selection_packet(original)
    limit = max(len(old_packet.encode("utf-8")), len(old_numeric.encode("utf-8")))
    added_packet, _ = selection.selection_view_packet(original)
    assert len(added_packet.encode("utf-8")) > limit
    original += [{"sources": [{"title": "Beta guide", "url": "https://beta.example/docs",
                               "snippet": "Beta retains records. Configuration determines retention."}]}]
    monkeypatch.setattr(selection, "MAX_PACKET_BYTES", limit)
    packet, menu = selection.selection_view_packet(original, ["Alpha", "Beta"])
    numeric, ids = selection.selection_packet(original, ["Alpha", "Beta"])
    assert set(menu) == {"S2"} and ids == {2}
    assert max(len(packet.encode("utf-8")), len(numeric.encode("utf-8"))) <= limit
    assert not selection.bind_selected_views({"source_view_ids": ["S1"]}, {"S1": {}}, original, ["Alpha", "Beta"], [])


@pytest.mark.parametrize("reference", ["unselected_view", "outside_view", "selected_view", "changed_menu"])
def test_joint_quotes_remain_bound_to_selected_overlapping_view(reference):
    original = chains(OMITTED_SHORT_TEXT)
    packet, offered = selection.selection_view_packet(original, ["Alpha"])
    selected_id = next(key for key in offered if key != "S1")
    from deepchoice.citations.verifier import _split_sentences
    count = len(_split_sentences(offered[selected_id]["fact"]["saved_text"]))
    token = ("S1B1" if reference == "unselected_view" else
             f"{selected_id}B{count+1}" if reference == "outside_view" else f"{selected_id}B1")
    raw = {"source_view_ids": [selected_id], "decision_analysis": [{
        "kind": "answer", "option": "", "question_id": "R0", "basis_refs": [token],
        "reasoning": "A conditional explanation.", "assumptions": [], "change_condition": "Reassess the premise."}]}
    assert token in packet or reference == "outside_view"
    if reference == "changed_menu":
        original[0]["sources"][0]["snippet"] += " A new saved qualification applies."
    facts, rows = selection.bind_selection_answers(raw, offered, original, ["Alpha"], {"R0"}, {})
    assert bool(rows) is (reference == "selected_view")
    if rows:
        assert rows[0]["basis"][0]["fact_id"] == facts[0]["id"]
        assert rows[0]["basis"][0]["source_sentences"] == [_split_sentences(facts[0]["saved_text"])[0]]
