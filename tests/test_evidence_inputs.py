"""Round-11 evidence-input repairs: constraints, source dates, change conditions.

The seventh report omitted required constraints/version conditions and had no
explicit recommendation-reversal conditions. These tests prove the frozen
request fields and source dates reach the actual synthesis and self-review
payloads; they do not claim the model will use them correctly.
"""
import asyncio

from deepchoice.agents import conclusion_synthesizer as cs
from deepchoice.agents import self_reviewer as sr


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
