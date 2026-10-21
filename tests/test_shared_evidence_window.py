"""Synthesis and self-review share one evidence package with a total budget."""
from deepchoice.agents import conclusion_synthesizer as cs
from deepchoice.agents import self_reviewer as sr
from deepchoice.agents.conclusion_synthesizer import build_source_registry
from deepchoice.utils.candidate_identity import (
    EVIDENCE_INPUT_BUDGET_CHARS,
    bounded_evidence_record,
    shared_evidence_package,
)

BODY = "A" * 500 + "BACKUP-PITR-DETAIL " + "B" * 1500


def _chains(body=BODY, title="Official docs"):
    return [{"sources": [{
        "title": title, "url": "https://docs.example/page",
        "snippet": body, "date": "2026-01-01",
    }]}]


def test_full_saved_body_is_used_when_it_fits_the_input_budget():
    record = bounded_evidence_record({"title": "T", "snippet": BODY})
    assert record["visible_chars"] == len(" ".join(BODY.split()))
    assert record["full_included"] is True
    assert record["selection_ranges"] == [(0, record["visible_chars"])]
    assert "BACKUP-PITR-DETAIL" in record["text"]


def test_a_long_saved_body_beyond_the_old_window_is_fully_included():
    # This is the ninth-run shape: 7,336 stored characters with the decisive
    # qualifier near 3,300. The full body is sent when the total package fits.
    body = "A" * 3298 + "VIRTUALIZED-HARDWARE-QUALIFIER " + "B" * 4000
    package = shared_evidence_package(
        [{"number": 1, "title": "Official docs", "url": "https://docs.example",
          "snippet": body}])
    assert package["full_included"] is True
    assert package["views"][1]["full_included"] is True
    assert "VIRTUALIZED-HARDWARE-QUALIFIER" in package["views"][1]["text"]
    assert package["visible_chars"] == len(" ".join(body.split()))


def test_over_budget_package_selects_bounded_source_ranges_with_context():
    first = "HEAD " + ("A" * 900) + " KEY-DECISION " + ("B" * 1800)
    second = "C" * 3000
    package = shared_evidence_package(
        [{"number": 1, "title": "First", "snippet": first},
         {"number": 2, "title": "Second", "snippet": second}],
        focus_terms=["KEY-DECISION"], budget_chars=2400)
    assert package["full_included"] is False
    view = package["views"][1]
    assert view["full_included"] is False
    assert "KEY-DECISION" in view["text"]
    assert view["selection_ranges"]
    assert view["omitted_chars"] > 0
    assert "chars omitted; source offsets" in view["text"]
    assert package["views"][2]["full_included"] is False
    # The package reports selection truthfully rather than pretending the
    # excerpt is the whole saved body.
    assert package["visible_chars"] < package["total_stored_chars"]


def test_page_stored_and_model_selection_are_distinct():
    record = bounded_evidence_record({
        "title": "T", "snippet": "S" * 100,
        "body_page_chars": 500, "body_stored_truncated": True,
        "body_page_truncated": False, "body_url": "https://docs.example/canonical",
    }, limit=50)
    assert record["page_chars"] == 500
    assert record["stored_chars"] == 100
    assert record["visible_chars"] <= 50
    assert record["full_included"] is False
    assert record["selection_ranges"]
    assert record["page_truncated"] is False
    assert record["stored_truncated"] is True
    assert record["truncated"] is True
    assert record["body_url"].endswith("/canonical")


def test_page_storage_provenance_reaches_both_prompts():
    chains = [{"sources": [{
        "title": "Docs", "url": "https://docs.example/page",
        "snippet": "B" * 200, "body_url": "https://docs.example/canonical",
        "body_page_chars": 900, "body_stored_chars": 200,
        "body_page_truncated": True, "body_stored_truncated": True,
    }]}]
    text, _mapping, audit = cs._summarize_chains(chains, with_audit=True)
    assert "body_url: https://docs.example/canonical" in text
    assert "page_extracted=900" in text
    assert "page_truncated=True" in text
    assert "stored_truncated=True" in text
    assert "full_text_included=True" in text
    assert audit[0]["page_chars"] == 900
    assert audit[0]["stored_chars"] == 200

    registry = build_source_registry(chains)
    review_text, review_audit = sr._source_register_text(registry, with_audit=True)
    assert "body_url: https://docs.example/canonical" in review_text
    assert "page_extracted=900" in review_text
    assert "full_text_included=True" in review_text
    assert review_audit[0]["stored_chars"] == 200


def test_synthesis_and_review_use_the_same_package_and_budget():
    package = shared_evidence_package(build_source_registry(_chains())["entries"])
    assert package["budget_chars"] == EVIDENCE_INPUT_BUDGET_CHARS

    text, _mapping, audit = cs._summarize_chains(_chains(), with_audit=True)
    assert f"content_visible: {package['visible_chars']}/" in text
    assert "full_text_included=True" in text
    assert "source_ranges=0-" in text
    assert audit[0]["visible_chars"] == package["views"][1]["visible_chars"]

    registry = build_source_registry(_chains())
    review_text, review_audit = sr._source_register_text(registry, with_audit=True)
    assert f"visible: {package['visible_chars']}/" in review_text
    assert "full_text_included=True" in review_text
    assert "source_ranges=0-" in review_text
    assert review_audit[0]["visible_chars"] == package["views"][1]["visible_chars"]
    assert review_audit[0]["selection_ranges"] == package["views"][1]["selection_ranges"]


def test_over_budget_water_fill_reuses_budget_for_large_bodies():
    entries = [
        {"number": index, "title": f"Source {index}",
         "snippet": ("H" if index == 0 else "S" * 1601)}
        for index in range(16)
    ]
    package = shared_evidence_package(entries, budget_chars=24000)
    assert package["full_included"] is False
    # Small bodies are kept whole and the remaining budget is redistributed;
    # the old equal-cut allocation would have left substantial headroom unused.
    assert package["visible_chars"] > 20000
    assert package["views"][0]["full_included"] is True


def test_focus_terms_do_not_change_which_sources_are_admitted():
    package = shared_evidence_package(
        [{"number": 1, "title": "T", "snippet": "body"}],
        focus_terms=["unrelated-focus"])
    assert package["sources"] == 1
    assert package["views"][1]["has_body"] is True
