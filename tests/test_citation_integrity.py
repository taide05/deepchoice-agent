"""Citation identity and self-review input contracts.

Fixed material: `tests/fixtures/sixth_run_minimal.json`, a tracked minimal
sanitized excerpt of the sixth run's saved material. It is used only to replay the
citation engine and the self-review input: the original model output was not
preserved, so these tests prove the mechanism, not what the model wrote then.
"""
import asyncio
import copy
import json
import pathlib

from deepchoice.agents import conclusion_synthesizer as cs
from deepchoice.agents import self_reviewer as sr
from deepchoice.formats import comparison_matrix, evidence_first, what_why_how
from deepchoice.formats.basis import used_sources
from deepchoice.formats.citations import inject_citations, number_sources

FIXTURE = (pathlib.Path(__file__).resolve().parent / "fixtures"
           / "sixth_run_minimal.json")

DOC_TITLE = "Shared Documentation Title"
PLAIN_TITLE = "Official Runtime Documentation"
SENTINEL = "ZV8SENTINEL"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _chains(*sources: dict) -> list[dict]:
    return [{"sources": list(sources)}]


def _source(title: str, body: str = "a real body", url: str = "") -> dict:
    entry = {"title": title, "snippet": body}
    if url:
        entry["url"] = url
    return entry


def _registry(*sources: dict) -> dict:
    return cs.build_source_registry(_chains(*sources))


def _duplicate_title_chains() -> list[dict]:
    return _chains(_source(DOC_TITLE, "body of A", "https://a.example/doc"),
                   _source(DOC_TITLE, "body of B", "https://b.example/doc"))


def _state(rec: dict, chains: list[dict], query: str = "测试问题",
           candidates: list[str] | None = None) -> dict:
    return {
        "task": {"query": query,
                 "candidate_techs": candidates or ["A"],
                 "report_format": "what_why_how"},
        "evidence_chains": chains,
        "conflicts": [],
        "conflict_check": {"pairs_scanned": 1, "pairs_arbitrated": 0,
                           "pairs_evidence": 0,
                           "scan_outcomes": {"difference": 0, "no_difference": 1,
                                             "unscanned": 0},
                           "reason": "test fixture"},
        "knowledge_gaps": [],
        "confidence": rec.get("confidence", "medium"),
        "final_recommendation": rec,
    }


def _valid_review(review: dict) -> dict:
    """Attach strict 6/6 accounting to ordinary test reviews."""
    if not isinstance(review, dict) or "checks" in review:
        return review
    review = dict(review)
    passed = review.get("passed_count", 5)
    try:
        passed = min(max(int(passed), 0), 6)
    except (TypeError, ValueError):
        passed = 5
    review["checks"] = [
        {"item": index, "passed": index <= passed, "note": "test"}
        for index in range(1, 7)
    ]
    review["passed_count"] = passed
    return review


def _capture_review(monkeypatch, state: dict, review: dict | None = None) -> str:
    captured = {}

    async def fake_call_model(prompt, **kwargs):
        captured["prompt"] = prompt
        return _valid_review(review or {"confidence": "medium", "knowledge_gaps": [],
                                        "corrections": []})

    monkeypatch.setattr(sr, "call_model", fake_call_model)
    asyncio.run(sr.SelfReviewerAgent().run(dict(state)))
    return captured["prompt"][1]["content"]


def _run_review(monkeypatch, state: dict, review: dict):
    async def fake_call_model(prompt, **kwargs):
        return _valid_review(review)

    monkeypatch.setattr(sr, "call_model", fake_call_model)
    return asyncio.run(sr.SelfReviewerAgent().run(dict(state)))


def _field_section(payload: str, locator: str) -> str:
    """The review-body section for one field locator."""
    marker = f"### {locator}\n"
    start = payload.index(marker) + len(marker)
    rest = payload[start:]
    ends = [pos for pos in (rest.find("\n### "), rest.find("\n## ")) if pos != -1]
    return rest[:min(ends)] if ends else rest


def _conflicts_section(payload: str) -> str:
    rest = payload.split("## Recorded Conflicts", 1)[1]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


class TestRegisteredIdentity:
    """A resolved citation keeps the registered source identity, independent of
    the display title, through the report, its source list, field Sources lines,
    the annotated view and export renderers."""

    def test_the_second_of_two_same_titled_sources_keeps_its_identity(self):
        chains = _duplicate_title_chains()
        rec = {"recommendation": "Only the second source supports this [[2]]."}
        cs.apply_citation_rules(rec, chains)
        bindings = rec[cs.CITATION_SOURCES_KEY]["recommendation"]
        assert [binding["url"] for binding in bindings] == ["https://b.example/doc"]
        assert [src["url"] for src in used_sources(rec, chains)] == \
            ["https://b.example/doc"]
        report = what_why_how.render(_state(rec, chains))
        assert "https://b.example/doc" in report
        assert "https://a.example/doc" not in report

    def test_citing_both_same_titled_sources_keeps_both_identities(self):
        chains = _duplicate_title_chains()
        rec = {"recommendation": "Both are relevant [[1]] and [[2]]."}
        cs.apply_citation_rules(rec, chains)
        bindings = rec[cs.CITATION_SOURCES_KEY]["recommendation"]
        assert [binding["url"] for binding in bindings] == [
            "https://a.example/doc", "https://b.example/doc"]
        used = used_sources(rec, chains)
        assert [src["url"] for src in used] == [
            "https://a.example/doc", "https://b.example/doc"]
        for renderer in (what_why_how.render, comparison_matrix.render,
                         evidence_first.render):
            out = renderer(_state(rec, chains))
            assert "https://a.example/doc" in out, renderer.__module__
            assert "https://b.example/doc" in out, renderer.__module__

    def test_field_sources_and_annotated_view_use_the_registered_url(self):
        chains = _duplicate_title_chains()
        rec = {"recommendation": "Context.",
               "ranked_options": [{"name": "A", "rank": 1,
                                   "rationale": "Second source only [[2]]."}]}
        cs.apply_citation_rules(rec, chains)
        report = what_why_how.render(_state(rec, chains))
        sources_line = next(line for line in report.splitlines()
                            if "*Sources:" in line)
        assert "https://b.example/doc" in sources_line
        assert "https://a.example/doc" not in sources_line
        # The annotated view numbers the same links the renderer emitted.
        annotated = inject_citations(report, number_sources(chains))
        assert 'href="#ev-2"' in annotated, annotated[-800:]
        assert "https://a.example/doc" not in annotated

    def test_a_literal_same_title_citation_is_still_a_gap(self):
        chains = _duplicate_title_chains()
        rec = {"recommendation": f"A claim [Source: {DOC_TITLE}]."}
        cs.apply_citation_rules(rec, chains)
        assert "引用未解析" in rec["recommendation"] or \
            "citation-unresolved" in rec["recommendation"]
        assert cs.CITATION_SOURCES_KEY in rec
        assert rec[cs.CITATION_SOURCES_KEY] == {}
        assert used_sources(rec, chains) == []

    def test_a_body_less_source_cannot_be_cited(self):
        nav = {"title": "Navigation Only", "url": "https://nav.example/x",
               "snippet": "", "has_body": False}
        chains = _chains(_source(PLAIN_TITLE, "body", "https://real.example/x"), nav)
        registry = cs.build_source_registry(chains)
        assert [entry["title"] for entry in registry["entries"]] == [PLAIN_TITLE]
        rec = {"recommendation": "A claim [Source: Navigation Only]."}
        cs.apply_citation_rules(rec, chains)
        assert "[Source: Navigation Only]" not in rec["recommendation"]
        assert used_sources(rec, chains) == []

    def test_legacy_material_never_picks_one_of_two_same_titled_sources(self):
        chains = _duplicate_title_chains()
        # No identity map: this is historical material, parsed by title only.
        rec = {"recommendation": f"A claim [Source: {DOC_TITLE}]."}
        assert used_sources(rec, chains) == []
        report = what_why_how.render(_state(rec, chains))
        assert "https://a.example/doc" not in report
        assert "https://b.example/doc" not in report

    def test_legacy_material_still_resolves_an_unambiguous_title(self):
        chains = _chains(_source(PLAIN_TITLE, "body", "https://unique.example/x"))
        rec = {"recommendation": f"A claim [Source: {PLAIN_TITLE}]."}
        used = used_sources(rec, chains)
        assert [src["url"] for src in used] == ["https://unique.example/x"]
        report = what_why_how.render(_state(rec, chains))
        assert "https://unique.example/x" in report

    def test_basis_keeps_cited_source_that_names_no_candidate(self):
        """The reference ledger mirrors visible citations.

        Relevance filtering happens when the citation is created, not when the
        report is rendered: hiding a source here would make the body and
        reference counts disagree.
        """
        relevant = _source("Jaeger Features", "Jaeger tracing backend",
                           "https://jaeger.example/features")
        irrelevant = _source("Bitcoin self-custody news", "crypto markets",
                             "https://news.example/btc")
        chains = _chains(relevant, irrelevant)
        rec = {
            "recommendation": ("Use Jaeger [Source: Jaeger Features]. "
                               "Context [Source: Bitcoin self-custody news]."),
            "ranked_options": [{"name": "Jaeger", "rank": 1},
                               {"name": "Zipkin", "rank": 2}],
        }
        cs.apply_citation_rules(rec, chains)
        used = used_sources(rec, chains)
        assert {src["url"] for src in used} == {
            "https://jaeger.example/features", "https://news.example/btc"}
        report = what_why_how.render(_state(rec, chains,
                                            candidates=["Jaeger", "Zipkin"]))
        assert "https://jaeger.example/features" in report
        assert "https://news.example/btc" in report

    def test_a_partial_identity_map_does_not_hide_legacy_fields(self):
        """A record revised later has identities only for revised fields; the
        untouched fields must still contribute their unique cited sources."""
        unique = _source("Unique Doc", "body", "https://unique.example/x")
        chains = _chains(_source(DOC_TITLE, "A", "https://a.example/doc"),
                         _source(DOC_TITLE, "B", "https://b.example/doc"),
                         unique)
        rec = {"recommendation": "new identity [[2]]"}
        cs.apply_citation_rules(rec, chains)
        rec["winner_rationale"] = "legacy text [Source: Unique Doc]"
        used_urls = [src["url"] for src in used_sources(rec, chains)]
        assert "https://b.example/doc" in used_urls
        assert "https://unique.example/x" in used_urls
        coverage = sr._citation_coverage(rec, chains)
        assert "winner_rationale" not in coverage["uncited_locations"]
        report = what_why_how.render(_state(rec, chains))
        assert "https://b.example/doc" in report
        assert "https://unique.example/x" in report

    def test_a_double_bracketed_source_marker_is_resolved_not_left_raw(self):
        registry = _registry(_source(PLAIN_TITLE, "body", "https://x"))
        resolved = cs.resolve_text(f"X [[Source: {PLAIN_TITLE}]] Y",
                                   registry=registry)
        assert f"[Source: {PLAIN_TITLE}]" in resolved
        assert "[[" not in resolved
        assert not cs.unresolved_citations(resolved, registry=registry)
        unknown = cs.resolve_text("X [[Source: Made Up Docs]] Y", registry=registry)
        assert "[[Source:" not in unknown
        assert "引用未解析" in unknown or "citation-unresolved" in unknown

    def test_a_reviewer_revision_carries_identity_into_the_report(self, monkeypatch):
        chains = _duplicate_title_chains()
        rec = {"recommendation": "R",
               "ranked_options": [{"name": "A", "rank": 1, "rationale": "old"}]}
        state = _state(rec, chains)
        review = {"confidence": "medium", "knowledge_gaps": [], "corrections": [{
            "option": "A", "field": "rationale", "action": "revise",
            "corrected": "revised with the second source [[2]]", "reason": "fix"}]}
        out = _run_review(monkeypatch, state, review)
        revised = out["final_recommendation"]["ranked_options"][0]["rationale"]
        bindings = out["final_recommendation"][cs.CITATION_SOURCES_KEY][
            "option=A/rationale"]
        assert [binding["url"] for binding in bindings] == ["https://b.example/doc"]
        registry = cs.build_source_registry(chains)
        expected_title = next(entry["title"] for entry in registry["entries"]
                              if entry["url"] == "https://b.example/doc")
        assert f"[Source: {expected_title}]" in revised
        assert "https://b.example/doc" in out["report"]


class TestAdjacentAndRepeatedCitations:
    def test_space_separated_citations_after_a_word_are_not_indexes(self):
        chains = _duplicate_title_chains()
        rec = {"recommendation": "sources [[1]] [[2]] words"}
        cs.apply_citation_rules(rec, chains)
        bindings = rec[cs.CITATION_SOURCES_KEY]["recommendation"]
        assert [binding["url"] for binding in bindings] == [
            "https://a.example/doc", "https://b.example/doc"]
        assert "引用未解析" not in rec["recommendation"]

    def test_adjacent_citations_without_space_are_not_indexes(self):
        chains = _duplicate_title_chains()
        rec = {"recommendation": "text [[1]][[2]]"}
        cs.apply_citation_rules(rec, chains)
        bindings = rec[cs.CITATION_SOURCES_KEY]["recommendation"]
        assert [binding["url"] for binding in bindings] == [
            "https://a.example/doc", "https://b.example/doc"]

    def test_repeating_the_same_citation_is_collapsed_not_a_gap(self):
        chains = _chains(_source(PLAIN_TITLE, "body", "https://x"))
        for text in (f"x [[1]] [[1]] y",
                     f"x [Source: {PLAIN_TITLE}] [Source: {PLAIN_TITLE}] y"):
            resolved = cs.resolve_text(text, registry=cs.build_source_registry(chains))
            assert resolved.count(f"[Source: {PLAIN_TITLE}]") == 1, (text, resolved)
            assert "引用未解析" not in resolved, (text, resolved)

    def test_the_same_registered_source_twice_is_not_a_gap(self):
        # The same page registered by two chains: one identity, not ambiguity.
        chains = _chains(_source(PLAIN_TITLE, "body", "https://x"),
                         _source(PLAIN_TITLE, "body", "https://x"))
        registry = cs.build_source_registry(chains)
        assert cs.resolve_text(f"[Source: {PLAIN_TITLE}]", registry=registry) == \
            f"[Source: {PLAIN_TITLE}]"
        assert not cs.unresolved_citations(f"[Source: {PLAIN_TITLE}]",
                                           registry=registry)

    def test_duplicate_titles_are_disambiguated_for_current_sources(self):
        # Generic titles repeated across pages are common on official doc sites.
        # The current registry must expose a unique title per identity so a
        # written citation resolves instead of becoming a visible unresolved gap.
        chains = _chains(
            _source(DOC_TITLE, "A", "https://docs.example/a/upgrade"),
            _source(DOC_TITLE, "B", "https://docs.example/b/performance"),
        )
        registry = cs.build_source_registry(chains)
        titles = [entry["title"] for entry in registry["entries"]]
        assert len(titles) == len(set(titles))
        for title in titles:
            resolved = cs.resolve_text(f"[Source: {title}]", registry=registry)
            assert "引用未解析" not in resolved, (title, resolved)

    def test_arrays_intervals_unknown_and_ambiguous_keep_their_boundary(self):
        registry = _registry(_source(PLAIN_TITLE, "body", "https://x"))
        for text in ("the interval [[0,1]] is normalized",
                     "matrix [[1, 2]] entry",
                     "code: arr[[1,2]] = x",
                     "x[[1]]y[[2]]z",
                     "row[[2,3]][0]",
                     "见 [[附录]] 说明"):
            assert cs.resolve_text(text, registry=registry) == text, text
            assert not cs.unresolved_citations(text, registry=registry), text
        # Unknown numbers and ambiguous literal titles remain unresolved.
        assert cs.unresolved_citations("[[99]]", registry=registry)
        ambiguous = _registry(_source(DOC_TITLE, "A", "https://a"),
                              _source(DOC_TITLE, "B", "https://b"))
        assert cs.unresolved_citations(f"[Source: {DOC_TITLE}]",
                                       registry=ambiguous)


class TestSelfReviewInput:
    def _full_recommendation(self) -> dict:
        return {
            "winner": "A",
            "recommendation": f"{SENTINEL}-recommendation",
            "winner_rationale": f"{SENTINEL}-winner-rationale",
            "confidence": "medium",
            "confidence_rationale": f"{SENTINEL}-confidence-rationale",
            "evidence_summary": f"{SENTINEL}-evidence-summary",
            "scene_fit_note": f"{SENTINEL}-scene-fit",
            "ranked_options": [{
                "name": "A", "rank": 1,
                "rationale": f"{SENTINEL}-rationale",
                "key_strength": f"{SENTINEL}-key-strength",
                "key_weakness": f"{SENTINEL}-key-weakness",
                "constraint_fit_reason": f"{SENTINEL}-constraint-fit-reason",
            }],
            "trade_offs": [{
                "dimension": "dimension-one",
                "finding": f"{SENTINEL}-finding",
                "impact": f"{SENTINEL}-impact",
            }],
            "unresolved_questions": [f"{SENTINEL}-open-question"],
        }

    def _full_state(self) -> dict:
        chains = _chains(_source(PLAIN_TITLE, "body", "https://x"))
        state = _state(self._full_recommendation(), chains)
        state["sub_questions"] = ["real sub-question one?"]
        state["knowledge_gaps"] = ["recorded gap one"]
        return state

    def _all_field_values(self, rec: dict) -> list[str]:
        values = []
        for locator, container, field in cs.citation_field_locations(rec):
            values.append(str(container.get(field)))
        return values

    def test_the_review_body_carries_every_correctable_field_once(
            self, monkeypatch):
        state = self._full_state()
        payload = _capture_review(monkeypatch, state)
        values = self._all_field_values(state["final_recommendation"])
        assert len(values) == 11
        for value in values:
            assert payload.count(value) == 1, value
        assert "real sub-question one?" in payload
        assert "recorded gap one" in payload
        assert "## Fields To Review" in payload
        # The review body is the located fields, not a second copy of the report.
        assert "## What:" not in payload
        assert "### References" not in payload

    def test_review_coverage_does_not_depend_on_the_report_format(
            self, monkeypatch):
        state = self._full_state()
        payload = _capture_review(monkeypatch, state)
        rendered_values: set[str] = set()
        renderers = (what_why_how.render, comparison_matrix.render,
                     evidence_first.render)
        for renderer in renderers:
            rendered = renderer(_state(self._full_recommendation(),
                                       state["evidence_chains"]))
            rendered_values |= {value for value in
                                self._all_field_values(
                                    self._full_recommendation())
                                if value in rendered}
        assert rendered_values, "fixture: renderers printed no correctable field"
        # Every field any format prints is reviewed, and the fields no format
        # prints are reviewed too: coverage is format-independent.
        assert rendered_values <= {value for value in payload.split()
                                   if SENTINEL in value}
        assert all(value in payload for value in self._all_field_values(
            self._full_recommendation()))

    def test_the_review_payload_keeps_real_question_context(self, monkeypatch):
        state = self._full_state()
        state["task"]["query"] = "ORIGINAL-QUERY-SENTINEL"
        state["task"]["scene_context"] = "SCENE-CONTEXT-SENTINEL"
        state["conflicts"] = [{"resolution": "unresolved",
                               "reasoning": "CONFLICT-REASONING-SENTINEL",
                               "key_factor": "CONFLICT-FACTOR-SENTINEL"}]
        payload = _capture_review(monkeypatch, state)
        assert "ORIGINAL-QUERY-SENTINEL" in payload
        assert "SCENE-CONTEXT-SENTINEL" in payload
        assert "CONFLICT-REASONING-SENTINEL" in payload
        assert "CONFLICT-FACTOR-SENTINEL" in payload
        assert "## Original Query" in payload
        assert "## Scene Context" in payload
        assert "## Recorded Conflicts" in payload

    def test_bound_sources_distinguish_same_titled_citations(self, monkeypatch):
        """Two fields cite the same display title but different registered
        sources; the review input must show each field's actual bound identity,
        not one title guessed into a source."""
        chains = _duplicate_title_chains()
        rec = {"recommendation": "first [[1]]", "winner_rationale": "second [[2]]"}
        cs.apply_citation_rules(rec, chains)
        payload = _capture_review(monkeypatch, _state(rec, chains))
        recommendation = _field_section(payload, "recommendation")
        rationale = _field_section(payload, "winner_rationale")
        assert "[[1]]" in recommendation
        assert "https://a.example/doc" in recommendation
        assert "https://b.example/doc" not in recommendation
        assert "[[2]]" in rationale
        assert "https://b.example/doc" in rationale
        assert "https://a.example/doc" not in rationale
        # Field bodies are supplied once; source bodies once (in the register).
        assert payload.count("body of A") == 1
        assert payload.count("body of B") == 1

    def _conflict_state(self, resolution: str, claim_a: str, claim_b: str) -> dict:
        chains = _duplicate_title_chains()
        state = _state({"recommendation": "R"}, chains)
        state["conflicts"] = [{
            "claim_a": claim_a,
            "claim_b": claim_b,
            "source_a": {"url": "https://a.example/doc"},
            "source_b": {"url": "https://unregistered.example/x"},
            "resolution": resolution,
            "confidence": "high",
            "reasoning": f"REASON-{resolution}",
            "key_factor": f"FACTOR-{resolution}",
        }]
        return state

    def test_conflict_claims_and_sides_are_locatable(self, monkeypatch):
        payload = _capture_review(
            monkeypatch,
            self._conflict_state("A_correct", "CLAIM-A-ONE", "CLAIM-B-ONE"))
        section = _conflicts_section(payload)
        assert "Claim A: CLAIM-A-ONE" in section
        assert "Claim B: CLAIM-B-ONE" in section
        assert "resolution: A_correct" in section
        # Both sides keep a locatable identity: a registered number for the
        # known source, an explicit unregistered URL for the other.
        registry = cs.build_source_registry(_duplicate_title_chains())
        expected_title = next(entry["title"] for entry in registry["entries"]
                              if entry["url"] == "https://a.example/doc")
        assert f"[[1]] {expected_title} — https://a.example/doc" in section
        assert "https://unregistered.example/x (not in numbered source register)" \
            in section
        assert "REASON-A_correct" in section
        assert "FACTOR-A_correct" in section

    def test_a_changed_conflict_side_changes_the_review_input(self, monkeypatch):
        first = _capture_review(
            monkeypatch,
            self._conflict_state("A_correct", "CLAIM-A-ONE", "CLAIM-B-ONE"))
        second = _capture_review(
            monkeypatch,
            self._conflict_state("B_correct", "CLAIM-A-TWO", "CLAIM-B-TWO"))
        first_section = _conflicts_section(first)
        second_section = _conflicts_section(second)
        assert "resolution: A_correct" in first_section
        assert "resolution: B_correct" in second_section
        assert "CLAIM-A-ONE" in first_section and "CLAIM-A-ONE" not in second_section
        assert "CLAIM-B-TWO" in second_section and "CLAIM-B-TWO" not in first_section
        assert "REASON-A_correct" in first_section
        assert "REASON-B_correct" in second_section

    def test_self_review_uses_one_model_call_when_contract_valid(self, monkeypatch):
        calls = {"n": 0}

        async def fake_call_model(prompt, **kwargs):
            calls["n"] += 1
            return {"confidence": "medium", "knowledge_gaps": [], "corrections": [],
                    "checks": [{"item": i, "passed": i <= 3, "note": "t"}
                               for i in range(1, 7)],
                    "passed_count": 3}

        monkeypatch.setattr(sr, "call_model", fake_call_model)
        out = asyncio.run(sr.SelfReviewerAgent().run(dict(self._full_state())))
        assert calls["n"] == 1
        assert out["quality_signals"][0]["review_attempts"] == 1

    def test_self_review_gets_one_repair_attempt_on_contract_violation(self, monkeypatch):
        """A contract violation is a pipeline-quality defect (final-200 review:
        15/200 runs), so exactly one structured repair call is allowed; the
        malformed payload itself is still never applied."""
        calls = {"n": 0}

        async def fake_call_model(prompt, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"confidence": "medium", "knowledge_gaps": [],
                        "corrections": []}
            return {"confidence": "medium", "knowledge_gaps": [], "corrections": [],
                    "checks": [{"item": i, "passed": i <= 3, "note": "t"}
                               for i in range(1, 7)],
                    "passed_count": 3}

        monkeypatch.setattr(sr, "call_model", fake_call_model)
        out = asyncio.run(sr.SelfReviewerAgent().run(dict(self._full_state())))
        assert calls["n"] == 2
        signal = out["quality_signals"][0]
        assert signal["review_attempts"] == 2
        assert signal["review_status"] == "completed"

    def test_bound_source_wording_handles_historical_and_partial_maps(self):
        chains = _duplicate_title_chains()
        historical = sr._review_fields_text(
            {"recommendation": f"claim [Source: {PLAIN_TITLE}]"})
        assert "historical material" in historical
        partial = {"recommendation": "first [[2]]"}
        cs.apply_citation_rules(partial, chains)
        partial["winner_rationale"] = f"legacy [Source: {PLAIN_TITLE}]"
        fields = sr._review_fields_text(partial)
        assert "title-inspected for completeness only" in fields
        uncited = {"recommendation": "claim without markers"}
        cs.apply_citation_rules(uncited, chains)
        assert "none recorded for this field" in sr._review_fields_text(uncited)

    def test_conflict_source_identity_uses_url_not_title(self):
        registry = cs.build_source_registry(_duplicate_title_chains())
        expected_title = next(entry["title"] for entry in registry["entries"]
                              if entry["url"] == "https://a.example/doc")
        identity = sr._conflict_source_identity
        # A registered URL wins even when the recorded title differs.
        assert identity({"title": "Different Title",
                         "url": "https://a.example/doc"}, registry) == \
            f"[[1]] {expected_title} — https://a.example/doc"
        # An unregistered URL is explicit, never forced onto a same-titled page.
        assert identity({"title": "Unknown", "url": "https://nope.example/x"},
                        registry) == \
            "Unknown — https://nope.example/x (not in numbered source register)"
        assert identity({"url": "https://nope.example/x", "has_body": False},
                        registry) == \
            ("https://nope.example/x (not in numbered source register) "
             "(no body collected; not citable)")
        assert identity({"title": "Only Title"}, registry) == \
            "Only Title (not in numbered source register; no URL)"
        assert identity(None, registry) == "source not recorded"

    def test_completeness_lists_the_same_field_locations(self, monkeypatch):
        state = self._full_state()
        payload = _capture_review(monkeypatch, state)
        completeness = payload.split("## Citation Completeness")[1].split("##")[0]
        registry = cs.build_source_registry(state["evidence_chains"])
        coverage = sr._citation_coverage(state["final_recommendation"],
                                         registry=registry)
        for locator in (coverage["uncited_locations"]
                        + coverage["unresolved_locations"]):
            assert locator in completeness, locator
        for locator, _container, _field in cs.citation_field_locations(
                state["final_recommendation"]):
            assert f"### {locator}" in payload, locator
        assert "option=A/constraint_fit_reason" in completeness
        assert "trade-off=dimension-one/impact" in completeness

    def test_the_reviewer_gets_the_same_numbered_sources_from_fixed_material(
            self, monkeypatch):
        fixture = _fixture()
        payload = _capture_review(monkeypatch, fixture)
        assert "[[1]] 处理敏感数据 | OpenTelemetry" in payload
        assert "https://opentelemetry.io/zh/docs/security/handling-sensitive-data" \
            in payload
        assert "`attribute` 处理器" in payload
        completeness = payload.split("## Citation Completeness")[1].split("##")[0]
        assert "trade-off=敏感字段处理与排障能力/finding" in completeness
        prompt = sr.REVIEW_SYSTEM.lower()
        assert "not proof" in prompt or "not a proof" in prompt
        assert "pre-computed" not in prompt
        assert "do not re-evaluate" not in prompt

    def test_the_correction_contract_names_the_sections_it_actually_gets(self):
        contract = sr.REVIEW_SYSTEM
        assert "Decision Claims To Check" not in contract
        assert "Revision Targets" not in contract
        assert "Fields To Review" in contract
        assert "Each is printed in the report" not in contract
        assert "not printed by this report format" not in contract

    def test_a_revision_citing_the_available_source_reaches_the_report(
            self, monkeypatch):
        fixture = _fixture()
        trade_off = next(t for t in fixture["final_recommendation"]["trade_offs"]
                         if "敏感" in str(t.get("dimension", "")))
        review = {"confidence": "medium", "knowledge_gaps": [], "corrections": [{
            "option": trade_off["dimension"], "field": "finding",
            "action": "revise",
            "corrected": ("attribute/filter/redaction/transform 处理器可在发送前处理敏感字段 "
                          "[Source: 处理敏感数据 | OpenTelemetry]"),
            "reason": "来源支持这一具体处理方式"}]}
        out = _run_review(monkeypatch, fixture, review)
        finding = next(t for t in out["final_recommendation"]["trade_offs"]
                       if "敏感" in str(t.get("dimension", "")))["finding"]
        assert "[Source: 处理敏感数据 | OpenTelemetry]" in finding
        assert "引用未解析" not in finding
        locator = next(key for key in
                       out["final_recommendation"][cs.CITATION_SOURCES_KEY]
                       if "敏感" in key and key.endswith("/finding"))
        binding = out["final_recommendation"][cs.CITATION_SOURCES_KEY][locator][0]
        assert binding["url"] == \
            "https://opentelemetry.io/zh/docs/security/handling-sensitive-data"
        assert f"[Source: 处理敏感数据 | OpenTelemetry]" in out["report"]
        used = used_sources(out["final_recommendation"],
                            fixture["evidence_chains"])
        assert any(src["url"] == binding["url"] for src in used)


class TestFixedMaterialReplay:
    """Replay the current engine over the tracked minimal sixth-run fixture.

    The original model output was not preserved. These tests prove what the
    current code does with the saved material; they do not reproduce what the
    model wrote or which markers the previous pipeline deleted.
    """

    def test_the_saved_recommendation_replays_idempotently(self):
        fixture = _fixture()
        registry = cs.build_source_registry(fixture["evidence_chains"])
        assert len(registry["entries"]) == 6
        assert registry["entries"][0]["title"] == "处理敏感数据 | OpenTelemetry"
        rec = copy.deepcopy(fixture["final_recommendation"])
        cs.apply_citation_rules(rec, fixture["evidence_chains"])
        again = copy.deepcopy(rec)
        cs.apply_citation_rules(again, fixture["evidence_chains"])
        assert rec == again, "the citation pass is not idempotent on saved material"
        identity_map = rec[cs.CITATION_SOURCES_KEY]
        assert len(identity_map) == 10
        cited_numbers = {binding["number"] for bindings in identity_map.values()
                         for binding in bindings}
        # The sensitive-data source was retrieved and is registered, but the
        # saved report never cited it; its trade-off finding is the replay target.
        assert 1 not in cited_numbers
        sensitive_key = "trade-off=敏感字段处理与排障能力/finding"
        assert sensitive_key not in identity_map

    def test_the_available_sensitive_source_would_bind_if_cited(self):
        fixture = _fixture()
        registry = cs.build_source_registry(fixture["evidence_chains"])
        entry = registry["entries"][0]
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

    def test_the_fixture_is_minimal_and_sanitized(self):
        fixture = _fixture()
        assert fixture["fixture_version"] == "sixth-run-minimal-v1"
        assert "fixture_note" in fixture
        blob = json.dumps(fixture, ensure_ascii=False)
        assert "task_id" not in fixture
        assert "run_limits" not in blob
        assert "token_usage" not in blob
        assert "D:\\\\" not in blob
        assert len(fixture["evidence_chains"]) == 6

class TestAttachedProseCitations:
    def test_citation_attached_to_word_ending_in_punctuation_resolves(self):
        chains = _duplicate_title_chains()
        rec = {"recommendation": "text Pydantic v2[[1]]。next"}
        cs.apply_citation_rules(rec, chains)
        assert "[[1]]" not in rec["recommendation"]
        assert "引用未解析" not in rec["recommendation"]
        assert rec[cs.CITATION_SOURCES_KEY]["recommendation"]

    def test_citation_attached_to_word_at_field_end_resolves(self):
        chains = _duplicate_title_chains()
        rec = {"recommendation": "text Pydantic v2[[1]]"}
        cs.apply_citation_rules(rec, chains)
        assert "[[1]]" not in rec["recommendation"]
        assert "引用未解析" not in rec["recommendation"]

    def test_citation_after_source_bracket_resolves(self):
        chains = _duplicate_title_chains()
        registry = cs.build_source_registry(chains)
        text = "claim [Source: A] [[1]]"
        resolved = cs.resolve_text(text, registry=registry)
        assert "[[1]]" not in resolved
        assert "引用未解析" not in resolved

class TestFreeTextCitationCleanup:
    def test_unresolved_questions_raw_markers_are_resolved(self):
        chains = _duplicate_title_chains()
        rec = {"unresolved_questions": ["子问题：v2[[1]]", "另一问：[[2]]。"]}
        cs.apply_citation_rules(rec, chains)
        joined = " ".join(rec["unresolved_questions"])
        assert "[[1]]" not in joined and "[[2]]" not in joined
        assert "引用未解析" not in joined
        assert "Source:" in joined

class TestCitationSafeTitles:
    def test_bracketed_source_title_does_not_break_source_marker(self):
        chains = _chains(_source("PDF [2026] guide", "body", "https://example.com/pdf"))
        registry = cs.build_source_registry(chains)
        tit = registry["entries"][0]["title"]
        assert "[" not in tit and "］" in tit
        rec = {"recommendation": f"claim [Source: {tit}]"}
        cs.apply_citation_rules(rec, chains)
        assert "引用未解析" not in rec["recommendation"]
        assert "Source:" in rec["recommendation"]
