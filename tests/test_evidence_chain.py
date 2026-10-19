from deepchoice.agents.evidence_chain import build_evidence_chain


class TestBuildEvidenceChain:
    """A retrieval hit is a source record, not a finding.

    The builder used to turn each scored result into a "conclusion" (its title)
    with an "evidence strength" derived from the metadata score, presenting a
    search result as an established judgment. The score ranks retrieval only.
    """

    def test_high_score_does_not_become_strong_evidence(self):
        scores = [{
            "url": "https://docs.example.com",
            "title": "Feature X is production-ready",
            "snippet": "Official documentation states...",
            "total_score": 8.5,
            "supporting_sources": ["https://other.com"],
        }]
        chains = build_evidence_chain(scores, [])
        assert len(chains) == 1
        assert chains[0]["evidence_strength"] == "unknown"
        assert chains[0]["conclusion"] == ""
        assert chains[0]["retrieval_score"] == 8.5
        assert chains[0]["disputed"] is False

    def test_page_fetch_provenance_travels_with_the_source(self):
        scores = [{
            "url": "https://docs.example.com", "title": "Docs",
            "snippet": "bounded body", "total_score": 8.5,
            "has_body": True, "body_url": "https://docs.example.com/canonical",
            "body_chars": 120, "body_stored_chars": 100, "body_truncated": True,
            "fetch_status": "body",
        }]
        source = build_evidence_chain(scores, [])[0]["sources"][0]
        assert source["body_url"] == "https://docs.example.com/canonical"
        assert source["body_truncated"] is True
        assert source["fetch_status"] == "body"

    def test_mid_score_does_not_become_moderate_evidence(self):
        scores = [{
            "url": "https://blog.example.com",
            "title": "Feature Y works well",
            "snippet": "Blog post about...",
            "total_score": 7.0,
            "supporting_sources": [],
        }]
        chains = build_evidence_chain(scores, [])
        assert chains[0]["evidence_strength"] == "unknown"
        assert chains[0]["retrieval_score"] == 7.0

    def test_low_score_still_records_the_retrieval_priority(self):
        scores = [{
            "url": "https://blog.example.com",
            "title": "Feature Y might work",
            "snippet": "Unclear claims...",
            "total_score": 5.0,
            "supporting_sources": [],
        }]
        chains = build_evidence_chain(scores, [])
        assert chains[0]["evidence_strength"] == "unknown"
        assert chains[0]["retrieval_score"] == 5.0

    def test_provenance_is_carried_with_the_source(self):
        scores = [{
            "url": "file:///kb/x.md",
            "title": "local doc",
            "snippet": "body",
            "total_score": 6.0,
            "supporting_sources": [],
            "provenance": "benchmark_ground_truth",
            "channel": "local_kb",
        }]
        chains = build_evidence_chain(scores, [])
        assert chains[0]["sources"][0]["provenance"] == "benchmark_ground_truth"
        assert chains[0]["sources"][0]["channel"] == "local_kb"

    def test_filters_out_very_low_scores(self):
        scores = [{
            "url": "https://spam.example.com",
            "title": "Buy now!",
            "snippet": "Spam content...",
            "total_score": 2.0,
            "supporting_sources": [],
        }]
        chains = build_evidence_chain(scores, [])
        assert len(chains) == 0

    def test_marks_disputed_from_conflicts(self):
        scores = [{
            "url": "https://contested.example.com",
            "title": "Claim X",
            "snippet": "A contested claim...",
            "total_score": 7.0,
            "supporting_sources": [],
        }]
        conflicts = [{
            "source_a": {"url": "https://contested.example.com"},
            "source_b": {"url": "https://counter.example.com"},
        }]
        chains = build_evidence_chain(scores, conflicts)
        assert chains[0]["disputed"] is True

    def test_empty_inputs(self):
        assert build_evidence_chain([], []) == []
