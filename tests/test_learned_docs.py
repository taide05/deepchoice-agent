"""Tests for the self-updating official-docs mapping (harvest + learned cache)."""
import json

from deepchoice.retrievers import learned_docs
from deepchoice.retrievers.learned_docs import (
    extract_terms,
    domain_label_match,
    harvest,
    is_plausible_term,
    learn,
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


class TestConcurrentLearn:
    def test_concurrent_learns_lose_no_updates(self, monkeypatch, tmp_path):
        import threading

        monkeypatch.setattr(learned_docs, "LEARNED_DOCS_PATH", tmp_path / "learned.json")

        def worker(i):
            learn(f"tool{i}", f"https://tool{i}.dev/docs", f"Tool {i}", via="llm")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        docs = load_learned()
        assert len(docs) == 30
        assert all(f"tool{i}" in docs for i in range(30))

    def test_atomic_write_leaves_no_tmp_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(learned_docs, "LEARNED_DOCS_PATH", tmp_path / "learned.json")

        learn("zed", "https://zed.dev/docs", "Zed", via="llm")

        leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert leftovers == []


class TestReadOnly:
    def _patch(self, monkeypatch, tmp_path):
        monkeypatch.setattr(learned_docs, "LEARNED_DOCS_PATH", tmp_path / "learned.json")
        monkeypatch.setattr(learned_docs, "_READONLY", True)

    def test_learn_readonly_does_not_write(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        learn("pinot", "https://pinot.apache.org/docs", "pinot docs", "llm")
        assert not (tmp_path / "learned.json").exists()

    def test_harvest_readonly_returns_empty(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        out = harvest(
            ["pinot"],
            [{"source": "tavily", "status": "success",
              "results": [{"url": "https://pinot.apache.org/docs",
                           "title": "Apache Pinot"}]}],
        )
        assert out == []
        assert not (tmp_path / "learned.json").exists()
