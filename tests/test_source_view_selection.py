"""Runtime views reduce model coordinates without relaxing source boundaries."""
from copy import deepcopy
import json

import pytest

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
    legacy_first, _ = selection.selection_packet(original[:1])
    monkeypatch.setattr(selection, "MAX_PACKET_BYTES", len(legacy_first.encode("utf-8")))
    assert selection.selection_packet(original)[1] == {1}
    packet, menu = selection.selection_view_packet(original)
    assert set(menu) == {"S2"} and len(packet.encode("utf-8")) <= selection.MAX_PACKET_BYTES
    assert select(["S2"], menu, original)[0]["saved_text"] == original[1]["sources"][0]["snippet"]


def test_view_metadata_overflow_allows_whole_source_replacement_but_keeps_range_admission(monkeypatch):
    text = " ".join(f"Section {i} explains complete storage administration and recovery configuration requirements." for i in range(17))
    original = chains(text) + [{"sources": [{"title": "Beta guide", "url": "https://beta.example/docs",
        "snippet": "Beta retains records. Configuration determines retention."}]}]
    original += [{"sources": [{"title": "Later range guide", "url": "https://later.example/docs", "snippet": text}]}]
    legacy_first, _ = selection.selection_packet(original[:1])
    monkeypatch.setattr(selection, "MAX_PACKET_BYTES", len(legacy_first.encode("utf-8")))
    assert selection.selection_packet(original)[1] == {1}
    packet, menu = selection.selection_view_packet(original)
    assert set(menu) == {"S2"} and len(packet.encode("utf-8")) <= selection.MAX_PACKET_BYTES
    # Every later range is still subject to the historical rebind/citation menu.
    assert not bind_evidence_choices({"source_facts": [{"id": "F1", "evidence_id": 3,
        "source_ranges": [[0, 2]]}]}, original, [], [])["source_facts"]
