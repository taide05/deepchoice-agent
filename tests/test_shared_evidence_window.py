"""Synthesis and self-review must share one bounded, recorded evidence view."""
from deepchoice.agents import conclusion_synthesizer as cs
from deepchoice.agents import self_reviewer as sr
from deepchoice.agents.conclusion_synthesizer import build_source_registry
from deepchoice.utils.candidate_identity import (
    EVIDENCE_WINDOW_CHARS,
    bounded_content_summary,
    bounded_evidence_record,
)

BODY = "A" * 500 + "BACKUP-PITR-DETAIL " + "B" * 1500


def _chains():
    return [{"sources": [{
        "title": "Official docs", "url": "https://docs.example/page",
        "snippet": BODY, "date": "2026-01-01",
    }]}]


def test_shared_window_records_visible_and_total_chars():
    record = bounded_evidence_record({"title": "T", "snippet": BODY})
    assert record["source_chars"] == len(" ".join(BODY.split()))
    assert record["visible_chars"] == EVIDENCE_WINDOW_CHARS
    assert record["truncated"] is True
    assert len(record["text"]) == EVIDENCE_WINDOW_CHARS
    # The synthesis and reviewer helpers use the same record, not a second cut.
    assert bounded_content_summary({"title": "T", "snippet": BODY}) == record["text"]


def test_a_detail_beyond_the_old_600_900_windows_is_visible():
    # The saved eighth Redrock body carries the pgBackRest/backup statement at
    # offset ~1358; this generic body places a marker at the same distance.
    detail = "BACKUP-PITR-DETAIL"
    body = ("A" * 1358) + detail + ("B" * 200)
    at_default = bounded_evidence_record({"title": "T", "snippet": body})["text"]
    at_600 = bounded_content_summary({"title": "T", "snippet": body}, limit=600)
    at_900 = bounded_content_summary({"title": "T", "snippet": body}, limit=900)
    assert detail not in at_600 and detail not in at_900
    assert detail in at_default


def test_synthesis_reports_the_visible_range_in_prompt_and_audit():
    text, _mapping, audit = cs._summarize_chains(_chains(), with_audit=True)
    assert f"content_visible: {EVIDENCE_WINDOW_CHARS}/" in text, text
    assert "(truncated)" in text, text
    assert audit and audit[0]["visible_chars"] == EVIDENCE_WINDOW_CHARS
    assert audit[0]["truncated"] is True


def test_self_review_register_uses_same_window_and_audit():
    registry = build_source_registry(_chains())
    text, audit = sr._source_register_text(registry, with_audit=True)
    assert f"visible: {EVIDENCE_WINDOW_CHARS}/" in text, text
    assert "(truncated)" in text, text
    assert audit[0]["visible_chars"] == EVIDENCE_WINDOW_CHARS
    assert audit[0]["truncated"] is True
