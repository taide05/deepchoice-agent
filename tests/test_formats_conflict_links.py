"""Conflict claims in all three renderers must carry source links (grounding).

Regression: after conflict detection was restored (2026-08-19), dispute
claims without links dragged claim_grounding_rate to the honest ~90% level.
Linking claims to their sources grounds them and feeds the reading view's
citation badges.

The display path escapes untrusted claim text for Markdown, so these tests
assert the rendered HTML (visible claim + real href), not a raw source string.
"""
import markdown

from deepchoice.formats.comparison_matrix import render as render_cm
from deepchoice.formats.evidence_first import render as render_ef
from deepchoice.formats.what_why_how import render as render_www

STATE = {
    "task": {"query": "FastAPI vs Flask for REST API"},
    "evidence_chains": [],
    "conflicts": [
        {
            "claim_a": "FastAPI is faster",
            "claim_b": "Flask is faster in micro-benchmarks",
            "source_a": {"url": "https://example.com/fastapi-bench", "score": 8},
            "source_b": {"url": "https://example.com/flask-bench", "score": 6},
            "resolution": "A_correct",
            "confidence": "high",
            "reasoning": "Benchmark evidence favors A.",
            "key_factor": "benchmark",
        }
    ],
    "final_recommendation": {},
    "confidence": "high",
}


def _assert_rendered_claim_link(md: str, claim: str, url: str) -> None:
    rendered = markdown.markdown(md)
    assert f'href="{url}"' in rendered, rendered
    assert claim in rendered, rendered


class TestConflictClaimLinks:
    def test_what_why_how_links_claim_a_and_b(self):
        md = render_www(STATE)
        _assert_rendered_claim_link(md, "FastAPI is faster",
                                    "https://example.com/fastapi-bench")
        _assert_rendered_claim_link(md, "Flask is faster in micro-benchmarks",
                                    "https://example.com/flask-bench")

    def test_evidence_first_links_conflict_claims(self):
        md = render_ef(STATE)
        _assert_rendered_claim_link(md, "FastAPI is faster",
                                    "https://example.com/fastapi-bench")
        _assert_rendered_claim_link(md, "Flask is faster in micro-benchmarks",
                                    "https://example.com/flask-bench")

    def test_comparison_matrix_links_claim_a_and_b(self):
        md = render_cm(STATE)
        _assert_rendered_claim_link(md, "FastAPI is faster",
                                    "https://example.com/fastapi-bench")
        _assert_rendered_claim_link(md, "Flask is faster in micro-benchmarks",
                                    "https://example.com/flask-bench")

    def test_missing_url_falls_back_to_plain_text(self):
        state = {
            **STATE,
            "conflicts": [
                {**STATE["conflicts"][0], "source_a": {"url": "", "score": 8}}
            ],
        }
        md = render_www(state)
        rendered = markdown.markdown(md)
        assert 'href="https://example.com/fastapi-bench"' not in rendered
        assert "FastAPI is faster" in rendered
