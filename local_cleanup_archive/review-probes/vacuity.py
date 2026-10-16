"""Vacuity experiments for the two HEAD rules in TestBodyLessSourcesAcrossEveryRoute.

Run with PYTHONPATH=<tree>\\src, cwd outside the worktree.
"""
from __future__ import annotations

import deepchoice
print("### module:", deepchoice.__file__)

import deepchoice.agents.conclusion_synthesizer as cs
from deepchoice.agents.conclusion_synthesizer import _norm_title, _sanitize_citations, _summarize_chains

NAV = {"url": "https://www.postgresql.org/docs/",
       "title": "PostgreSQL — Official Documentation",
       "snippet": "", "has_body": False, "score": 8.0}
REAL = {"url": "https://www.postgresql.org/docs/release-17",
        "title": "PostgreSQL 17 release notes",
        "snippet": "PostgreSQL 17 improves vacuum and logical replication.",
        "has_body": True, "score": 7.5}
CHAINS = [{"conclusion": "c", "evidence_strength": "strong", "disputed": False,
           "sources": [NAV, REAL]}]


def prev24_is_real_title(norm, real):
    """The implementation that shipped in 24e4b75."""
    return any(norm == rt or (len(norm) >= 8 and norm in rt) for rt in real)


def run_test5_body() -> bool:
    """Exact body of test_a_substring_title_cannot_pass_as_real."""
    try:
        result = _sanitize_citations(
            {"recommendation": "Use it [Source: PostgreSQL — Official Documentation]."},
            CHAINS)
        assert "Official Documentation" not in result["recommendation"], result
        _prompt, mapping = _summarize_chains(CHAINS, ["PostgreSQL"])
        assert NAV["title"] not in mapping.values(), mapping
        # _bind_citations with unknown/absent numbers
        from deepchoice.agents.conclusion_synthesizer import _bind_citations
        bound = _bind_citations({"recommendation": "Use it [[1]]."}, mapping)
        assert "Official Documentation" not in bound["recommendation"], bound
        assert REAL["title"] in bound["recommendation"]
        return True
    except AssertionError as e:
        print("   assertion:", str(e)[:160])
        return False


def run_test6_body() -> bool:
    """Exact body of test_renderer_source_lookup_excludes_body_less_sources."""
    from deepchoice.formats.what_why_how import _cited_sources, render
    state = {"task": {"query": "pgvector", "candidate_techs": ["PostgreSQL"]},
             "evidence_chains": [{"conclusion": "c", "evidence_strength": "strong",
                                  "disputed": False, "sources": [NAV]}],
             "conflicts": [], "knowledge_gaps": [], "final_recommendation": {},
             "confidence": "medium"}
    out = render(state)
    try:
        assert "*Sources: [PostgreSQL — Official Documentation]" not in out
        assert _cited_sources("x [Source: PostgreSQL — Official Documentation].", {}) == []
        return True
    except AssertionError as e:
        print("   assertion:", str(e)[:160])
        return False


print("== test_a_substring_title_cannot_pass_as_real ==")
print("   as written, HEAD code          :", "PASS" if run_test5_body() else "FAIL")
saved = cs._is_real_title
cs._is_real_title = prev24_is_real_title
try:
    print("   same test, 24e4b75 _is_real_title:", "PASS" if run_test5_body() else "FAIL")
finally:
    cs._is_real_title = saved
# does the test detect the substring leniency at all? build the fixture the commit
# message describes: a real title that CONTAINS the nav title.
fuller = {"url": "https://www.postgresql.org/docs/full", "has_body": True,
          "title": "PostgreSQL — Official Documentation and Release Notes",
          "snippet": "body", "score": 7.0}
cs._is_real_title = prev24_is_real_title
try:
    kept = _sanitize_citations(
        {"recommendation": "Use it [Source: PostgreSQL — Official Documentation]."},
        [{"conclusion": "c", "sources": [fuller]}])["recommendation"]
    print("   leniency reachable when fixture has a containing title:", "Official Documentation" in kept)
finally:
    cs._is_real_title = saved

print("== test_renderer_source_lookup_excludes_body_less_sources ==")
print("   as written, HEAD code          :", "PASS" if run_test6_body() else "FAIL")
from deepchoice.formats.what_why_how import _cited_sources, render
populated = {"task": {"query": "pgvector", "candidate_techs": ["PostgreSQL"]},
             "evidence_chains": [{"conclusion": "c", "evidence_strength": "strong",
                                  "disputed": False, "sources": [NAV]}],
             "conflicts": [], "knowledge_gaps": [], "confidence": "medium",
             "final_recommendation": {"ranked_options": [
                 {"name": "PostgreSQL", "rank": 1,
                  "rationale": "Use it [Source: PostgreSQL — Official Documentation]."}]}}
out = render(populated)
attached = "*Sources: [PostgreSQL — Official Documentation](https://www.postgresql.org/docs/)" in out
print("   with ranked_options populated, nav re-attached as '*Sources:' line:", attached)
print("   (state used by the test has no ranked_options/trade_offs -> that branch never runs)")
