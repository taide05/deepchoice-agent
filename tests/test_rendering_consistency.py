"""Rendering consistency: canonical source identity, source count, labels."""
from __future__ import annotations

from deepchoice.formats.basis import (
    _canonical_source_url,
    source_provenance_note,
    used_sources,
)
from deepchoice.formats.what_why_how import render


def _binding(title, url, *, citations=1, provenance="unknown"):
    return {
        "source_id": url,
        "title": title,
        "url": url,
        "provenance": provenance,
        "channel": "tavily",
        "date": "2026-01-01",
        "source_type": "web_document",
    }


def _chain(title, url, body="Alpha and Beta are compared here."):
    return {"sources": [{
        "url": url, "title": title, "snippet": body, "has_body": True,
        "body": body, "provenance": "tavily", "channel": "tavily",
        "date": "2026-01-01", "source_type": "web_document",
    }]}


def test_canonical_url_ignores_trailing_slash_and_fragment():
    assert _canonical_source_url("https://Example.com/a/#x") == \
        "https://example.com/a"
    assert _canonical_source_url("https://example.com/a") == \
        "https://example.com/a"


def test_used_sources_merges_same_url_with_different_titles():
    url = "https://stackoverflow.com/questions/70126243/buildah-vs-kaniko"
    chains = [_chain("Buildah vs Kaniko", url)]
    rec = {
        "recommendation": "Alpha vs Beta [Source: Buildah vs Kaniko]",
        "citation_sources": {
            "recommendation": [
                _binding("Buildah vs Kaniko", url, citations=1),
                _binding("Stack Overflow — Buildah vs Kaniko", url, citations=3,
                         provenance="community"),
            ],
        },
    }
    used = used_sources(rec, chains)
    assert len(used) == 1
    assert used[0]["citations"] == 2
    assert used[0]["title"] == "Stack Overflow — Buildah vs Kaniko"


def test_official_labels_distinguish_docs_announcement_page():
    assert "官方文档" in source_provenance_note(
        {"url": "https://example.com/docs/guide", "title": "Docs guide",
         "source_type": "official_doc"}, "zh")
    assert "官方公告" in source_provenance_note(
        {"url": "https://example.com/blog/release", "title": "Release announcement",
         "source_type": "official_doc"}, "zh")
    assert "官方页面" in source_provenance_note(
        {"url": "https://example.com/", "title": "Product home",
         "source_type": "official_doc"}, "zh")


def _render_state(count: int = 13) -> dict:
    chains = []
    bindings = []
    for index in range(count):
        title = f"Alpha vs Beta source {index}"
        url = f"https://example.com/source-{index}"
        chains.append(_chain(title, url))
        bindings.append(_binding(title, url))
    return {
        "task": {"query": "Alpha vs Beta", "candidate_techs": ["Alpha", "Beta"],
                 "language": "zh", "constraints": [], "report_format": "what_why_how"},
        "sub_questions": [],
        "search_results": [],
        "source_scores": [],
        "conflicts": [],
        "evidence_chains": chains,
        "knowledge_gaps": [],
        "confidence": "medium",
        "final_recommendation": {
            "decision_status": "conditional", "winner": "",
            "recommendation": "Alpha or Beta [Source: Alpha vs Beta source 0]",
            "ranked_options": [
                {"name": "Alpha", "rationale": "Alpha [Source: Alpha vs Beta source 1]"},
                {"name": "Beta", "rationale": "Beta [Source: Alpha vs Beta source 2]"},
            ],
            "trade_offs": [], "evidence_summary": "",
            "citation_sources": {"recommendation": bindings},
        },
    }


def test_reference_list_is_not_truncated_and_matches_count():
    report = render(_render_state(13))
    assert "13 source" in report
    refs_section = report.split("References")[-1]
    bullet_lines = [line for line in refs_section.splitlines()
                    if line.startswith("- [")]
    assert len(bullet_lines) == 13
    assert "more sources" not in report

def test_verified_first_party_page_is_labelled_without_official_doc_type():
    note = source_provenance_note({
        "url": "https://example.com/docs/guide",
        "title": "Guide",
        "source_type": "web_document",
        "source_owner": "Example",
        "body_identity_verified": True,
    }, "zh")
    assert "官方" in note
