"""Tests for the deterministic decisive-claim support audit."""
import json
from pathlib import Path

from deepchoice.utils.claim_support import (
    claim_support_flags,
    decisive_claim_support,
)


def _binding(url, title="Source", source_type="official_doc"):
    return {"source_id": url, "url": url, "title": title,
            "source_type": source_type}


def test_recommended_with_official_source_is_supported():
    rec = {
        "decision_status": "recommended",
        "winner": "A",
        "citation_sources": {
            "recommendation": [_binding("https://docs.example.com/a")],
            "winner_rationale": [_binding("https://docs.example.com/a")],
            "option=A/rationale": [_binding("https://docs.example.com/a")],
        },
    }
    result = decisive_claim_support(rec)
    assert result["counts"]["primary"] == 1
    assert "recommended_no_primary" not in result["flags"]


def test_recommended_with_only_secondary_is_flagged():
    rec = {
        "decision_status": "recommended",
        "winner": "A",
        "citation_sources": {
            "recommendation": [_binding("https://blog.example.com/a", source_type="tech_blog")],
            "winner_rationale": [_binding("https://blog.example.com/a", source_type="tech_blog")],
        },
    }
    flags = claim_support_flags(rec)
    assert "recommended_no_primary" in flags
    assert "recommended_single_source" in flags


def test_same_url_is_one_decisive_source():
    rec = {
        "decision_status": "recommended",
        "winner": "A",
        "citation_sources": {
            "recommendation": [
                _binding("https://docs.example.com/a"),
                _binding("https://docs.example.com/a/"),
            ],
            "winner_rationale": [_binding("https://docs.example.com/a")],
        },
    }
    result = decisive_claim_support(rec)
    assert result["distinct_sources"] == 1


def test_conditional_without_primary_is_diagnostic_only():
    rec = {
        "decision_status": "conditional",
        "citation_sources": {
            "recommendation": [_binding("https://blog.example.com/a", source_type="tech_blog")],
        },
    }
    assert "conditional_no_primary" in claim_support_flags(rec)

def test_recommended_winner_owned_docs_dominate_is_flagged():
    rec = {
        "decision_status": "recommended",
        "winner": "Redpanda",
        "citation_sources": {
            "recommendation": [
                {"source_id": "https://docs.redpanda.com/a", "url": "https://docs.redpanda.com/a",
                 "title": "Redpanda docs", "source_type": "official_doc",
                 "source_owner": "Redpanda"},
                {"source_id": "https://docs.redpanda.com/b", "url": "https://docs.redpanda.com/b",
                 "title": "Redpanda deploy", "source_type": "official_doc",
                 "source_owner": "Redpanda"},
            ],
            "winner_rationale": [
                {"source_id": "https://docs.redpanda.com/a", "url": "https://docs.redpanda.com/a",
                 "title": "Redpanda docs", "source_type": "official_doc",
                 "source_owner": "Redpanda"},
            ],
        },
    }
    flags = claim_support_flags(rec)
    assert "recommended_winner_owner_dominates" in flags
