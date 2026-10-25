"""Display repairs: bracket titles, full field sources, titles, punctuation.

The saved seventh report/annotated material shows these presentation and
identity defects directly (multi-line heading, dangling punctuation, missing
bracket-title badge, capped Sources). Fixes are on the shared paths, not
per-title exceptions; no single rendering defect is assumed proven by simulation.
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
            # The heading is a short display title, not the request. The full
            # request is one line of context in the body.
            assert "Gitleaks vs TruffleHog" in first_line, first_line
            assert "第一行需求 第二行约束 第三行场景" in md

    def test_dangling_space_before_punctuation_is_display_only(self):
        gap = "需要查官方 CLI 文档 。"
        md = render_www(_state(final_recommendation={"unresolved_questions": [gap]}))
        assert "- 需要查官方 CLI 文档。" in md, md
        assert " 。" not in md
        # Text is not deleted to clean the punctuation.
        assert "需要查官方 CLI 文档" in md

    def test_self_review_retry_queries_are_not_report_gaps(self):
        # `knowledge_gaps` are retry search targets, not user-facing gaps: they
        # stay in the snapshot and must not surface as raw search strings.
        retry_query = "RQ worker throughput benchmark tasks per second Redis Django production"
        md = render_www(_state(knowledge_gaps=[retry_query]))
        assert retry_query not in md
        assert "RQ worker throughput" not in md

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

class TestActualMarkdownRendering:
    """Check rendered HTML, not just escaped source strings.

    A conflict excerpt is scraped body text. Raw HTML, autolinks and Markdown
    control characters must all appear as literal text; the source link must
    remain a real link; the stored source/claim must remain untouched. The same
    assertion runs against all three report renderers and against the annotated
    reading view.
    """

    MALICIOUS = ("<img src=x onerror=alert(1)> *bold* `code` "
                 "[x](https://evil.example/x) <https://evil.example/auto>")
    SOURCE_URL = "https://source.example/doc"

    def _state(self):
        return _state(conflicts=[{
            "claim_a": self.MALICIOUS,
            "claim_b": "A normal competing excerpt",
            "source_a": {"url": self.SOURCE_URL,
                         "title": "<b>Source A</b> [2026]",
                         "snippet": self.MALICIOUS, "score": 8},
            "source_b": {"url": "https://source.example/b",
                         "title": "Source B", "snippet": "A normal competing excerpt",
                         "score": 7},
            "resolution": "insufficient_data", "confidence": "low",
            "reasoning": "r", "key_factor": "k",
        }])

    def test_all_renderers_keep_untrusted_text_literal_and_links_intact(self):
        import copy

        import markdown

        registry = [{"n": 1, "url": self.SOURCE_URL,
                     "title": "<b>Source A</b> [2026]"}]
        renderers = (("what_why_how", render_www),
                     ("comparison_matrix", render_cm),
                     ("evidence_first", render_ef))
        for name, renderer in renderers:
            state = self._state()
            before = copy.deepcopy(state)
            md = renderer(state)
            rendered = markdown.markdown(md)
            # Raw HTML/script/autolink are not active.
            assert "<img" not in rendered.lower(), (name, rendered)
            assert "<script" not in rendered.lower(), (name, rendered)
            assert 'href="https://evil.example' not in rendered, (name, rendered)
            # The text is still visible as literal content.
            assert "&lt;img" in rendered, (name, rendered)
            assert "*bold*" in rendered or "\\*bold\\*" in rendered, (name, rendered)
            # The real source link survives as a link.
            assert f'href="{self.SOURCE_URL}"' in rendered, (name, rendered)
            # Stored claim/body/source are not mutated by display.
            assert state == before, name

            annotated = inject_citations(md, registry)
            assert 'href="#ev-1"' in annotated, (name, annotated)
            assert 'href="https://evil.example' not in annotated, (name, annotated)
            # Annotated HTML shows the literal title, not double-escaped entities.
            assert "&lt;b&gt;Source A&lt;/b&gt;" in annotated, (name, annotated)
            assert "&amp;lt;b&amp;gt;" not in annotated, (name, annotated)


class TestEvidenceLimitsAndTradeoffImpact:
    def test_tradeoff_impact_and_evidence_summary_reach_the_default_report(self):
        rec = {
            "winner": "Gitleaks",
            "winner_rationale": "Only one saved body states the scan mechanism.",
            "recommendation": "Use Gitleaks for the frozen GitLab scene.",
            "trade_offs": [{
                "dimension": "Detection vs false positives",
                "finding": "The saved body reports a trade-off but no accuracy measurement.",
                "impact": "A team with no dedicated security reviewer must budget triage time.",
            }],
            "evidence_summary": ("Only third-party blogs were saved; the official page was "
                                 "a navigation link and the scan time is unmeasured."),
            "confidence": "low",
            "confidence_rationale": "The self-review recorded missing official evidence.",
            "ranked_options": [],
        }
        md = render_www(_state(final_recommendation=rec))
        assert "A team with no dedicated security reviewer must budget triage time." in md, md
        assert "Only third-party blogs were saved" in md, md
        assert "### Evidence Summary" in md, md

    def test_duplicate_winner_rationale_is_not_printed_twice(self):
        repeated = "Use Gitleaks for the frozen GitLab scene."
        rec = {
            "winner": "Gitleaks",
            "winner_rationale": repeated,
            "recommendation": repeated,
            "trade_offs": [],
            "evidence_summary": "",
            "confidence": "low",
            "ranked_options": [],
        }
        md = render_www(_state(final_recommendation=rec))
        assert md.count(repeated) == 1, md

class TestAnnotatedRendering:
    """The annotated artifact is Markdown for the PDF/reading-view consumers.

    It must render the same literal label text after the second Markdown pass;
    the per-title escaping cannot be dropped just because annotation converts
    the link into labeled text.
    """

    TITLE = ("Docs [click](https://evil.example/x) *fast* "
             "![logo](https://evil.example/img.png)")
    SOURCE_URL = "https://source.example/doc"

    def test_all_renderers_annotated_markdown_is_literal_and_badge_present(self):
        import copy

        import markdown

        renderers = (("what_why_how", render_www),
                     ("comparison_matrix", render_cm),
                     ("evidence_first", render_ef))
        registry = [{"n": 1, "url": self.SOURCE_URL, "title": self.TITLE}]
        chains = [{"sources": [{
            "title": self.TITLE, "url": self.SOURCE_URL,
            "snippet": "excerpt A", "date": "2026-01-01",
        }]}]
        for name, renderer in renderers:
            state = _state(
                conflicts=[{
                    "claim_a": "excerpt A",
                    "claim_b": "excerpt B",
                    "source_a": {"url": self.SOURCE_URL, "title": self.TITLE,
                                 "snippet": "excerpt A", "score": 8},
                    "source_b": {"url": "https://source.example/b",
                                 "title": "Source B", "snippet": "excerpt B",
                                 "score": 7},
                    "resolution": "insufficient_data", "confidence": "low",
                    "reasoning": "r", "key_factor": "k",
                }],
                evidence_chains=chains,
                final_recommendation={
                    "recommendation": "Use it [[1]]",
                    "citation_sources": {"recommendation": [{
                        "source_id": self.SOURCE_URL, "number": 1,
                        "title": self.TITLE, "url": self.SOURCE_URL,
                    }]},
                },
            )
            before = copy.deepcopy(state)
            annotated = inject_citations(renderer(state), registry)
            # Production PDF/reading-view path parses the annotated Markdown again.
            rendered = markdown.markdown(annotated, extensions=["tables"])
            assert "<img" not in rendered.lower(), (name, rendered)
            assert 'href="https://evil.example' not in rendered, (name, rendered)
            # The badge points at the evidence card; the annotated reading view
            # intentionally replaces inline source links with that badge.
            assert 'href="#ev-1"' in rendered, (name, rendered)
            literal = "Docs [click](https://evil.example/x) *fast* ![logo](https://evil.example/img.png)"
            # The title can appear in the conflict row and in the used-source /
            # reference sections; every occurrence must be literal.
            assert literal in rendered, (name, rendered)
            assert rendered.count(literal) >= 1, (name, rendered)
            assert state == before, name
