"""Candidate identity: declared candidates reach synthesis and the report.

The failure these protect against: the official retriever matched the adapted
query's ordinary words, so the term "vector" pulled in vector.dev — a log
pipeline — which was then cited as pgvector's official basis; synthesis received
only titles and scores, so no source content could contradict it; and the What
section was gated on a strong chain, so with none it rendered empty and the
reader never saw the candidates.

The bound is structural, not a term list: only task.candidate_techs may introduce
an official source.
"""
from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

from deepchoice.agents.conclusion_synthesizer import _summarize_chains
from deepchoice.formats.what_why_how import _cited_sources, render
from deepchoice.retrievers.official import TECH_DOCS, OfficialSearch
from deepchoice.utils.candidate_identity import (
    UNASSIGNED,
    bounded_content_summary,
    candidate_for_source,
    candidate_tokens,
    has_factual_content,
    index_sources_by_candidate,
    mapping_key_for,
    split_navigation_label,
)

FAILED_RUN = (pathlib.Path(r"D:\deepchoice-precodex\outputs")
              / "e3b1c837-d2e1-46a1-b77c-c46eefe41dea" / "research_snapshot.json")


def _failed_run_state() -> dict:
    """The real failed-run material, preserved unedited."""
    if not FAILED_RUN.exists():
        pytest.skip(f"failed-run snapshot not present at {FAILED_RUN}")
    return json.loads(FAILED_RUN.read_text(encoding="utf-8"))


class TestOrdinaryWordsDoNotIntroduceProducts:
    def test_vector_is_not_a_candidate_token(self):
        tokens = candidate_tokens(["pgvector on Amazon RDS for PostgreSQL"])
        assert "vector" not in tokens
        assert "pgvector" in tokens

    def test_unrelated_product_is_not_named_by_these_candidates(self):
        keys = set(mapping_key_for(
            ["pgvector on Amazon RDS for PostgreSQL", "Pinecone"], TECH_DOCS))
        assert "vector" not in keys, "an ordinary word named an out-of-list product"
        assert "postgresql" in keys, "a candidate's own name must still resolve"

    @pytest.mark.asyncio
    async def test_adapted_query_words_cannot_add_official_sources(self):
        """Ordinary search words must not become research targets."""
        search = OfficialSearch()
        out = await search._do_search(
            "which vector store", [], 7,
            adapted_queries=["vector database comparison", "semantic search latency"],
            candidate_techs=["pgvector on Amazon RDS for PostgreSQL", "Pinecone"],
        )
        urls = [r["url"] for r in out]
        assert not any("vector.dev" in u for u in urls), urls
        assert any("postgresql.org" in u for u in urls), urls

    @pytest.mark.asyncio
    async def test_no_declared_candidate_yields_no_official_source(self):
        search = OfficialSearch()
        out = await search._do_search(
            "which vector store", [], 7,
            adapted_queries=["vector database"], candidate_techs=[])
        assert out == []


class TestNavigationCaptionIsNotEvidence:
    def test_caption_is_recognised(self):
        content, navigation_only = split_navigation_label(
            "Official documentation site for vector")
        assert navigation_only is True
        assert content == ""

    def test_caption_becomes_a_stated_gap(self):
        summary = bounded_content_summary({
            "title": "vector — Official Documentation",
            "snippet": "Official documentation site for vector",
            "url": "https://vector.dev/docs/",
        })
        assert "NO CONTENT RETRIEVED" in summary

    def test_real_body_is_preserved(self):
        summary = bounded_content_summary({
            "title": "Postgres With pgvector vs Pinecone",
            "snippet": "The HNSW deep-dive reports sub-20ms for top-10 queries on 1M.",
        })
        assert "sub-20ms" in summary
        assert "NO CONTENT" not in summary


class TestSynthesisInput:
    def test_candidates_urls_and_content_all_reach_the_prompt(self):
        state = _failed_run_state()
        candidates = state["task"]["candidate_techs"]
        text, _ = _summarize_chains(state.get("evidence_chains", []), candidates)

        for candidate in candidates:
            assert candidate in text, f"{candidate} missing from the synthesis prompt"
        assert "url: http" in text, "source URLs did not reach synthesis"
        assert "content:" in text, "bounded content did not reach synthesis"

    def test_title_and_score_alone_is_no_longer_the_source_record(self):
        text, _ = _summarize_chains(
            [{"conclusion": "c", "evidence_strength": "moderate",
              "sources": [{"title": "T", "url": "https://x", "score": 7.0,
                           "snippet": "body text here"}]}], ["Candidate"])
        assert "url: https://x" in text
        assert "body text here" in text


class TestWhatRendersCandidates:
    def test_all_candidates_render_even_with_zero_strong_chains(self):
        state = _failed_run_state()
        chains = state.get("evidence_chains", [])
        assert not [c for c in chains if c.get("evidence_strength") == "strong"], \
            "this fixture is meant to exercise the zero-strong case"
        report = render(state)
        what = report.split("## Why")[0]
        for candidate in state["task"]["candidate_techs"]:
            assert candidate in what, f"{candidate} missing from What"

    def test_candidate_without_material_states_the_gap(self):
        state = {
            "task": {"query": "X vs Y", "candidate_techs": ["Totally Unretrieved Thing"]},
            "evidence_chains": [], "conflicts": [], "knowledge_gaps": [],
            "final_recommendation": {}, "confidence": "low",
        }
        what = render(state).split("## Why")[0]
        assert "Totally Unretrieved Thing" in what
        assert "No retrieved material" in what or "未取得明确指向" in what


class TestNavigationLinksAreNotCitable:
    """A discovered link with no body is navigation, not evidence.

    It stays visible as a link, but it cannot be a citable fact source and does
    not appear in the citation mapping — writing its title verbatim must not
    smuggle it in either.
    """

    def test_navigation_source_has_no_factual_content(self):
        assert not has_factual_content({
            "title": "vector — Official Documentation",
            "snippet": "Official documentation site for vector"})
        assert has_factual_content({"title": "t", "snippet": "a real body"})

    def test_the_retriever_output_shape_is_recognised(self):
        """The shape official.py actually emits must be treated as navigation.

        It marks the entry and leaves the snippet empty. A previous attempt
        checked only the raw caption text while the producer wrote a non-empty
        'NO CONTENT RETRIEVED — …' sentence, so every body-less official source
        stayed citable through the numbered path.
        """
        from deepchoice.retrievers.official import OfficialSearch

        entry = {"url": "https://www.postgresql.org/docs/",
                 "title": "PostgreSQL — Official Documentation",
                 "snippet": "", "has_body": False}
        assert not has_factual_content(entry)

        # And the placeholder sentence is not content either, whichever way it
        # arrives.
        assert not has_factual_content({
            "title": "PostgreSQL — Official Documentation",
            "snippet": ("NO CONTENT RETRIEVED — PostgreSQL — Official Documentation "
                        "is a documentation link only; its page body was not "
                        "collected, so it states nothing about this question.")})

    @pytest.mark.asyncio
    async def test_official_retriever_marks_its_entries_as_body_less(self):
        """Drive the real retriever: its entries must be non-citable."""
        search = OfficialSearch()
        out = await search._do_search(
            "pgvector on RDS", [], 10, [], ["PostgreSQL"])
        assert out, "the candidate should resolve a curated docs entry"
        for entry in out:
            assert has_factual_content(entry) is False, entry

    def test_official_placeholder_never_enters_the_citation_registry(self):
        """The renderer's numbered citation path must exclude it too."""
        from deepchoice.formats.citations import number_sources

        entry = {"url": "https://www.postgresql.org/docs/",
                 "title": "PostgreSQL — Official Documentation",
                 "snippet": "", "has_body": False}
        assert number_sources([{"sources": [entry]}]) == []

    def test_navigation_source_is_excluded_from_the_citation_mapping(self):
        nav = {"title": "vector — Official Documentation", "url": "https://vector.dev/docs/",
               "snippet": "Official documentation site for vector", "score": 6.8}
        real = {"title": "Real Page", "url": "https://real/page",
                "snippet": "pgvector HNSW measured at sub-20ms on 1M vectors.",
                "score": 7.0}
        text, mapping = _summarize_chains(
            [{"conclusion": "c", "evidence_strength": "moderate",
              "sources": [nav, real]}], ["pgvector"])

        assert "vector — Official Documentation" not in mapping.values(), \
            "a navigation link entered the citation mapping"
        assert "Real Page" in mapping.values()
        assert "NOT citable" in text
        assert "https://vector.dev/docs/" in text, "the link should still be visible"

    def test_a_chain_with_only_navigation_is_a_stated_gap(self):
        nav = {"title": "vector — Official Documentation", "url": "https://vector.dev/docs/",
               "snippet": "Official documentation site for vector", "score": 6.8}
        text, mapping = _summarize_chains(
            [{"conclusion": "c", "evidence_strength": "moderate", "sources": [nav]}],
            ["pgvector"])
        assert mapping == {}
        assert "no fact-bearing source" in text

    def test_writing_a_navigation_title_verbatim_is_stripped(self):
        from deepchoice.agents.conclusion_synthesizer import _sanitize_citations

        nav = {"title": "vector — Official Documentation", "url": "https://vector.dev/docs/",
               "snippet": "Official documentation site for vector", "score": 6.8}
        real = {"title": "Real Page", "url": "https://real/page",
                "snippet": "body", "score": 7.0}
        chains = [{"conclusion": "c", "evidence_strength": "moderate",
                   "sources": [nav, real]}]
        result = _sanitize_citations({
            "recommendation": "Use pgvector [Source: vector — Official Documentation] "
                              "and it is fast [Source: Real Page].",
        }, chains)
        assert "vector — Official Documentation" not in result["recommendation"], \
            "a navigation title was accepted as a citation"
        assert "Real Page" in result["recommendation"]


class TestCandidateAssociation:
    """Explicit association: a source belongs to a candidate only when it names
    it, not because a word is shared."""

    CANDIDATES = ["Amazon OpenSearch Service", "Amazon OpenSearch Serverless",
                  "Amazon Athena over S3", "ClickHouse"]

    def test_shared_word_alone_is_not_an_association(self):
        assert candidate_for_source(
            {"title": "What is serverless computing?", "url": "https://ex.com/serverless"},
            self.CANDIDATES) is None

    def test_serverless_page_does_not_land_on_the_generic_service(self):
        owner = candidate_for_source(
            {"title": "Amazon OpenSearch Serverless pricing",
             "url": "https://aws.amazon.com/opensearch-serverless"}, self.CANDIDATES)
        assert owner == "Amazon OpenSearch Serverless", owner

    def test_named_candidates_still_match(self):
        assert candidate_for_source(
            {"title": "ClickHouse for logs", "url": "https://clickhouse.com/docs"},
            self.CANDIDATES) == "ClickHouse"
        assert candidate_for_source(
            {"title": "Amazon Athena over S3 pricing",
             "url": "https://aws.amazon.com/athena"}, self.CANDIDATES) == "Amazon Athena over S3"

    def test_a_partial_name_match_is_not_an_association(self):
        """Sharing part of a candidate's name does not make a source about it.

        'PostgreSQL 17 release notes' is not material for 'Amazon Aurora
        PostgreSQL with pgvector'. It is reported as unassigned rather than
        attributed to whichever candidate it most resembles.
        """
        candidates = ["PostgreSQL", "Amazon Aurora PostgreSQL with pgvector"]
        assert candidate_for_source(
            {"title": "PostgreSQL 17 release notes",
             "url": "https://www.postgresql.org/docs/release-17"},
            candidates) == "PostgreSQL"
        assert candidate_for_source(
            {"title": "Amazon Aurora PostgreSQL with pgvector",
             "url": "https://aws.amazon.com/rds/aurora/pgvector"},
            candidates) == "Amazon Aurora PostgreSQL with pgvector"
        # A source about neither is unassigned, not dealt to the nearest name.
        assert candidate_for_source(
            {"title": "Log analytics benchmark", "url": "https://x/bench"},
            candidates) is None

    def test_specific_candidate_wins_over_a_shorter_one(self):
        candidates = ["Amazon Aurora PostgreSQL with pgvector", "PostgreSQL"]
        assert candidate_for_source(
            {"title": "Amazon Aurora PostgreSQL with pgvector limits",
             "url": "https://aws.amazon.com/rds/aurora"}, candidates) == \
            "Amazon Aurora PostgreSQL with pgvector"

    def test_no_word_list_decides_attribution(self):
        """Attribution must not depend on a curated 'distinguishing' word list."""
        import deepchoice.utils.candidate_identity as cid

        assert not hasattr(cid, "_DISAMBIGUATING")

    def test_unassignable_material_is_listed_not_dealt_out(self):
        sources = [
            {"title": "Log analytics benchmark", "url": "https://x/bench",
             "snippet": "body", "score": 7.0},
            {"title": "ClickHouse for logs", "url": "https://clickhouse.com/docs",
             "snippet": "body", "score": 7.0},
        ]
        index = index_sources_by_candidate(sources, self.CANDIDATES)
        assert [s["title"] for s in index[UNASSIGNED]] == ["Log analytics benchmark"]
        assert [s["title"] for s in index["ClickHouse"]] == ["ClickHouse for logs"]
        assert index["Amazon OpenSearch Service"] == []

    def test_what_shows_unassigned_material_separately(self):
        state = {
            "task": {"query": "logs", "candidate_techs": self.CANDIDATES},
            "evidence_chains": [{
                "conclusion": "Log analytics benchmark",
                "evidence_strength": "moderate",
                "sources": [{"title": "Log analytics benchmark", "url": "https://x/bench",
                             "snippet": "body", "score": 7.0}],
            }],
            "conflicts": [], "knowledge_gaps": [], "final_recommendation": {},
            "confidence": "low",
        }
        what = render(state).split("## Why")[0]
        assert "Unassigned material" in what or "未归属材料" in what
        for candidate in self.CANDIDATES:
            assert f"### {candidate}" in what


class TestBodyLessSourcesAcrossEveryRoute:
    """A body-less source must not be presented as evidence on any route.

    The retriever marker, the prompt and the citation registry were fixed first,
    but three renderer/UI routes still leaked it: evidence_first's evidence list,
    the reading view's evidence card, and the renderer's re-attached
    '*Sources:*' line (which worked because a short title is a substring of a
    longer real one).
    """

    NAV = {"url": "https://www.postgresql.org/docs/",
           "title": "PostgreSQL — Official Documentation",
           "snippet": "", "has_body": False, "score": 8.0}
    REAL = {"url": "https://www.postgresql.org/docs/release-17",
            "title": "PostgreSQL 17 release notes",
            "snippet": "PostgreSQL 17 improves vacuum and logical replication.",
            "has_body": True, "score": 7.5}

    def _chains(self):
        return [{"conclusion": "c", "evidence_strength": "strong", "disputed": False,
                 "sources": [self.NAV, self.REAL]}]

    def _state(self):
        return {"task": {"query": "pgvector", "candidate_techs": ["PostgreSQL"]},
                "evidence_chains": self._chains(), "conflicts": [],
                "knowledge_gaps": [], "final_recommendation": {},
                "confidence": "medium"}

    def test_marker_survives_evidence_chain(self):
        from deepchoice.agents.evidence_chain import build_evidence_chain

        chains = build_evidence_chain([
            {"url": self.NAV["url"], "title": self.NAV["title"], "snippet": "",
             "has_body": False, "total_score": 8.0, "scores": {},
             "supporting_sources": []},
        ], [])
        assert chains[0]["sources"][0].get("has_body") is False

    def test_evidence_first_does_not_list_it_as_evidence(self):
        from deepchoice.formats.evidence_first import render as render_evidence

        out = render_evidence(self._state())
        # Scope to the evidence list itself: the link may still appear elsewhere
        # as a navigation reference, but not as this chain's evidence. Compare the
        # exact linked line, since one source URL is a prefix of the other.
        section = out.split("### Strongest Evidence")[-1].split("### Supporting")[0]
        nav_line = f"[{self.NAV['title']}]({self.NAV['url']})"
        assert nav_line not in section, section[:300]
        assert "[PostgreSQL 17 release notes]" in section

    def test_reading_view_payload_never_numbers_it(self):
        """The UI falls back to the card's own number for unknown URLs, so a
        body-less URL must not be in the registry at all."""
        from deepchoice.formats.citations import number_sources

        registry = number_sources(self._chains())
        assert [r["url"] for r in registry] == [self.REAL["url"]]

    def test_no_citation_anchor_lands_on_a_body_less_title(self):
        import re

        from deepchoice.formats.citations import inject_citations, number_sources
        from deepchoice.formats.what_why_how import render

        registry = number_sources(self._chains())
        marked = inject_citations(render(self._state()), registry)
        anchored = re.findall(r"([^>\n]*?)<sup><a class=\"cite\"", marked)
        assert not any("Official Documentation" in t for t in anchored), anchored

    def test_a_substring_title_cannot_pass_as_real(self):
        """The nav title is a prefix of a longer real title.

        Substring leniency let it survive citation sanitization, and the renderer
        then re-attached it as the claim's source.
        """
        from deepchoice.agents.conclusion_synthesizer import (
            _bind_citations,
            _sanitize_citations,
            _summarize_chains,
        )

        result = _sanitize_citations(
            {"recommendation":
             "Use it [Source: PostgreSQL — Official Documentation]."},
            self._chains())
        assert "Official Documentation" not in result["recommendation"], result

        _prompt, mapping = _summarize_chains(self._chains(), ["PostgreSQL"])
        assert self.NAV["title"] not in mapping.values(), mapping
        bound = _bind_citations({"recommendation": "Use it [[1]]."}, mapping)
        assert "Official Documentation" not in bound["recommendation"], bound
        assert self.REAL["title"] in bound["recommendation"]

    def test_renderer_source_lookup_excludes_body_less_sources(self):
        """An all-body-less chain must not yield an attached Sources line."""
        from deepchoice.formats.what_why_how import _cited_sources, render

        state = {**self._state(),
                 "evidence_chains": [{"conclusion": "c", "evidence_strength": "strong",
                                      "disputed": False, "sources": [self.NAV]}]}
        out = render(state)
        assert "*Sources: [PostgreSQL — Official Documentation]" not in out
        assert _cited_sources("x [Source: PostgreSQL — Official Documentation].",
                              {}) == []


class TestRendererDoesNotGuessCitations:
    def test_uncited_text_attaches_nothing(self):
        assert _cited_sources("prose with no citation", {}) == []

    def test_only_the_cited_source_is_attached(self):
        chain_sources = {"c": ["[Real Source](https://real)"]}
        got = _cited_sources("A claim [Source: Real Source].", chain_sources)
        assert got == ["[Real Source](https://real)"]
