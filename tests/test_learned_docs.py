"""Tests for the self-updating official-docs mapping (harvest + learned cache)."""
import json

from deepchoice.retrievers import learned_docs
from deepchoice.retrievers.learned_docs import (
    extract_terms,
    domain_label_match,
    harvest,
    is_plausible_term,
    load_learned,
)


class TestIsPlausibleTerm:
    def test_generic_english_words_rejected(self):
        for w in ("docs", "code", "url", "dom", "flow", "dev", "apache", "kernel"):
            assert not is_plausible_term(w), w

    def test_real_tech_names_accepted(self):
        for w in ("supabase", "liveblocks", "windmill", "yjs", "tauri"):
            assert is_plausible_term(w), w

    def test_too_short_rejected(self):
        assert not is_plausible_term("ai")
        assert not is_plausible_term("go")


class TestExtractTerms:
    def test_strips_punctuation_and_short_words(self):
        terms = extract_terms("Supabase vs Firebase, for a team!")
        assert terms == ["supabase", "firebase", "for", "team"]  # 'for' len 3 kept

    def test_drops_trailing_dots(self):
        assert "django." not in extract_terms("django. react")

    def test_keeps_dotted_tech_names(self):
        assert "next.js" in extract_terms("next.js vs nuxt")


class TestDomainLabelMatch:
    def test_full_label_match(self):
        assert domain_label_match("supabase", "https://supabase.com/docs")

    def test_substring_not_a_label_is_rejected(self):
        assert not domain_label_match("react", "https://myreactblog.com/post")

    def test_empty_url_rejected(self):
        assert not domain_label_match("react", "")


class TestHarvest:
    def _patch_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr(learned_docs, "LEARNED_DOCS_PATH", tmp_path / "learned.json")

    def test_learns_term_from_docs_signal_url(self, monkeypatch, tmp_path):
        self._patch_path(monkeypatch, tmp_path)
        results = [
            {
                "source": "tavily", "status": "success",
                "results": [
                    {"url": "https://supabase.com/docs", "title": "Supabase Docs"},
                    {"url": "https://blog.example.com/x", "title": "random"},
                ],
            },
        ]
        learned = harvest(["supabase"], results)
        assert len(learned) == 1
        assert learned[0]["term"] == "supabase"
        assert learned[0]["url"] == "https://supabase.com/docs"
        assert learned[0]["via"] == "harvest:tavily"
        assert load_learned()["supabase"]["url"] == "https://supabase.com/docs"

    def test_no_docs_signal_no_learn(self, monkeypatch, tmp_path):
        self._patch_path(monkeypatch, tmp_path)
        results = [
            {"source": "tavily", "status": "success",
             "results": [{"url": "https://supabase.com/pricing", "title": "Pricing"}]},
        ]
        assert harvest(["supabase"], results) == []
        assert load_learned() == {}

    def test_skips_already_known_terms(self, monkeypatch, tmp_path):
        self._patch_path(monkeypatch, tmp_path)
        results = [
            {"source": "tavily", "status": "success",
             "results": [{"url": "https://supabase.com/docs", "title": "Docs"}]},
        ]
        assert harvest(["supabase"], results, existing={"supabase"}) == []

    def test_persists_across_calls(self, monkeypatch, tmp_path):
        self._patch_path(monkeypatch, tmp_path)
        results = [
            {"source": "tavily", "status": "success",
             "results": [{"url": "https://supabase.com/docs", "title": "Docs"}]},
        ]
        harvest(["supabase"], results)
        loaded = json.loads((tmp_path / "learned.json").read_text(encoding="utf-8"))
        assert "supabase" in loaded

    def test_generic_words_not_learned(self, monkeypatch, tmp_path):
        """Regression: the word 'docs' matched docs.pydantic.dev via label match
        and polluted the cache; generic English words must never be learned."""
        self._patch_path(monkeypatch, tmp_path)
        results = [
            {"source": "tavily", "status": "success",
             "results": [{"url": "https://docs.pydantic.dev/latest", "title": "Pydantic docs"}]},
        ]
        assert harvest(["docs"], results) == []
        assert load_learned() == {}
