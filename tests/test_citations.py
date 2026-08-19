"""Tests for report citation injection and TOC building (formats/citations.py)."""
import pytest

from deepchoice.formats.citations import number_sources, inject_citations, build_toc


CHAINS = [
    {
        "conclusion": "LangGraph wins for complex control flow",
        "evidence_strength": "strong",
        "disputed": False,
        "sources": [
            {"title": "LangGraph Docs", "url": "https://docs.langgraph.io/", "score": 9},
            {"title": "Benchmark Post", "url": "https://example.com/bench", "score": 7},
        ],
    },
    {
        "conclusion": "CrewAI better for quick prototypes",
        "evidence_strength": "moderate",
        "disputed": False,
        "sources": [
            {"title": "Benchmark Post", "url": "https://example.com/bench", "score": 6},
        ],
    },
    {
        "conclusion": "No-url chain",
        "evidence_strength": "weak",
        "disputed": False,
        "sources": [{"title": "Mystery Source", "url": "", "score": 3}],
    },
]


class TestNumberSources:
    def test_dedupes_repeated_urls(self):
        registry = number_sources(CHAINS)
        urls = [r["url"] for r in registry]
        assert urls == ["https://docs.langgraph.io/", "https://example.com/bench"]

    def test_assigns_stable_1_based_numbers(self):
        registry = number_sources(CHAINS)
        assert [r["n"] for r in registry] == [1, 2]

    def test_carries_title_and_chain_index_of_first_occurrence(self):
        registry = number_sources(CHAINS)
        assert registry[0]["title"] == "LangGraph Docs"
        assert registry[0]["chain_idx"] == 0
        assert registry[1]["title"] == "Benchmark Post"
        assert registry[1]["chain_idx"] == 0  # first seen in CHAINS[0], later dup skipped

    def test_empty_chains(self):
        assert number_sources([]) == []


class TestInjectCitations:
    def test_replaces_known_link_with_title_plus_sup_anchor(self):
        registry = number_sources(CHAINS)
        md = "See [Benchmark Post](https://example.com/bench) for details."
        out = inject_citations(md, registry)
        assert out == (
            'See Benchmark Post<sup><a class="cite" href="#ev-2">[2]</a></sup> for details.'
        )

    def test_same_url_gets_same_number(self):
        registry = number_sources(CHAINS)
        md = "[A](https://example.com/bench) and [B](https://example.com/bench)"
        out = inject_citations(md, registry)
        assert out.count("#ev-2") == 2
        assert "A<sup>" in out
        assert "B<sup>" in out
        assert "(https://" not in out

    def test_unknown_url_left_untouched(self):
        registry = number_sources(CHAINS)
        md = "[External](https://elsewhere.com/x)"
        assert inject_citations(md, registry) == md

    def test_plain_text_unaffected(self):
        registry = number_sources(CHAINS)
        md = "No links here, just [brackets] and (parens)."
        assert inject_citations(md, registry) == md


class TestBuildToc:
    def test_extracts_headings_with_levels_and_injects_spans(self):
        md = "# Title\n\n## Section One\n\n### Deep Dive\n\nbody"
        toc, annotated = build_toc(md)
        assert [t["text"] for t in toc] == ["Title", "Section One", "Deep Dive"]
        assert [t["level"] for t in toc] == [1, 2, 3]
        assert [t["id"] for t in toc] == ["sec-1", "sec-2", "sec-3"]
        assert '<span id="sec-1"></span>\n# Title' in annotated
        assert '<span id="sec-3"></span>\n### Deep Dive' in annotated

    def test_no_headings(self):
        toc, annotated = build_toc("just text")
        assert toc == []
        assert annotated == "just text"

    def test_heading_level4_ignored(self):
        md = "#### Not In Toc"
        toc, annotated = build_toc(md)
        assert toc == []
        assert annotated == md
