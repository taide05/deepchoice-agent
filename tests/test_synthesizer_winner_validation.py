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

    def test_synthesis_prompt_has_three_step_anti_bias(self):
        assert "three-step" in cs_mod.SYNTHESIS_PROMPT
        assert "constraint-fit" in cs_mod.SYNTHESIS_PROMPT

    def test_synthesis_prompt_clarifies_established_not_mainstream(self):
        assert "established, adoptable" in cs_mod.SYNTHESIS_PROMPT
        assert "mainstream" in cs_mod.SYNTHESIS_PROMPT

    def test_synthesis_prompt_requires_verbatim_titles(self):
        assert "VERBATIM" in cs_mod.SYNTHESIS_PROMPT

    def test_synthesis_prompt_requires_every_sentence_cited(self):
        assert "EVERY sentence" in cs_mod.SYNTHESIS_PROMPT
        assert "no sentence or field may be left uncited" in cs_mod.SYNTHESIS_PROMPT

    def test_summarize_chains_includes_up_to_four_titles(self):
        chains = [{"evidence_strength": "strong", "conclusion": "c",
                   "sources": [{"title": f"T{i}"} for i in range(5)]}]
        out = cs_mod._summarize_chains(chains)
        assert "T0" in out and "T3" in out  # up to the 4th source title

    def test_synthesis_prompt_covers_all_claim_fields(self):
        assert "winner_rationale" in cs_mod.SYNTHESIS_PROMPT
        assert "key_strength" in cs_mod.SYNTHESIS_PROMPT
        assert "scene_fit_note" in cs_mod.SYNTHESIS_PROMPT


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


class TestConstraintFitValidation:
    def test_lower_fit_winner_falls_back_to_highest_fit(self):
        result = {
            "winner": "Elasticsearch",
            "ranked_options": [
                {"name": "Meilisearch", "rank": 1, "constraint_fit": "high", "rationale": "x"},
                {"name": "Elasticsearch", "rank": 2, "constraint_fit": "low", "rationale": "x"},
            ],
        }
        cs_mod._validate_constraint_fit(result)
        assert result["winner"] == "Meilisearch"

    def test_best_fit_winner_kept(self):
        result = {
            "winner": "Meilisearch",
            "ranked_options": [
                {"name": "Meilisearch", "rank": 1, "constraint_fit": "high", "rationale": "x"},
                {"name": "Elasticsearch", "rank": 2, "constraint_fit": "low", "rationale": "x"},
            ],
        }
        cs_mod._validate_constraint_fit(result)
        assert result["winner"] == "Meilisearch"

    def test_missing_constraint_fit_skips(self):
        result = {
            "winner": "Elasticsearch",
            "ranked_options": [
                {"name": "Meilisearch", "rank": 1, "rationale": "x"},
                {"name": "Elasticsearch", "rank": 2, "rationale": "x"},
            ],
        }
        cs_mod._validate_constraint_fit(result)
        assert result["winner"] == "Elasticsearch"

    def test_tied_highest_fit_keeps_winner_if_among_tied(self):
        result = {
            "winner": "Meilisearch",
            "ranked_options": [
                {"name": "Meilisearch", "rank": 1, "constraint_fit": "high", "rationale": "x"},
                {"name": "Typesense", "rank": 2, "constraint_fit": "high", "rationale": "x"},
            ],
        }
        cs_mod._validate_constraint_fit(result)
        assert result["winner"] == "Meilisearch"

    def test_run_falls_back_to_highest_fit(self, monkeypatch):
        monkeypatch.setattr(cs_mod, "call_model", _fake_call_model({
            "winner": "Elasticsearch",
            "winner_rationale": "x",
            "ranked_options": [
                {"rank": 1, "name": "Meilisearch", "constraint_fit": "high", "rationale": "x"},
                {"rank": 2, "name": "Elasticsearch", "constraint_fit": "low", "rationale": "x"},
            ],
        }))
        import asyncio
        out = asyncio.run(cs_mod.ConclusionSynthesizerAgent().run(STATE))
        assert out["final_recommendation"]["winner"] == "Meilisearch"


class TestCitationSanitization:
    def _chains(self, titles):
        return [{"sources": [{"title": t} for t in titles]}]

    def test_removes_fabricated_citation(self):
        result = {"recommendation": "Use X [Source: Fake Docs]."}
        cs_mod._sanitize_citations(result, self._chains(["Real Docs"]))
        assert "Fake Docs" not in result["recommendation"]

    def test_keeps_real_citation(self):
        result = {"recommendation": "Use X [Source: Real Docs]."}
        cs_mod._sanitize_citations(result, self._chains(["Real Docs"]))
        assert "[Source: Real Docs]" in result["recommendation"]

    def test_mixed_keeps_real_removes_fake(self):
        result = {"recommendation": "Use X [Source: Real Docs, Source: Fake Docs]."}
        cs_mod._sanitize_citations(result, self._chains(["Real Docs"]))
        assert "Real Docs" in result["recommendation"]
        assert "Fake Docs" not in result["recommendation"]

    def test_all_fabricated_removes_bracket(self):
        result = {"recommendation": "Use X [Source: Fake Docs]."}
        cs_mod._sanitize_citations(result, self._chains(["Real Docs"]))
        assert "[Source:" not in result["recommendation"]

    def test_run_sanitizes_citations(self, monkeypatch):
        monkeypatch.setattr(cs_mod, "call_model", _fake_call_model({
            "winner": "Unleash",
            "winner_rationale": "x",
            "recommendation": "Use Unleash [Source: Made Up Docs].",
            "ranked_options": [{"rank": 1, "name": "Unleash", "rationale": "x",
                                "key_strength": "x", "key_weakness": "x"}],
        }))
        import asyncio
        out = asyncio.run(cs_mod.ConclusionSynthesizerAgent().run(STATE))
        assert "Made Up Docs" not in out["final_recommendation"]["recommendation"]
