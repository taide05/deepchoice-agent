"""Tests for report citation injection and TOC building (formats/citations.py)."""
from deepchoice.formats.citations import (
    build_toc,
    citation_verification_section,
    inject_citations,
    number_sources,
)
from deepchoice.formats import comparison_matrix, evidence_first, what_why_how

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

    def test_canonical_equivalent_urls_dedupe_and_aggregate_highest_risk_status(self):
        chains = [
            {"sources": [{
                "title": "First", "url": "https://EXAMPLE.com/article#top",
                "verification_status": "verified", "verification_reason": "lexical_support",
            }]},
            {"sources": [
                {
                    "title": "Second", "url": "https://example.com/article#other",
                    "verification_status": "unreachable", "verification_reason": "network_uncertain",
                },
                {
                    "title": "Third", "url": "https://example.com/article#last",
                    "verification_status": "unsupported", "verification_reason": "numeric_mismatch",
                },
            ]},
        ]
        registry = number_sources(chains)
        assert len(registry) == 1
        assert registry[0]["url"] == "https://example.com/article"
        assert registry[0]["canonical_url"] == "https://example.com/article"
        assert registry[0]["chain_idx"] == 0
        assert registry[0]["source_idx"] == 0
        assert registry[0]["verification_status"] == "unsupported"
        assert registry[0]["verification_reason"] == "numeric_mismatch"

    def test_status_priority_unsupported_then_unreachable_then_unknown_then_verified(self):
        def aggregate(statuses):
            return number_sources([{"sources": [
                {"url": f"https://example.com/x#{i}", "verification_status": status}
                for i, status in enumerate(statuses)
            ]}])[0]["verification_status"]

        assert aggregate(["verified", "unknown"]) == "unknown"
        assert aggregate(["unknown", "unreachable"]) == "unreachable"
        assert aggregate(["unreachable", "unsupported"]) == "unsupported"

    def test_historical_sources_project_as_unknown_not_checked(self):
        registry = number_sources([{"sources": [{"title": "Old", "url": "https://example.com/old"}]}])
        assert registry[0]["verification_status"] == "unknown"
        assert registry[0]["verification_reason"] == "not_checked"

    def test_untrusted_stored_canonical_url_is_recomputed_from_source_url(self):
        registry = number_sources([{"sources": [{
            "title": "Docs",
            "url": "https://example.com/real#section",
            "canonical_url": "javascript:alert(1)",
        }]}])
        assert registry[0]["url"] == "https://example.com/real"
        assert registry[0]["canonical_url"] == "https://example.com/real"


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

    def test_canonical_equivalent_url_gets_same_number(self):
        registry = number_sources([{"sources": [{
            "title": "Original", "url": "https://EXAMPLE.com/article#one",
        }]}])
        out = inject_citations("[Equivalent](HTTPS://example.com/article#two)", registry)
        assert 'href="#ev-1"' in out
        assert "(https://" not in out

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


def test_citation_verification_summary_warns_and_clarifies_unknown():
    state = {
        "citation_verification": {
            "status_counts": {"verified": 2, "unsupported": 1, "unreachable": 0, "unknown": 3}
        }
    }
    section = "\n".join(citation_verification_section(state, "en"))
    assert "Unsupported 1" in section and "Unknown 3" in section
    assert "review" in section
    assert "not necessarily incorrect" in section
    assert citation_verification_section({}, "en") == []


def test_all_report_formats_include_verification_warning_and_legacy_omits_it():
    state = {
        "task": {"query": "FastAPI vs Flask"},
        "evidence_chains": [],
        "citation_verification": {
            "status_counts": {"verified": 1, "unsupported": 0, "unreachable": 0, "unknown": 0}
        },
    }
    for renderer in (what_why_how.render, evidence_first.render, comparison_matrix.render):
        assert "Citation Verification" in renderer(state)
        assert "All checked citations passed" in renderer(state)
        assert "Citation Verification" not in renderer({"task": {"query": "FastAPI vs Flask"}})
