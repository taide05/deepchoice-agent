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
    """Explicit association: a source belongs to a candidate only when the page is
    about it, not because a word is shared.

    A page must name the candidate (in full, or by its identity phrase) AND its
    collected body must actually discuss it. Fixtures therefore carry a body: a
    title alone is not material.
    """

    CANDIDATES = ["Amazon OpenSearch Service", "Amazon OpenSearch Serverless",
                  "Amazon Athena over S3", "ClickHouse"]

    def test_shared_word_alone_is_not_an_association(self):
        assert candidate_for_source(
            {"title": "What is serverless computing?",
             "url": "https://ex.com/serverless",
             "snippet": "Serverless computing abstracts capacity planning."},
            self.CANDIDATES) is None

    def test_serverless_page_does_not_land_on_the_generic_service(self):
        owner = candidate_for_source(
            {"title": "Amazon OpenSearch Serverless pricing",
             "url": "https://aws.amazon.com/opensearch-serverless",
             "snippet": "Amazon OpenSearch Serverless bills by OCU-hour."},
            self.CANDIDATES)
        assert owner == "Amazon OpenSearch Serverless", owner

    def test_named_candidates_still_match(self):
        assert candidate_for_source(
            {"title": "ClickHouse for logs", "url": "https://clickhouse.com/docs",
             "snippet": "ClickHouse stores logs in a columnar format."},
            self.CANDIDATES) == "ClickHouse"
        assert candidate_for_source(
            {"title": "Amazon Athena over S3 pricing",
             "url": "https://aws.amazon.com/athena",
             "snippet": "Amazon Athena charges per terabyte scanned."},
            self.CANDIDATES) == "Amazon Athena over S3"

    def test_a_page_named_for_the_product_is_material(self):
        """A page titled after the product it documents is that product's material.

        Requiring the full candidate name ('Amazon Athena over S3') reported real
        Athena documentation as a gap; the identity phrase is what a page uses.
        """
        assert candidate_for_source(
            {"title": "Amazon Athena - Serverless Interactive Query Service",
             "url": "https://aws.amazon.com/athena/",
             "snippet": "With Amazon Athena, you pay only for the queries you run."},
            self.CANDIDATES) == "Amazon Athena over S3"

    def test_a_page_about_another_product_is_not_material(self):
        """A page whose own subject is a different product is not the candidate's
        material, even when it mentions the candidate in its body."""
        assert candidate_for_source(
            {"title": "可观测性方案怎么选？SelectDB vs Elasticsearch vs ClickHouse — SelectDB 博客",
             "url": "https://www.selectdb.com/blog/1398",
             "snippet": "SelectDB 采用列式存储，性能优于 Elasticsearch；ClickHouse 也在对比中。"},
            self.CANDIDATES) is None

    def test_a_title_naming_a_product_the_body_never_discusses(self):
        """The Elastic pricing page names the candidate in its title while its
        collected text is about Elastic's own pricing."""
        assert candidate_for_source(
            {"title": "Amazon OpenSearch 对比 Elasticsearch | Elastic",
             "url": "https://www.elastic.co/cn/amazon-opensearch-service",
             "snippet": "Observability 和 Security 根据数据摄取和保留计算费用；"
                        "Search 起价仅为每月 $24。"},
            self.CANDIDATES) is None

    def test_a_partial_name_match_is_not_an_association(self):
        """Sharing part of a candidate's name does not make a source about it.

        'PostgreSQL 17 release notes' is not material for 'Amazon Aurora
        PostgreSQL with pgvector'. It is reported as unassigned rather than
        attributed to whichever candidate it most resembles.
        """
        candidates = ["PostgreSQL", "Amazon Aurora PostgreSQL with pgvector"]
        assert candidate_for_source(
            {"title": "PostgreSQL 17 release notes",
             "url": "https://www.postgresql.org/docs/release-17",
             "snippet": "PostgreSQL 17 release notes cover vacuum improvements."},
            candidates) == "PostgreSQL"
        assert candidate_for_source(
            {"title": "Amazon Aurora PostgreSQL with pgvector",
             "url": "https://aws.amazon.com/rds/aurora/pgvector",
             "snippet": "Amazon Aurora PostgreSQL with pgvector supports HNSW."},
            candidates) == "Amazon Aurora PostgreSQL with pgvector"
        # A source about neither is unassigned, not dealt to the nearest name.
        assert candidate_for_source(
            {"title": "Log analytics benchmark", "url": "https://x/bench",
             "snippet": "A benchmark of log pipelines."},
            candidates) is None

    def test_specific_candidate_wins_over_a_shorter_one(self):
        candidates = ["Amazon Aurora PostgreSQL with pgvector", "PostgreSQL"]
        assert candidate_for_source(
            {"title": "Amazon Aurora PostgreSQL with pgvector limits",
             "url": "https://aws.amazon.com/rds/aurora",
             "snippet": "Amazon Aurora PostgreSQL with pgvector has index limits."},
            candidates) == "Amazon Aurora PostgreSQL with pgvector"

    def test_no_word_list_decides_attribution(self):
        """Attribution must not depend on a curated 'distinguishing' word list."""
        import deepchoice.utils.candidate_identity as cid

        assert not hasattr(cid, "_DISAMBIGUATING")

    def test_unassignable_material_is_listed_not_dealt_out(self):
        sources = [
            {"title": "Log analytics benchmark", "url": "https://x/bench",
             "snippet": "A benchmark of log pipelines.", "score": 7.0},
            {"title": "ClickHouse for logs", "url": "https://clickhouse.com/docs",
             "snippet": "ClickHouse stores logs columnar.", "score": 7.0},
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
        # It may be listed, but only as a labelled navigation link, never as
        # unlabelled evidence.
        for line in section.splitlines():
            if nav_line in line:
                assert "navigation link only" in line or "导航链接" in line, line
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
        """The nav title IS a substring of the longer real title here.

        A previous fixture used a real title that did not contain the nav title,
        so the substring branch was never reached and the test passed against the
        old lenient rule too.
        """
        from deepchoice.agents.conclusion_synthesizer import (
            _bind_citations,
            _sanitize_citations,
            _summarize_chains,
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

        result = _sanitize_citations(
            {"recommendation":
             "Use it [Source: PostgreSQL — Official Documentation]."}, chains)
        assert nav["title"] not in result["recommendation"], result

        _prompt, mapping = _summarize_chains(chains, ["PostgreSQL"])
        assert nav["title"] not in mapping.values(), mapping
        bound = _bind_citations({"recommendation": "Use it [[1]]."}, mapping)
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
