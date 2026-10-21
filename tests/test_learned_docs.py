"""Tests for the self-updating official-docs mapping (harvest + learned cache)."""
import json

from deepchoice.retrievers import learned_docs
from deepchoice.retrievers.learned_docs import (
    extract_terms,
    harvest,
    is_plausible_term,
    learn,
    load_learned,
)
from deepchoice.utils.candidate_identity import (
    constraint_discovery_terms,
    source_identity_verified,
    source_text_discusses_candidate,
    source_text_identity_match,
    source_url_identity_match,
)
from deepchoice.retrievers.official import TECH_DOCS


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


class TestSourceIdentity:
    def test_multiword_name_can_be_a_concatenated_host_label(self):
        assert source_url_identity_match("Kata Containers", "https://katacontainers.io/docs/")
        assert not source_url_identity_match("Kata Containers",
                                             "https://katacontainers-blog.example/docs")

    def test_platform_name_can_split_across_vendor_host_and_path(self):
        assert source_url_identity_match("Amazon EKS", "https://docs.aws.amazon.com/eks/latest/userguide/")

    def test_unrelated_domain_and_path_do_not_establish_identity(self):
        assert not source_url_identity_match("Kata Containers",
                                             "https://evil.example/katacontainers/docs")
        assert not source_url_identity_match("react", "https://myreactblog.com/post")
        assert not source_url_identity_match("react", "")

    def test_domain_match_is_not_enough_without_page_support(self):
        assert not source_text_identity_match("Kata Containers", "Unrelated blog", "nothing here")
        assert not source_identity_verified("Kata Containers", "https://katacontainers.io/docs",
                                             "Unrelated blog", "nothing here")
        assert source_identity_verified("Kata Containers", "https://katacontainers.io/docs",
                                        "Kata Containers Documentation",
                                        "Kata Containers runs each Pod in a VM.")

    def test_aliases_can_own_a_brand_domain_without_the_parenthetical(self):
        assert source_url_identity_match(
            "Sigstore (Cosign)", "https://docs.sigstore.dev/cosign/signing/overview")
        assert source_url_identity_match(
            "Notary Project (Notation)", "https://notaryproject.dev/docs/")
        assert source_text_discusses_candidate(
            "Sigstore (Cosign)", "Overview - Sigstore", "")
        assert source_text_discusses_candidate(
            "Notary Project (Notation)", "Notation CLI", "")

    def test_lookalike_host_and_path_do_not_pass(self):
        assert not source_url_identity_match(
            "Kata Containers", "https://kata.example.com/containers")
        assert not source_url_identity_match(
            "Kata Containers", "https://docs.katacontainers.io.evil.example/docs")
        assert source_url_identity_match(
            "Kata Containers", "https://docs.katacontainers.io/docs")
        assert not source_url_identity_match("GitHub", "https://someuser.github.io")
        assert not source_url_identity_match("GitHub Actions", "https://someuser.github.io/actions")
        assert not source_url_identity_match("GitHub", "https://docs.github.io/post")
        assert source_url_identity_match("GitHub", "https://docs.github.com")
        assert source_url_identity_match("GitHub Actions", "https://docs.github.com/actions")
        assert source_url_identity_match("Amazon EKS", "https://aws.amazon.com/eks")
        assert source_url_identity_match("Docker", "https://hub.docker.com")
        assert source_url_identity_match("Terraform", "https://registry.terraform.io")
        assert source_url_identity_match("Kubernetes", "https://v1-30.docs.kubernetes.io")
        assert source_url_identity_match("Kubernetes", "https://blog.kubernetes.io")


class TestConstraintDiscoveryTerms:
    def test_ordinary_sentence_capitals_are_not_platform_targets(self):
        terms = constraint_discovery_terms(
            ["Deploy the service. Support existing users. Need to ensure uptime."],
            ["gVisor", "Kata Containers"], TECH_DOCS)
        assert terms == []

    def test_explicit_platform_names_are_discovered_generically(self):
        terms = constraint_discovery_terms(
            ["生产必须运行在 Amazon EKS 和 Kubernetes 上"],
            ["gVisor", "Kata Containers"], TECH_DOCS)
        assert any("Amazon EKS" in term for term in terms), terms
        assert any(term == "Kubernetes" for term in terms), terms
        assert not any(term in terms for term in ("Deploy", "Support", "Existing"))

    def test_declared_candidates_are_not_platform_targets(self):
        terms = constraint_discovery_terms(
            ["必须在 Kata Containers 和 gVisor 之间选择"],
            ["gVisor", "Kata Containers"], TECH_DOCS)
        assert not any(term == "Kata Containers" or term == "gVisor" for term in terms)


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
             "results": [{"url": "https://supabase.com/docs", "title": "Supabase Docs"}]},
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
