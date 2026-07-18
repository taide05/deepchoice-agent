from deepchoice.agents.evidence_chain import build_evidence_chain


class TestBuildEvidenceChain:
    def test_strong_evidence_when_high_score_and_supporting(self):
        scores = [{
            "url": "https://docs.example.com",
            "title": "Feature X is production-ready",
            "snippet": "Official documentation states...",
            "total_score": 8.5,
            "supporting_sources": ["https://other.com"],
        }]
        chains = build_evidence_chain(scores, [])
        assert len(chains) == 1
        assert chains[0]["evidence_strength"] == "strong"
        assert chains[0]["disputed"] is False

    def test_moderate_evidence(self):
        scores = [{
            "url": "https://blog.example.com",
            "title": "Feature Y works well",
            "snippet": "Blog post about...",
            "total_score": 7.0,
            "supporting_sources": [],
        }]
        chains = build_evidence_chain(scores, [])
        assert chains[0]["evidence_strength"] == "moderate"

    def test_weak_evidence_when_low_score(self):
        scores = [{
            "url": "https://blog.example.com",
            "title": "Feature Y might work",
            "snippet": "Unclear claims...",
            "total_score": 5.0,
            "supporting_sources": [],
        }]
        chains = build_evidence_chain(scores, [])
        assert chains[0]["evidence_strength"] == "weak"

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
