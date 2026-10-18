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
    bounded_content_summary,
    candidate_tokens,
    has_factual_content,
    mapping_key_for,
    names_candidate,
    split_navigation_label,
)

FAILED_RUN = (pathlib.Path(r"D:\deepchoice-precodex\outputs")
              / "e3b1c837-d2e1-46a1-b77c-c46eefe41dea" / "research_snapshot.json")


def _similar_embeddings(dim: int = 8):
    """Distinct vectors that stay above the candidate similarity threshold."""
    import types

    import numpy as np

    def encode(titles):
        rows = []
        for index in range(len(titles)):
            row = np.ones(dim)
            row[0] = 1.0 - 0.01 * (index % 3)
            row[1] = 1.0 - 0.01 * ((index // 3) % 3)
            rows.append(row)
        return np.array(rows) if rows else np.ones((0, dim))
    return types.SimpleNamespace(encode=encode)


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

    def test_candidate_without_an_explanation_states_the_gap(self):
        """What reads the candidate explanations from the synthesis result.

        A candidate the synthesis did not explain is stated as a gap rather than
        filled by the renderer's own guess about which sources belong to it.
        """
        state = {
            "task": {"query": "X vs Y", "candidate_techs": ["Totally Unexplained Thing"]},
            "evidence_chains": [], "conflicts": [], "knowledge_gaps": [],
            "final_recommendation": {}, "confidence": "low",
        }
        what = render(state).split("\n## Why")[0]
        assert "Totally Unexplained Thing" in what
        assert "本次合成未给出该候选的说明" in what or \
            "synthesis produced no explanation" in what

    def test_candidate_explanation_comes_from_the_recommendation(self):
        """The What bullet for a candidate is the ranking's own explanation, so
        the two sections cannot disagree about what the candidate is."""
        state = {
            "task": {"query": "X vs Y", "candidate_techs": ["Candidate A", "Candidate B"]},
            "evidence_chains": [], "conflicts": [], "knowledge_gaps": [],
            "confidence": "low",
            "final_recommendation": {
                "winner": "Candidate A",
                "recommendation": "Pick A.",
                "ranked_options": [{
                    "rank": 1, "name": "Candidate A", "constraint_fit": "high",
                    "rationale": "Fits the stated constraint [Source: Real Source].",
                    "key_strength": "Simple to operate [Source: Real Source].",
                    "key_weakness": "Costs more at scale [Source: Real Source].",
                }],
            },
        }
        what = render(state).split("\n## Why")[0]
        assert "Fits the stated constraint" in what
        assert "Simple to operate" in what
        assert "Costs more at scale" in what
        # Candidate B has no explanation and is reported as a gap, not guessed at.
        section_b = what.split("### Candidate B")[-1]
        assert "本次合成未给出该候选的说明" in section_b or \
            "synthesis produced no explanation" in section_b

    def test_a_multiline_explanation_is_not_truncated(self):
        """A newline inside a model field used to break the bullet and drop the
        rest of that candidate's explanation."""
        state = {
            "task": {"query": "X vs Y", "candidate_techs": ["Candidate A"]},
            "evidence_chains": [], "conflicts": [], "knowledge_gaps": [],
            "confidence": "low",
            "final_recommendation": {
                "recommendation": "Pick A.",
                "ranked_options": [{
                    "rank": 1, "name": "Candidate A",
                    "rationale": "First line.\nSecond line with the real reason.",
                }],
            },
        }
        what = render(state).split("\n## Why")[0]
        assert "Second line with the real reason." in what


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
        """The navigation title is not accepted as a citation; it is kept only as
        an unresolved-citation gap, so the claim cannot read as supported."""
        from deepchoice.agents.conclusion_synthesizer import apply_citation_rules

        nav = {"title": "vector — Official Documentation", "url": "https://vector.dev/docs/",
               "snippet": "Official documentation site for vector", "score": 6.8}
        real = {"title": "Real Page", "url": "https://real/page",
                "snippet": "body", "score": 7.0}
        chains = [{"conclusion": "c", "evidence_strength": "moderate",
                   "sources": [nav, real]}]
        result = apply_citation_rules({
            "recommendation": "Use pgvector [Source: vector — Official Documentation] "
                              "and it is fast [Source: Real Page].",
        }, chains)
        assert "[Source: vector — Official Documentation]" not in result["recommendation"], \
            "a navigation title was accepted as a citation"
        assert "Real Page" in result["recommendation"]
        assert "引用未解析" in result["recommendation"] or \
            "citation-unresolved" in result["recommendation"]


class TestCandidateNameMatching:
    """Name matching for the official-source mapping lookup.

    The renderer no longer maps sources onto candidates, so there is no
    attribution function left to test. What remains is `names_candidate`, which
    decides whether a declared candidate names a curated mapping entry; it must
    stay name-based and must not consult a word list.
    """

    CANDIDATES = ["Amazon OpenSearch Service", "Amazon OpenSearch Serverless",
                  "Amazon Athena over S3", "ClickHouse"]

    def test_a_shared_word_is_not_a_name_match(self):
        assert not names_candidate("What is serverless computing?", "ClickHouse")
        assert not names_candidate("serverless architecture", "Amazon OpenSearch Serverless")

    def test_a_full_name_still_matches(self):
        assert names_candidate("Amazon Athena over S3 pricing", "Amazon Athena over S3")
        assert names_candidate("ClickHouse for logs", "ClickHouse")
        assert names_candidate("Amazon OpenSearch Serverless pricing",
                               "Amazon OpenSearch Serverless")

    def test_a_partial_name_is_not_a_match(self):
        """Sharing part of a candidate's name does not name it.

        'PostgreSQL 17 release notes' does not name 'Amazon Aurora PostgreSQL
        with pgvector'; the whole name must appear as a run of words.
        """
        assert names_candidate("PostgreSQL 17 release notes", "PostgreSQL")
        assert not names_candidate("PostgreSQL 17 release notes",
                                   "Amazon Aurora PostgreSQL with pgvector")
        assert names_candidate("Amazon Aurora PostgreSQL with pgvector limits",
                               "Amazon Aurora PostgreSQL with pgvector")

    def test_no_subject_guessing_rules(self):
        """Attribution must not infer a page's subject from word lists or title
        prefixes. Those rules were withdrawn and must not return."""
        import deepchoice.utils.candidate_identity as cid

        for removed in ("_DISAMBIGUATING", "_QUALIFIER", "subject_tokens",
                        "identity_phrase", "_mentioned_in_body", "_LEADING_STOP",
                        "candidate_for_source", "index_sources_by_candidate",
                        "UNASSIGNED"):
            assert not hasattr(cid, removed), f"{removed} was reintroduced"

    def test_what_lists_the_sources_the_recommendation_cites(self):
        """The links under What are the recommendation's own citations, resolved
        through the evidence chains, and a body-less link is not among them."""
        state = {
            "task": {"query": "logs", "candidate_techs": self.CANDIDATES},
            "evidence_chains": [{
                "conclusion": "Log analytics benchmark",
                "evidence_strength": "moderate",
                "sources": [
                    {"title": "Real Benchmark", "url": "https://x/bench",
                     "snippet": "A measured benchmark body.", "score": 7.0},
                    {"title": "PostgreSQL Docs Link", "url": "https://www.postgresql.org/docs/",
                     "snippet": "", "has_body": False, "score": 6.0},
                ],
            }],
            "conflicts": [], "knowledge_gaps": [], "confidence": "low",
            "final_recommendation": {
                "recommendation": "Use it [Source: Real Benchmark].",
                "ranked_options": [{"rank": 1, "name": "ClickHouse",
                                    "rationale": "Columnar [Source: Real Benchmark]."}],
            },
        }
        report = render(state)
        what = report.split("\n## Why")[0]
        # The cited-source list is derived once, in References, from the sources
        # the synthesis result actually cites. It is no longer duplicated under
        # What, where the two copies could drift apart.
        references = report.split("### References")[-1]
        assert "https://x/bench" in references, "the cited source should be reachable"
        # A body-less link is listed only under the navigation heading, never as a
        # cited source for the recommendation.
        assert "https://www.postgresql.org/docs/" not in references, \
            "a body-less link must not be listed as a cited source"
        assert "https://www.postgresql.org/docs/" in what, \
            "the navigation link should still be reachable"
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
                "knowledge_gaps": [], "confidence": "medium",
                # A basis only exists if the synthesis result cites a source;
                # the report derives 'used' from the citations, not from what was
                # retrieved.
                "final_recommendation": {
                    "recommendation": f"Use it [Source: {self.REAL['title']}]."}}

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
        # The body-less link may still appear, but only as a labelled navigation
        # link. It must never be presented as a source the report relies on.
        nav_line = f"[{self.NAV['title']}]({self.NAV['url']})"
        for line in out.splitlines():
            if nav_line in line:
                assert "navigation link only" in line or "导航链接" in line, line
        # The cited, fact-bearing source is the report's basis.
        assert f"[{self.REAL['title']}]({self.REAL['url']}) ×1" in out
        assert "[PostgreSQL 17 release notes]" in out

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
        """The nav title IS a substring of the longer real title here.

        A previous fixture used a real title that did not contain the nav title,
        so the substring branch was never reached and the test passed against the
        old lenient rule too.
        """
        from deepchoice.agents.conclusion_synthesizer import (
            _summarize_chains,
            apply_citation_rules,
        )

        nav = {"url": "https://www.postgresql.org/docs/",
               "title": "PostgreSQL — Official Documentation",
               "snippet": "", "has_body": False, "score": 8.0}
        real = {"url": "https://www.postgresql.org/docs/release-17",
                "title": "PostgreSQL — Official Documentation and Release Notes",
                "snippet": "PostgreSQL 17 improves vacuum.", "has_body": True,
                "score": 7.5}
        chains = [{"conclusion": "c", "evidence_strength": "strong",
                   "disputed": False, "sources": [nav, real]}]

        # The hazard: the nav title is a normalised substring of the real one.
        from deepchoice.agents.conclusion_synthesizer import _norm_title

        assert _norm_title(nav["title"]) in _norm_title(real["title"]), \
            "fixture must reproduce the substring hazard"

        result = apply_citation_rules(
            {"recommendation":
             "Use it [Source: PostgreSQL — Official Documentation]."}, chains)
        # The navigation title is not accepted as a source. It remains only as a
        # located gap, never as a `[Source: ...]` citation.
        assert "[Source: PostgreSQL — Official Documentation]" not in \
            result["recommendation"], result
        assert "引用未解析" in result["recommendation"] or \
            "citation-unresolved" in result["recommendation"], result

        _prompt, mapping = _summarize_chains(chains, ["PostgreSQL"])
        assert nav["title"] not in mapping.values(), mapping
        bound = apply_citation_rules({"recommendation": "Use it [[1]]."}, chains,
                                     mapping)
        # Compare the parsed citation exactly: the nav title is a literal prefix of
        # the real one, so a substring check cannot distinguish them.
        import re

        cited = re.findall(r"\[Source:\s*([^\]]+)\]", bound["recommendation"])
        assert cited == [real["title"]], cited

    @pytest.mark.asyncio
    async def test_conflict_rows_keep_the_snippet_for_ordinary_sources(self, monkeypatch):
        """Drive the real conflict construction, where the bug lived.

        _cited_source rebuilt each source as {url, score}, dropping the snippet;
        the renderers then saw no body and branded every ordinary evidence source
        as body-less. A test that hand-builds the conflicts dict never executes
        that function, so it would pass even if the snippet were stripped again.
        """
        import asyncio

        from deepchoice.agents import conflict_detector as cd
        from deepchoice.utils.candidate_identity import has_factual_content

        monkeypatch.setattr(cd, "get_embedding_model", lambda: _similar_embeddings())

        async def fake_scan(src_a, src_b, query, usage=None):
            return {"has_difference": True, "type": "tradeoff_disagreement",
                    "explanation": "e"}

        monkeypatch.setattr(cd, "_scan_pair_contradiction", fake_scan)

        ordinary = {"url": "https://blog.example/a", "title": "Benchmark A",
                    "snippet": "Benchmark A measured p95 at 20ms on 1M vectors.",
                    "total_score": 9.5, "scores": {"authority": 9}}
        nav = {"url": self.NAV["url"], "title": self.NAV["title"], "snippet": "",
               "has_body": False, "total_score": 5.0, "scores": {"authority": 5}}

        result = await cd.ConflictDetectorAgent(gather_evidence=False).run({
            "source_scores": [ordinary, nav],
            "task": {"query": "t", "candidate_techs": ["PostgreSQL"]},
            "token_usage": [],
        })
        conflicts = result["conflicts"]
        assert conflicts, "the decisive score gap should build a conflict row"

        rows = [c[k] for c in conflicts for k in ("source_a", "source_b")]
        by_url = {row.get("url"): row for row in rows}
        ordinary_row = by_url.get(ordinary["url"])
        assert ordinary_row is not None, by_url
        # The snippet must survive, or the renderer judges it body-less.
        assert ordinary_row.get("snippet") == ordinary["snippet"], ordinary_row
        assert has_factual_content(ordinary_row) is True, ordinary_row
        nav_row = by_url.get(nav["url"])
        assert nav_row is not None and nav_row.get("has_body") is False, by_url
        assert has_factual_content(nav_row) is False, nav_row

    def test_a_fact_bearing_claim_source_is_not_mislabelled(self):
        """The shape every non-official retriever produces: a real snippet and NO
        has_body marker. Nothing in the pipeline ever sets has_body=True, so a
        label decided from a stripped dict branded ordinary evidence as body-less.
        """
        from deepchoice.formats.comparison_matrix import render as render_matrix
        from deepchoice.formats.evidence_first import render as render_evidence
        from deepchoice.formats.what_why_how import render as render_www

        ordinary = {"url": "https://blog.example/a", "score": 8.0,
                    "snippet": "Benchmark A measured p95 at 20ms."}
        state = {
            "task": {"query": "pgvector", "candidate_techs": ["PostgreSQL"]},
            "evidence_chains": [], "knowledge_gaps": [], "confidence": "low",
            "final_recommendation": {"recommendation": "x"},
            "conflicts": [{
                "resolution": "a", "claim_a": "Benchmark A", "claim_b": "Docs page",
                "source_a": dict(ordinary),
                "source_b": {"url": self.NAV["url"], "score": 6.8, "has_body": False},
                "reasoning": "r", "key_factor": "k", "confidence": "low",
            }],
        }
        for name, renderer in (("what_why_how", render_www),
                               ("evidence_first", render_evidence),
                               ("comparison_matrix", render_matrix)):
            out = renderer(state)
            line = [ln for ln in out.splitlines() if ordinary["url"] in ln]
            assert line, f"{name}: the ordinary source vanished"
            assert not any("no body" in ln or "无正文" in ln for ln in line), \
                f"{name} mislabelled a fact-bearing source: {line}"
            # And the body-less one is still labelled.
            nav_line = [ln for ln in out.splitlines() if self.NAV["url"] in ln]
            assert any("no body" in ln or "无正文" in ln for ln in nav_line), \
                f"{name} lost the body-less label"

    def test_plain_has_factual_content_for_an_ordinary_source(self):
        from deepchoice.utils.candidate_identity import has_factual_content

        assert has_factual_content(
            {"url": "https://x/a", "snippet": "A real body with a measurement."})
        assert not has_factual_content(
            {"url": "https://x/b", "snippet": "", "has_body": False})
        # The marker wins even when a body is present: a page whose text was not
        # kept is not evidence.
        assert not has_factual_content(
            {"url": "https://x/c", "snippet": "looks like a body",
             "has_body": False})

    def test_evidence_first_keeps_a_navigation_link_reachable_without_disputes(self):
        """Outside the disputes section the link used to disappear entirely, so
        the reader could not reach the page at all."""
        from deepchoice.formats.evidence_first import render as render_evidence

        state = {
            "task": {"query": "pgvector", "candidate_techs": ["PostgreSQL"]},
            "evidence_chains": [{"conclusion": "c", "evidence_strength": "strong",
                                 "disputed": False, "sources": [self.NAV]}],
            "conflicts": [], "knowledge_gaps": [], "confidence": "high",
            "final_recommendation": {"recommendation": "x"},
        }
        out = render_evidence(state)
        assert self.NAV["url"] in out, "the navigation link disappeared"
        assert "navigation link only" in out or "导航链接" in out

    def test_conflict_claims_label_a_body_less_source(self):
        """The dispute path dropped the marker, so all three renderers linked a
        claim to a body-less page as if it were the claim's source."""
        """The dispute path dropped the marker, so all three renderers linked a
        claim to a body-less page as if it were the claim's source."""
        from deepchoice.formats.comparison_matrix import render as render_matrix
        from deepchoice.formats.evidence_first import render as render_evidence
        from deepchoice.formats.what_why_how import render as render_www

        state = {
            "task": {"query": "pgvector", "candidate_techs": ["PostgreSQL"]},
            "evidence_chains": [], "knowledge_gaps": [], "confidence": "low",
            "final_recommendation": {"recommendation": "x"},
            "conflicts": [{
                "resolution": "a",
                "claim_a": self.NAV["title"], "claim_b": "Real claim",
                "source_a": {"url": self.NAV["url"], "score": 6.8, "has_body": False},
                "source_b": {"url": self.REAL["url"], "score": 7.0, "has_body": True},
                "reasoning": "r", "key_factor": "k", "confidence": "low",
            }],
        }
        for name, renderer in (("what_why_how", render_www),
                               ("evidence_first", render_evidence),
                               ("comparison_matrix", render_matrix)):
            out = renderer(state)
            dispute = out.split("Claim A" if name != "comparison_matrix" else "Side A")[-1]
            nav_line = [ln for ln in dispute.splitlines() if self.NAV["url"] in ln]
            assert nav_line, f"{name}: the link should stay visible"
            assert any("no body collected" in ln or "无正文" in ln for ln in nav_line), \
                f"{name} presented a body-less page as a claim's source: {nav_line}"
            # The fact-bearing source is unaffected.
            real_line = [ln for ln in dispute.splitlines() if self.REAL["url"] in ln]
            assert real_line and not any("no body" in ln for ln in real_line), real_line

    def test_conflict_builder_keeps_the_body_marker(self):
        """The marker must not be dropped when a conflict row is built."""
        import inspect

        from deepchoice.agents import conflict_detector as cd

        source = inspect.getsource(cd.ConflictDetectorAgent.run)
        assert "has_body" in source, \
            "the conflict builder dropped the body marker"

    def test_renderer_source_lookup_excludes_body_less_sources(self):
        """The `*Sources:*` line must not re-attach a body-less link.

        The branch only runs when the recommendation carries ranked options or
        trade-offs, so the fixture must populate them; otherwise the assertion
        passes on any implementation.
        """
        from deepchoice.formats.what_why_how import _cited_sources, render

        nav = self.NAV
        real = self.REAL
        state = {
            "task": {"query": "pgvector", "candidate_techs": ["PostgreSQL"]},
            "evidence_chains": [{"conclusion": "c", "evidence_strength": "strong",
                                 "disputed": False, "sources": [nav, real]}],
            "conflicts": [], "knowledge_gaps": [], "confidence": "medium",
            "final_recommendation": {
                "winner": "PostgreSQL",
                "recommendation": "Use it.",
                "ranked_options": [{
                    "rank": 1, "name": "PostgreSQL",
                    "rationale": ("Measured at scale [Source: PostgreSQL — Official "
                                  "Documentation] and again [Source: PostgreSQL 17 "
                                  "release notes]."),
                }],
                "trade_offs": [{
                    "dimension": "ops",
                    "finding": ("Cheaper [Source: PostgreSQL — Official "
                                "Documentation]."),
                }],
            },
        }
        out = render(state)
        assert "ranked_options" or True
        assert "*Sources: [PostgreSQL — Official Documentation]" not in out, out
        assert "[PostgreSQL 17 release notes" in out

        # And directly: no lookup entry for a body-less source.
        assert _cited_sources(
            "x [Source: PostgreSQL — Official Documentation].",
            {"c": [f"[{real['title']}]({real['url']})"]}) == []


class TestRendererDoesNotGuessCitations:
    def test_uncited_text_attaches_nothing(self):
        assert _cited_sources("prose with no citation", {}) == []

    def test_only_the_cited_source_is_attached(self):
        chain_sources = {"c": ["[Real Source](https://real)"]}
        got = _cited_sources("A claim [Source: Real Source].", chain_sources)
        assert got == ["[Real Source](https://real)"]
