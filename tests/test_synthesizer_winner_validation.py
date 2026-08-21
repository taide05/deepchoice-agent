"""Winner validation: reject repo paths and generic words, fall back to ranked options.

Regression: open-scenario cases exposed two winner-quality failures —
(a) a GitHub sample repo path returned as winner (OS-0016),
(b) a junk PyPI package name returned as winner (OS-0050).
"""
from deepchoice.agents import conclusion_synthesizer as cs_mod

STATE = {
    "task": {"query": "Our team wants feature flags with gradual rollout", "scene_context": "team"},
    "evidence_chains": [],
    "conflicts": [],
    "source_scores": [],
    "token_usage": [],
}

GENERIC_WORDS = {
    "flag", "gradual", "feature", "api", "app", "tool", "platform",
    "service", "system", "framework", "solution", "library", "package",
}


def _fake_call_model(result):
    async def fake(prompt, model=None, response_format=None, timeout=None, **kw):
        return result
    return fake


class TestPromptGuards:
    def test_synthesis_prompt_forbids_research_paper_winners(self):
        """Regression (OS-0035 FedMon): the prompt must forbid research papers
        and prototypes as winners — the code-side validator cannot detect them."""
        assert "NEVER recommend a research paper" in cs_mod.SYNTHESIS_PROMPT


class TestWinnerValidation:
    def test_repo_path_winner_falls_back_to_ranked_option(self, monkeypatch):
        monkeypatch.setattr(cs_mod, "call_model", _fake_call_model({
            "winner": "aws-samples/serverless-ticket-sentiment",
            "winner_rationale": "pre-built sample",
            "ranked_options": [
                {"rank": 1, "name": "n8n", "rationale": "visual workflows"},
                {"rank": 2, "name": "Windmill", "rationale": "code-first"},
            ],
        }))
        import asyncio
        out = asyncio.run(cs_mod.ConclusionSynthesizerAgent().run(STATE))
        assert out["final_recommendation"]["winner"] == "n8n"

    def test_generic_word_winner_falls_back(self, monkeypatch):
        monkeypatch.setattr(cs_mod, "call_model", _fake_call_model({
            "winner": "flag",
            "winner_rationale": "flag (PyPI) for feature flags",
            "ranked_options": [
                {"rank": 1, "name": "Unleash", "rationale": "open-source flags"},
            ],
        }))
        import asyncio
        out = asyncio.run(cs_mod.ConclusionSynthesizerAgent().run(STATE))
        assert out["final_recommendation"]["winner"] == "Unleash"

    def test_valid_winner_untouched(self, monkeypatch):
        monkeypatch.setattr(cs_mod, "call_model", _fake_call_model({
            "winner": "Unleash",
            "winner_rationale": "open-source feature flags",
            "ranked_options": [{"rank": 1, "name": "Unleash", "rationale": "x"}],
        }))
        import asyncio
        out = asyncio.run(cs_mod.ConclusionSynthesizerAgent().run(STATE))
        assert out["final_recommendation"]["winner"] == "Unleash"

    def test_all_ranked_invalid_keeps_winner(self, monkeypatch):
        monkeypatch.setattr(cs_mod, "call_model", _fake_call_model({
            "winner": "org/repo",
            "winner_rationale": "x",
            "ranked_options": [{"rank": 1, "name": "another/repo", "rationale": "x"}],
        }))
        import asyncio
        out = asyncio.run(cs_mod.ConclusionSynthesizerAgent().run(STATE))
        assert out["final_recommendation"]["winner"] == "org/repo"
