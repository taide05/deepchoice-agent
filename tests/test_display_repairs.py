"""Round-11 display repairs: bracket titles, full field sources, titles, punctuation.

These are presentation/identity defects observed in the seventh run (task
49cf0eee-ad7d-48c3-aa39-1b51731fb1c5) and fixed on the shared paths, not by
per-title exceptions.
"""
from deepchoice.formats.citations import inject_citations
from deepchoice.formats.comparison_matrix import render as render_cm
from deepchoice.formats.evidence_first import render as render_ef
from deepchoice.formats.what_why_how import _field_source_links
from deepchoice.formats.what_why_how import render as render_www

BRACKET_TITLE = "Stop Leaked Secrets in Git With Gitleaks [2026]"
BRACKET_URL = "https://tech-insider.org/stop-leaked-secrets-git-gitleaks-2026"


def _state(**overrides):
    state = {
        "task": {"query": "Gitleaks vs TruffleHog for private GitLab",
                 "candidate_techs": ["Gitleaks", "TruffleHog"]},
        "evidence_chains": [],
        "conflicts": [],
        "knowledge_gaps": [],
        "final_recommendation": {},
        "confidence": "low",
    }
    state.update(overrides)
    return state


class TestBracketTitles:
    def test_a_balanced_bracket_title_still_gets_its_citation_badge(self):
        md = f"*Sources: [{BRACKET_TITLE}]({BRACKET_URL})*"
        annotated = inject_citations(md, [{"n": 18, "url": BRACKET_URL,
                                           "title": BRACKET_TITLE}])
        assert 'href="#ev-18"' in annotated, annotated
        assert "[18]" in annotated
        assert BRACKET_TITLE in annotated

    def test_bracket_title_does_not_break_following_links_or_text(self):
        second = "https://example.com/second"
        md = (f"lead [{BRACKET_TITLE}]({BRACKET_URL}) middle "
              f"[Second]({second}) tail")
        annotated = inject_citations(md, [
            {"n": 1, "url": BRACKET_URL, "title": BRACKET_TITLE},
            {"n": 2, "url": second, "title": "Second"},
        ])
        assert 'href="#ev-1"' in annotated
        assert 'href="#ev-2"' in annotated
        assert "middle" in annotated and "tail" in annotated


class TestFieldSources:
    def test_all_bound_sources_are_shown_not_only_the_first_three(self):
        bindings = [{"source_id": f"https://example.com/{i}",
                     "number": i + 1, "title": f"Source {i}",
                     "url": f"https://example.com/{i}"} for i in range(4)]
        rec = {"citation_sources": {"option=Gitleaks/rationale": bindings}}
        links = _field_source_links(rec, "option=Gitleaks/rationale", "", [])
        assert len(links) == 4, links
        assert links[3] == "[Source 3](https://example.com/3)"

    def test_renderer_prints_every_bound_source(self):
        rec = {
            "winner": "Gitleaks",
            "recommendation": "Adopt Gitleaks [[1]]",
            "ranked_options": [{
                "name": "Gitleaks", "constraint_fit": "high",
                "rationale": "Offline scan fits the runner constraint [[1]]",
                "key_strength": "history scan [[1]]",
                "key_weakness": "custom rules [[1]]",
                "constraint_fit_reason": "no outbound calls [[1]]",
            }],
            "trade_off_findings": [],
            "scene_fit_note": "fits [[1]]",
            "evidence_summary": "summary [[1]]",
            "citation_sources": {"option=Gitleaks/rationale": [
                {"title": f"Source {i}", "url": f"https://example.com/{i}"}
                for i in range(4)
            ]},
        }
        md = render_www(_state(final_recommendation=rec))
        source_lines = [line for line in md.splitlines() if "*Sources:" in line]
        assert source_lines, md
        for i in range(4):
            assert f"https://example.com/{i}" in source_lines[0], source_lines[0]


class TestDisplayText:
    def test_multiline_query_heading_stays_on_one_line(self):
        query = "第一行需求\n第二行约束\n第三行场景"
        state = _state(task={"query": query, "candidate_techs": ["Gitleaks", "TruffleHog"]})
        for renderer in (render_www, render_cm, render_ef):
            md = renderer(state)
            first_line = md.splitlines()[0]
            assert first_line.startswith("# ")
            assert "第一行需求 第二行约束 第三行场景" in first_line, first_line

    def test_dangling_space_before_punctuation_is_display_only(self):
        gap = "需要查官方 CLI 文档 。"
        md = render_www(_state(knowledge_gaps=[gap]))
        assert "- 需要查官方 CLI 文档。" in md, md
        assert " 。" not in md
        # Text is not deleted to clean the punctuation.
        assert "需要查官方 CLI 文档" in md

class TestScannerRobustness:
    def test_unmatched_bracket_does_not_suppress_later_badges(self):
        """Body text can contain an unmatched `[`. The scanner must advance, not
        abandon the rest of the report (the old flat regex still annotated B)."""
        md = "Intro [oops and then [B](https://b.example/doc)"
        annotated = inject_citations(md, [{"n": 2, "url": "https://b.example/doc",
                                           "title": "B"}])
        assert 'href="#ev-2"' in annotated, annotated
        assert "[2]" in annotated
        assert "Intro [oops and then" in annotated

    def test_escaped_and_nested_brackets_inside_a_label(self):
        url = "https://a.example/doc"
        md = r"[A [nested] label](https://a.example/doc)"
        annotated = inject_citations(md, [{"n": 1, "url": url, "title": "A"}])
        assert 'href="#ev-1"' in annotated
        assert "[1]" in annotated

    def test_conflict_claim_excerpt_is_escaped_and_title_labels_the_link(self):
        state = _state(conflicts=[{
            "claim_a": "docs [ broken excerpt",
            "claim_b": "other [ excerpt",
            "source_a": {"url": "https://a.example/doc", "title": "Bench [2026]",
                         "snippet": "docs [ broken excerpt", "score": 8},
            "source_b": {"url": "https://b.example/doc", "title": "Other",
                         "snippet": "other [ excerpt", "score": 7},
            "resolution": "insufficient_data", "confidence": "low",
            "reasoning": "r", "key_factor": "k",
        }])
        md = render_www(state)
        # The source title labels the link; brackets are escaped, not interpreted.
        assert r"[Bench \[2026\]](https://a.example/doc)" in md, md
        # The excerpt is plain escaped text, so it cannot become a live link.
        assert r"docs \[ broken excerpt" in md
        assert "[1]" not in md  # conflict section has no evidence badges

    def test_excluded_bodyless_sources_are_noted_when_no_conflict_remains(self):
        state = _state(conflict_check={
            "pairs_scanned": 2,
            "scan_outcomes": {"difference": 0, "no_difference": 2, "unscanned": 0},
            "sources_without_comparable_claim": 3,
        })
        for renderer in (render_www, render_cm, render_ef):
            md = renderer(state)
            # Language follows the task query (this fixture is English).
            assert "3 high-scoring source(s) had no collected body" in md, (renderer, md)
            assert "were not compared for conflicts" in md, (renderer, md)

class TestBodylessSourceRegistry:
    def test_a_bodyless_repository_metadata_row_is_navigation_not_citation(self):
        from deepchoice.agents.conclusion_synthesizer import build_source_registry
        from deepchoice.formats.citations import number_sources

        url = "https://github.com/gitleaks/gitleaks"
        chains = [{"sources": [{
            "title": "gitleaks/gitleaks", "url": url,
            "snippet": "Stars: 20000, Forks: 1500", "has_body": False,
        }]}]
        registry = build_source_registry(chains)
        assert registry["entries"] == []
        assert registry["navigation"] == [url]
        assert number_sources(chains) == []
