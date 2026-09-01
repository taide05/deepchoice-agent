"""Citation per-field breakdown tests (task 0.3)."""
from benchmarks.metrics import compute_citation_breakdown


def _run(case_id, fr):
    return {"case_id": case_id, "final_recommendation": fr}


def test_counts_citations_per_field():
    fr = {
        "winner": "FastAPI",
        "winner_rationale": "FastAPI wins [Source: FastAPI Benchmarks 2025]",
        "recommendation": "Use FastAPI [Source: FastAPI Benchmarks 2025] and "
                          "validate with Pydantic [Source: FastAPI — Official Documentation]",
        "evidence_summary": "",
        "scene_fit_note": "Fits solo [Source: FastAPI — Official Documentation]",
        "ranked_options": [
            {"name": "FastAPI", "rationale": "Strong [Source: FastAPI Benchmarks 2025]",
             "key_strength": "async [Source: FastAPI — Official Documentation]",
             "key_weakness": "learning curve"},
        ],
        "trade_offs": [
            {"dimension": "perf", "finding": "async faster [Source: FastAPI Benchmarks 2025]",
             "impact": "solo devs"},
        ],
    }
    out = compute_citation_breakdown([_run("TC-0001", fr)])
    fields = out["per_case"][0]["fields"]
    assert fields["recommendation"]["citations"] == 2
    assert fields["winner_rationale"]["citations"] == 1
    assert fields["evidence_summary"]["citations"] == 0
    assert fields["ranked_options[0].rationale"]["citations"] == 1
    assert fields["ranked_options[0].key_weakness"]["citations"] == 0  # uncited
    assert fields["trade_offs[0].finding"]["citations"] == 1
    assert fields["trade_offs[0].impact"]["citations"] == 0


def test_empty_recommendation_is_zeroed():
    out = compute_citation_breakdown([_run("TC-0002", {})])
    fields = out["per_case"][0]["fields"]
    assert all(v["citations"] == 0 for v in fields.values())
