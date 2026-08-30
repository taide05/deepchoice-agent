"""Claim citation rate: precise [Source: title] coverage + anti-fabrication."""
from benchmarks.metrics import compute_claim_citation_rate


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
