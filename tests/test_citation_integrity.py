"""Citation identity and self-review input contracts (v8).

The fixed material is the sixth real run's saved snapshot. It is used only to
replay the citation engine and the self-review input; the original model output
was not preserved, so these tests prove mechanism, not what the model wrote then.
"""
import asyncio
import copy
import json
import pathlib
import re

import pytest

from deepchoice.agents import conclusion_synthesizer as cs
from deepchoice.agents import self_reviewer as sr

V6_SNAPSHOT = (pathlib.Path(__file__).resolve().parents[1]
               / "outputs"
               / "b927ce67-1ca2-475e-974c-251c7c2aec3f"
               / "research_snapshot.json")

COMMA_TITLE = "Deploy, Calibrate, Monitor, Heal — An Autonomous AI SRE Agent"
PLAIN_TITLE = "Official Runtime Documentation"


def _chains(*sources):
    return [{"sources": list(sources)}]


def _source(title, body="a real body", url=None):
    entry = {"title": title, "snippet": body}
    if url:
        entry["url"] = url
    return entry


def test_gap_notes_are_not_counted_as_used_sources():
    """The reference list is derived from `[Source: ...]` only; a located gap is
    not a citation and must not be reported as a basis."""
    from deepchoice.formats.basis import used_sources

    sources = [_source(PLAIN_TITLE, url="https://example.com/a")]
    rec = {"recommendation": (f"a [Source: {PLAIN_TITLE}] "
                              f"b 〔引用未解析：来源标题 “Missing”〕")}
    used = used_sources(rec, _chains(*sources))
    assert [entry["title"] for entry in used] == [PLAIN_TITLE]


def test_the_reference_list_uses_the_registered_canonical_title():
    """Binding writes the registered title, so the reference lookup by title
    finds the source even when the model wrote a slightly different form."""
    from deepchoice.formats.basis import used_sources

    chains = _chains(_source(COMMA_TITLE, url="https://example.com/comma"))
    bound = cs.apply_citation_rules(
        {"recommendation": f"reason [Source: {COMMA_TITLE}]"}, chains)
    used = used_sources(bound, chains)
    assert [entry["title"] for entry in used] == [COMMA_TITLE]


def _registry(*sources):
    return cs.build_source_registry(_chains(*sources))


class TestLiteralTitleIdentity:
    def test_a_title_containing_commas_is_matched_whole(self):
        """The old sanitizer split a marker's titles on commas, so this real
        title was truncated and dropped; numbers kept it. Full identity first."""
        registry = _registry(_source(COMMA_TITLE))
        result = {"recommendation": f"Use it [Source: {COMMA_TITLE}]."}
        cs.apply_citation_rules(result, _chains(_source(COMMA_TITLE)))
        assert f"[Source: {COMMA_TITLE}]" in result["recommendation"]
        assert "引用未解析" not in result["recommendation"]
        assert cs.canonical_source_title(registry, COMMA_TITLE) == COMMA_TITLE

    def test_a_number_and_a_literal_name_the_same_canonical_source(self):
        sources = [_source(COMMA_TITLE)]
        registry = _registry(*sources)
        mapping = registry["mapping"]
        number = next(iter(mapping))
        literal = cs.resolve_text(f"理由 [Source: {COMMA_TITLE}]",
                                  registry=registry, mapping=mapping)
        numbered = cs.resolve_text(f"理由 [[{number}]]",
                                   registry=registry, mapping=mapping)
        assert literal == numbered == f"理由 [Source: {COMMA_TITLE}]"

    def test_multi_source_markers_split_only_on_the_explicit_separator(self):
        registry = _registry(_source(COMMA_TITLE), _source(PLAIN_TITLE))
        text = f"理由 [Source: {COMMA_TITLE}, Source: {PLAIN_TITLE}]"
        resolved = cs.resolve_text(text, registry=registry)
        assert resolved == (f"理由 [Source: {COMMA_TITLE}, Source: {PLAIN_TITLE}]")

    def test_an_ambiguous_title_is_not_resolved_to_one_arbitrary_source(self):
        # Same written title, two different source identities.
        registry = _registry(_source(PLAIN_TITLE, url="https://a.example/x"),
                             _source(PLAIN_TITLE, url="https://b.example/y"))
        assert cs.canonical_source_title(registry, PLAIN_TITLE) is None
        resolved = cs.resolve_text(f"理由 [Source: {PLAIN_TITLE}]",
                                   registry=registry)
        assert f"[Source: {PLAIN_TITLE}]" not in resolved
        assert "引用未解析" in resolved
        assert cs.unresolved_citations(resolved, registry=registry)


class TestUnresolvedCitationsStayVisible:
    def test_a_fabricated_title_becomes_a_located_gap(self):
        registry = _registry(_source(PLAIN_TITLE))
        resolved = cs.resolve_text("理由 [Source: Made Up Docs]",
                                   registry=registry)
        assert "[Source: Made Up Docs]" not in resolved
        assert "Made Up Docs" in resolved
        assert "引用未解析" in resolved
        assert cs.unresolved_citations(resolved, registry=registry)

    def test_an_unknown_number_becomes_a_located_gap(self):
        registry = _registry(_source(PLAIN_TITLE))
        resolved = cs.resolve_text("理由 [[99]]", registry=registry)
        assert "[[99]]" not in resolved
        assert "99" in resolved
        assert "引用未解析" in resolved

    def test_known_and_unknown_numbers_in_one_marker(self):
        registry = _registry(_source(PLAIN_TITLE))
        resolved = cs.resolve_text("理由 [[1,99]]", registry=registry)
        assert f"[Source: {PLAIN_TITLE}]" in resolved
        assert "99" in resolved
        assert "引用未解析" in resolved

    def test_a_known_citation_is_not_reported_as_unresolved(self):
        registry = _registry(_source(PLAIN_TITLE))
        resolved = cs.resolve_text(f"理由 [[1]] 与 [Source: {PLAIN_TITLE}]",
                                   registry=registry)
        assert resolved.count(f"[Source: {PLAIN_TITLE}]") == 2
        assert not cs.unresolved_citations(resolved, registry=registry)

    def test_array_and_interval_markers_are_not_citations(self):
        registry = _registry(_source(PLAIN_TITLE))
        for text in ("the interval [[0,1]] is normalized", "code: arr[[1,2]] = x",
                     "x[[1]]y[[2]]z", "row[[2,3]][0]", "matrix [[1, 2]] entry"):
            assert cs.resolve_text(text, registry=registry) == text, text
            assert not cs.unresolved_citations(text, registry=registry), text

    def test_a_field_that_is_only_markers_is_withdrawn(self):
        result = {"recommendation": "[[1]]"}
        cs.apply_citation_rules(result, _chains(_source(PLAIN_TITLE)))
        assert result["recommendation"].strip()
        assert "撤回" in result["recommendation"] or \
            "withdrawn" in result["recommendation"].lower()


class TestSelfReviewInput:
    def _payload(self, monkeypatch, state):
        captured = {}

        async def fake_call_model(prompt, **kwargs):
            captured["prompt"] = prompt
            return {"confidence": "medium", "knowledge_gaps": [], "corrections": []}

        monkeypatch.setattr(sr, "call_model", fake_call_model)
        asyncio.run(sr.SelfReviewerAgent().run(dict(state)))
        return captured["prompt"][1]["content"]

    def _state(self):
        chain = {"sources": [
            {"title": COMMA_TITLE, "url": "https://example.com/a",
             "snippet": "snippet only", "content": "the full stored body text",
             "provenance": "publisher", "channel": "web"},
            {"title": PLAIN_TITLE, "url": "https://example.com/b",
             "snippet": "second body"},
        ]}
        recommendation = {
            "recommendation": f"Use it [Source: {COMMA_TITLE}].",
            "confidence_rationale": "because [Source: {PLAIN_TITLE}].",
            "ranked_options": [{"name": "A", "rationale": "r",
                                "constraint_fit_reason": "fit",
                                "key_strength": "s", "key_weakness": "w"}],
            "trade_offs": [{"dimension": "d", "finding": "f", "impact": "i"}],
            "unresolved_questions": ["a real open question"],
        }
        return {
            "task": {"query": "q", "candidate_techs": ["A", "B"]},
            "report": "REPORT BODY MARKER",
            "evidence_chains": [chain],
            "final_recommendation": recommendation,
            "confidence": "medium",
            "knowledge_gaps": ["a recorded gap"],
            "sub_questions": ["Original sub-question one?"],
            "retry_count": 0,
        }

    def test_the_reviewer_gets_the_same_numbered_source_package(self, monkeypatch):
        payload = self._payload(monkeypatch, self._state())
        assert "## Source Register" in payload
        assert f"[[1]] {COMMA_TITLE}" in payload
        assert "url: https://example.com/a" in payload
        # The body shown is the stored content, not the shorter snippet.
        assert "the full stored body text" in payload
        assert "snippet only" not in payload.split("## Original Sub-Questions")[0]

    def test_the_reviewer_is_told_a_citation_is_not_proof(self, monkeypatch):
        payload = self._payload(monkeypatch, self._state())
        prompt = sr.REVIEW_SYSTEM.lower()
        assert "not proof" in prompt or "not a proof" in prompt
        assert "pre-computed" not in prompt
        assert "do not re-evaluate" not in prompt
        assert "do not re-count" not in prompt
        assert "revision targets" in payload.lower()
        assert "report body marker" in payload.lower()

    def test_completeness_lists_missing_fields_with_the_shared_field_list(
            self, monkeypatch):
        payload = self._payload(monkeypatch, self._state())
        completeness = payload.split("## Citation Completeness")[1].split("##")[0]
        # confidence_rationale and constraint_fit_reason were missing from the
        # old self-review field list; both now appear in the shared traversal.
        assert "confidence_rationale" in completeness
        assert "option=A/constraint_fit_reason" in completeness
        assert "option=A/key_strength" in completeness
        assert "trade-off=d/finding" in completeness

    def test_the_payload_does_not_duplicate_the_candidate_prose(self, monkeypatch):
        payload = self._payload(monkeypatch, self._state())
        # The rationale text lives in the report; the locator section names only
        # the field, so it is not a second copy.
        assert payload.count("REPORT BODY MARKER") == 1
        locators = payload.split("## Revision Targets")[1].split("##")[0]
        assert "rationale" in locators
        assert "The per-candidate justifications below" not in payload
        # Fields this report format does not print are the exception: the
        # reviewer needs their current text to check them.
        assert "(not printed by this report format) — fit" in locators

    def test_the_correction_contract_names_the_sections_it_actually_gets(
            self, monkeypatch):
        payload = self._payload(monkeypatch, self._state())
        assert "decision claims to check" not in payload.lower()
        assert "revision targets" in payload.lower()
        contract = sr.REVIEW_SYSTEM
        assert "Decision Claims To Check" not in contract
        assert "Revision Targets" in contract
        assert "Each is printed in the report" not in contract

    def test_a_revision_binds_numbers_with_the_same_registry(self, monkeypatch):
        state = self._state()

        async def fake_call_model(prompt, **kwargs):
            return {"confidence": "medium", "knowledge_gaps": [], "corrections": [
                {"option": "A", "field": "rationale", "action": "revise",
                 "corrected": f"理由 [[1]] 和 [Source: {PLAIN_TITLE}]",
                 "reason": "fix"}]}

        monkeypatch.setattr(sr, "call_model", fake_call_model)
        out = asyncio.run(sr.SelfReviewerAgent().run(dict(state)))
        rationale = out["final_recommendation"]["ranked_options"][0]["rationale"]
        assert f"[Source: {COMMA_TITLE}]" in rationale
        assert f"[Source: {PLAIN_TITLE}]" in rationale
        assert "引用未解析" not in rationale

    def test_a_revision_with_a_fabricated_citation_keeps_its_prose(self, monkeypatch):
        state = self._state()

        async def fake_call_model(prompt, **kwargs):
            return {"confidence": "medium", "knowledge_gaps": [], "corrections": [
                {"option": "A", "field": "rationale", "action": "revise",
                 "corrected": "有依据的说明 [Source: Made Up Docs]", "reason": "fix"}]}

        monkeypatch.setattr(sr, "call_model", fake_call_model)
        out = asyncio.run(sr.SelfReviewerAgent().run(dict(state)))
        rationale = out["final_recommendation"]["ranked_options"][0]["rationale"]
        assert "有依据的说明" in rationale
        assert "[Source: Made Up Docs]" not in rationale
        assert "引用未解析" in rationale


@pytest.mark.skipif(not V6_SNAPSHOT.is_file(), reason="sixth-run snapshot not present")
class TestFixedMaterialReplay:
    """Replay the citation engine over the sixth run's saved snapshot.

    The original model output was not preserved, so this proves what the current
    engine does with the saved source registry and recommendation. It does not
    reproduce what the model wrote or deleted during that run.
    """

    def _snapshot(self):
        return json.loads(V6_SNAPSHOT.read_text(encoding="utf-8"))

    def test_the_saved_recommendation_is_idempotent_and_resolved(self):
        snap = self._snapshot()
        registry = cs.build_source_registry(snap.get("evidence_chains") or [])
        assert len(registry["entries"]) == 21
        before = copy.deepcopy(snap["final_recommendation"])
        after = cs.apply_citation_rules(copy.deepcopy(before),
                                        snap["evidence_chains"],
                                        registry["mapping"])
        # Re-applying the rules changes nothing: canonical titles stay canonical.
        again = cs.apply_citation_rules(copy.deepcopy(after),
                                        snap["evidence_chains"],
                                        registry["mapping"])
        assert after == again
        for (_loc, container, field) in cs.citation_field_locations(after):
            assert not cs.unresolved_citations(str(container[field]),
                                               registry=registry), field

    def test_the_unused_sensitive_data_source_would_bind_if_cited(self):
        """The sensitive-data source is in the saved material and the current
        engine registers it and can bind it by title and by number.

        What is NOT provable from the saved snapshot: whether the previous
        pipeline deleted a marker the model wrote, or whether the model wrote one
        at all. The original model output was not preserved. This test proves the
        resolution mechanism, not the history of that run's citations.
        """
        snap = self._snapshot()
        registry = cs.build_source_registry(snap.get("evidence_chains") or [])
        entry = next((e for e in registry["entries"]
                      if "处理敏感数据" in e["title"]), None)
        assert entry is not None, "fixture: the sensitive-data source is registered"
        finding = ("attribute 处理器可删/改/哈希指定属性，filter 丢弃整条 span "
                   "或指标，redaction 只保留白名单属性，transform 用正则改写")
        numbered = cs.resolve_text(f"{finding} [[{entry['number']}]]",
                                   registry=registry)
        literal = cs.resolve_text(f"{finding} [Source: {entry['title']}]",
                                  registry=registry)
        for resolved in (numbered, literal):
            assert f"[Source: {entry['title']}]" in resolved
            assert "引用未解析" not in resolved
        assert numbered == literal

    def _capture_payload(self, monkeypatch, state):
        captured = {}

        async def fake_call_model(prompt, **kwargs):
            captured["prompt"] = prompt
            return {"confidence": "medium", "knowledge_gaps": [], "corrections": []}

        monkeypatch.setattr(sr, "call_model", fake_call_model)
        asyncio.run(sr.SelfReviewerAgent().run(dict(state)))
        return captured["prompt"][1]["content"]

    def test_the_reviewer_payload_on_the_saved_run_carries_the_unused_source(
            self, monkeypatch):
        """The self-review input now holds the same numbered sources as synthesis,
        including the sensitive-data document the report did not cite, and the
        completeness list locates the uncited field."""
        payload = self._capture_payload(monkeypatch, self._snapshot())
        assert "[[10]] 处理敏感数据 | OpenTelemetry" in payload
        assert "handling-sensitive-data" in payload
        assert "attribute 处理器" in payload
        completeness = payload.split("## Citation Completeness")[1].split("##")[0]
        assert "敏感字段处理与排障能力/finding" in completeness
        assert "confidence_rationale" in completeness

    def test_a_revision_citing_the_available_source_reaches_the_report(
            self, monkeypatch):
        snap = self._snapshot()
        registry = cs.build_source_registry(snap.get("evidence_chains") or [])
        entry = next(e for e in registry["entries"] if "处理敏感数据" in e["title"])
        trade_off = next(t for t in snap["final_recommendation"]["trade_offs"]
                         if "敏感" in str(t.get("dimension", "")))

        async def fake_call_model(prompt, **kwargs):
            return {"confidence": "medium", "knowledge_gaps": [], "corrections": [{
                "option": trade_off["dimension"], "field": "finding",
                "action": "revise",
                "corrected": (f"attribute/filter/redaction/transform 处理器可在发送前"
                              f"处理敏感字段 [Source: {entry['title']}]"),
                "reason": "来源支持这一具体处理方式"}]}

        monkeypatch.setattr(sr, "call_model", fake_call_model)
        out = asyncio.run(sr.SelfReviewerAgent().run(dict(snap)))
        finding = next(t for t in out["final_recommendation"]["trade_offs"]
                       if "敏感" in str(t.get("dimension", "")))["finding"]
        assert f"[Source: {entry['title']}]" in finding
        assert "引用未解析" not in finding
        # The single re-rendered report is the served artifact.
        assert f"[Source: {entry['title']}]" in out["report"]
