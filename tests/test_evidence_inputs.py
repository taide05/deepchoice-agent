"""Evidence-input repairs: constraints, source dates, change conditions.

The saved seventh report records unanswered version/constraint items and no
explicit recommendation-reversal conditions. These tests prove the frozen
request fields and source dates reach the actual synthesis and self-review
payloads; they do not claim the model will use them correctly.
"""
import asyncio
import re

from deepchoice.agents import conclusion_synthesizer as cs
from deepchoice.agents import self_reviewer as sr
from deepchoice.utils import candidate_identity as cid


def _state():
    return {
        "task": {
            "query": "Gitleaks vs TruffleHog for private GitLab",
            "scene_context": "team",
            "constraints": [
                "private GitLab: 80 repos, ~100 GB history",
                "ordinary Runners must not call credential issuers",
            ],
            "candidate_techs": ["Gitleaks", "TruffleHog"],
        },
        "sub_questions": ["scan scope?", "exit codes?"],
        "evidence_chains": [{"sources": [{
            "title": "Gitleaks docs", "url": "https://example.com/gitleaks",
            "snippet": "Gitleaks scans git history.", "date": "2026-01-02",
        }]}],
        "source_scores": [],
        "conflicts": [],
        "conflict_check": {},
        "token_usage": [],
    }


class TestSynthesisInputs:
    def test_declared_constraints_reach_the_synthesis_prompt(self, monkeypatch):
        captured = {}

        async def fake_call_model(prompt, **kwargs):
            captured["payload"] = "\n".join(
                str(m.get("content", "")) for m in prompt if isinstance(m, dict))
            return {"recommendation": "x", "winner": "Gitleaks"}

        monkeypatch.setattr(cs, "call_model", fake_call_model)
        asyncio.run(cs.ConclusionSynthesizerAgent().run(_state()))
        payload = captured["payload"]
        assert "## Declared Constraints" in payload
        assert "ordinary Runners must not call credential issuers" in payload
        assert "change the recommendation" in payload

    def test_source_date_travels_with_the_source_register(self):
        text, _ = cs._summarize_chains([{"sources": [{
            "title": "Gitleaks docs", "url": "https://example.com/gitleaks",
            "snippet": "Gitleaks scans git history.", "date": "2026-01-02",
        }]}])
        assert "date: 2026-01-02" in text, text


class TestSelfReviewInputs:
    def test_declared_constraints_reach_the_review_payload(self, monkeypatch):
        state = _state()
        state["final_recommendation"] = {"recommendation": "Adopt Gitleaks [[1]]"}
        captured = {}

        async def fake_call_model(prompt, **kwargs):
            captured["payload"] = "\n".join(
                str(m.get("content", "")) for m in prompt if isinstance(m, dict))
            return {"checks": [], "passed_count": 0, "confidence": "low",
                    "knowledge_gaps": [], "corrections": []}

        monkeypatch.setattr(sr, "call_model", fake_call_model)
        asyncio.run(sr.SelfReviewerAgent().run(state))
        payload = captured["payload"]
        assert "## Declared Constraints" in payload
        assert "ordinary Runners must not call credential issuers" in payload
        assert "## Original Sub-Questions" in payload
        assert "scan scope?" in payload
        assert "exit codes?" in payload

    def test_source_register_includes_dates(self):
        registry = {"entries": [{
            "number": 1, "title": "Gitleaks docs",
            "url": "https://example.com/gitleaks", "body": "body text",
            "date": "2026-01-02",
        }], "navigation": []}
        text = sr._source_register_text(registry)
        assert "date: 2026-01-02" in text, text


def test_synthesis_and_review_agents_share_over_budget_selection(monkeypatch):
    monkeypatch.setattr(cid, "EVIDENCE_INPUT_BUDGET_CHARS", 2000)
    marker = "SUBQ-ONLY-MARKER"
    body = ("A" * 3000) + f" {marker} " + ("B" * 3000)
    state = _state()
    state["sub_questions"] = [f"What does {marker} require?"]
    state["evidence_chains"] = [{"sources": [{
        "title": "Official docs", "url": "https://example.com/docs",
        "snippet": body,
    }]}]
    captured = {}

    async def synthesis_model(prompt, **kwargs):
        captured["synthesis"] = "\n".join(
            str(m.get("content", "")) for m in prompt if isinstance(m, dict))
        return {"winner": "Gitleaks", "recommendation": "Use Gitleaks.",
                "ranked_options": [], "trade_offs": [], "evidence_summary": "",
                "confidence": "low", "confidence_rationale": "",
                "unresolved_questions": [], "scene_fit_note": ""}

    monkeypatch.setattr(cs, "call_model", synthesis_model)
    asyncio.run(cs.ConclusionSynthesizerAgent().run(dict(state)))

    review_state = dict(state)
    review_state["final_recommendation"] = {"recommendation": "Use Gitleaks [[1]]"}

    async def review_model(prompt, **kwargs):
        captured["review"] = "\n".join(
            str(m.get("content", "")) for m in prompt if isinstance(m, dict))
        return {"checks": [], "passed_count": 0, "confidence": "low",
                "knowledge_gaps": [], "corrections": []}

    monkeypatch.setattr(sr, "call_model", review_model)
    asyncio.run(sr.SelfReviewerAgent().run(review_state))

    synthesis = captured["synthesis"]
    review = captured["review"]
    assert marker in synthesis and marker in review
    syn_body = re.search(r"^\s+content: (.*)$", synthesis, re.MULTILINE).group(1)
    rev_body = re.search(r"^\s+body: (.*)$", review, re.MULTILINE).group(1)
    assert syn_body == rev_body
    syn_ranges = re.search(r"source_ranges=([^;]+);", synthesis).group(1)
    rev_ranges = re.search(r"source_ranges=([^;]+);", review).group(1)
    assert syn_ranges == rev_ranges
    assert len(syn_body) <= 2000
