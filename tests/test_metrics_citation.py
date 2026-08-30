"""Claim citation rate: precise [Source: title] coverage + anti-fabrication."""
from benchmarks.metrics import compute_claim_citation_rate, _split_sentences


def _run(recommendation, search_titles, **extra):
    fr = {
        "recommendation": recommendation,
        "winner_rationale": "",
        "ranked_options": [],
        "trade_offs": [],
        "evidence_summary": "",
        "scene_fit_note": "",
    }
    fr.update(extra)
    return {
        "final_recommendation": fr,
        "search_results": [{"results": [{"title": t, "url": "u"} for t in search_titles]}],
    }


def test_basic_rate():
    run = _run(
        "Use FastAPI. It is fast [Source: FastAPI Docs].",
        ["FastAPI Docs"],
        winner_rationale="FastAPI wins [Source: FastAPI Docs]",
        ranked_options=[{"name": "FastAPI", "rationale": "async [Source: FastAPI Docs]",
                         "key_strength": "x", "key_weakness": "y"}],
        evidence_summary="Summary [Source: FastAPI Docs]",
        scene_fit_note="fits",
    )
    out = compute_claim_citation_rate([run])
    assert out["total_claims"] == 8
    assert out["cited_claims"] == 4
    assert out["fabricated_citations"] == 0
    assert out["value"] == 0.5


def test_fabricated_citation():
    run = _run("Use X [Source: MadeUp Docs].", ["Real Docs"])
    out = compute_claim_citation_rate([run])
    assert out["total_claims"] == 1
    assert out["cited_claims"] == 0
    assert out["fabricated_citations"] == 1
    assert out["value"] == 0.0


def test_title_normalization_matches():
    run = _run("Use X [Source: FastAPI Docs].", ["FastAPI - Docs"])
    out = compute_claim_citation_rate([run])
    assert out["cited_claims"] == 1
    assert out["fabricated_citations"] == 0


def test_empty_runs():
    out = compute_claim_citation_rate([])
    assert out["value"] == 0.0
    assert out["total_claims"] == 0


def test_shortened_title_does_not_count_as_fabricated():
    # LLM often cites a shortened prefix of a real title (e.g. "What is
    # LangGraph?" for "What is LangGraph? 2026 Stateful Graph Guide").
    run = {
        "final_recommendation": {"recommendation": "Use X [Source: What is LangGraph?]."},
        "evidence_titles": ["What is LangGraph? 2026 Stateful Graph Guide"],
        "search_results": [],
    }
    out = compute_claim_citation_rate([run])
    assert out["fabricated_citations"] == 0


def test_truly_invented_title_still_counts_as_fabricated():
    run = {
        "final_recommendation": {"recommendation": "Use X [Source: Made Up Docs]."},
        "evidence_titles": ["What is LangGraph? 2026 Stateful Graph Guide"],
        "search_results": [],
    }
    out = compute_claim_citation_rate([run])
    assert out["fabricated_citations"] == 1


def test_evidence_titles_used_for_anti_fabrication():
    # Fabrication check must use the evidence-chain titles (same set the
    # synthesizer was shown), not the raw search_result titles (which the
    # source evaluator may have rewritten).
    run = {
        "final_recommendation": {"recommendation": "Use X [Source: Evidence Doc]."},
        "evidence_titles": ["Evidence Doc"],
        "search_results": [{"results": [{"title": "Different Search Title"}]}],
    }
    out = compute_claim_citation_rate([run])
    assert out["fabricated_citations"] == 0


def test_split_sentences_does_not_split_after_vs():
    # Regression: "vs." inside a [Source: ...] title must not split the claim,
    # otherwise the title is truncated ("MQTT vs.") and misjudged fabricated.
    text = "Adopt MQTT [Source: MQTT vs. CoAP: IoT Showdown]. For a team, use a broker."
    parts = _split_sentences(text)
    assert len(parts) == 2
    assert "MQTT vs. CoAP: IoT Showdown" in parts[0]


def test_multiple_sources_in_one_bracket():
    # LLM often emits [Source: A, Source: B] inside a single bracket
    run = _run("Use X [Source: FastAPI Docs, Source: Flask Docs].",
               ["FastAPI Docs", "Flask Docs"])
    out = compute_claim_citation_rate([run])
    assert out["cited_claims"] == 1
    assert out["fabricated_citations"] == 0


def test_semicolon_separated_sources():
    run = _run("Use X [Source: LangGraph Docs; Source: langgraph (PyPI)].",
               ["LangGraph Docs"])
    out = compute_claim_citation_rate([run])
    assert out["cited_claims"] == 1
    assert out["fabricated_citations"] == 1  # langgraph (PyPI) not in retrieved


def test_mixed_real_and_fake_titles():
    run = _run("Use X [Source: Real Docs, Source: Fake Docs].", ["Real Docs"])
    out = compute_claim_citation_rate([run])
    # claim has >=1 real title -> cited; 1 fake title -> fabricated
    assert out["cited_claims"] == 1
    assert out["fabricated_citations"] == 1


def test_nested_bracket_in_title():
    run = _run("Use X [Source: Bun vs Node.js: 3x Faster, Is It Ready? [2026]].",
               ["Bun vs Node.js: 3x Faster"])
    out = compute_claim_citation_rate([run])
    assert out["cited_claims"] == 1
    assert out["fabricated_citations"] == 0
