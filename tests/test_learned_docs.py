"""Tests for the self-updating official-docs mapping (harvest + learned cache)."""
import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from deepchoice.budget_errors import BudgetPersistenceError, StaleBudgetAuthorityError
from deepchoice.contracts.errors import DeepChoiceError

from deepchoice.retrievers import learned_docs
from deepchoice.retrievers.learned_docs import (
    domain_label_match,
    extract_terms,
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


@pytest.fixture
def isolated_mapping(monkeypatch, tmp_path):
    path = tmp_path / "learned.json"
    monkeypatch.setattr(learned_docs, "LEARNED_DOCS_PATH", path)
    monkeypatch.setattr(learned_docs, "_READONLY", False)
    return path


def _harvest_zed(items=None):
    return harvest(["zed"], [{"source": "tavily", "status": "success", "results":
                            items or [{"url": "https://zed.dev/docs", "title": "Zed"}]}])


@pytest.mark.parametrize("raw", [
    b"{", b"[]", b"null", b"\xff", b'{"zed":null}',
    b'{"zed":{"url":123}}', b'{"zed":{"url":"https://[bad/docs"}}',
    b'{"zed":{"url":"https://zed.dev/docs","title":{}}}',
    b" " * (512 * 1024 + 1), b"[" * 1500,
], ids=["truncated", "array", "null", "encoding", "null-entry", "url-type",
        "malformed-host", "title-type", "oversized", "nested"])
def test_invalid_mapping_is_not_overwritten_or_cacheable(isolated_mapping, raw, caplog):
    isolated_mapping.write_bytes(raw)
    assert load_learned() == {}
    assert learned_docs.official_mapping_identity() is None
    assert learn("zed", "https://zed.dev/docs", "Zed", "llm") == {}
    assert _harvest_zed() == []
    assert isolated_mapping.read_bytes() == raw
    assert set(record.message for record in caplog.records) == {
        "Optional official-document learning unavailable; retrieval continues."}


def test_missing_and_legacy_url_only_mapping_keep_raw_identity(isolated_mapping):
    prefix = b"official-mapping-v1\0"
    assert learned_docs.official_mapping_identity() == hashlib.sha256(prefix + b"{}").hexdigest()
    raw = b'{ "zed": {"url":"https://zed.dev/docs"} }'
    isolated_mapping.write_bytes(raw)
    assert load_learned()["zed"]["url"] == "https://zed.dev/docs"
    assert learned_docs.official_mapping_identity() == hashlib.sha256(prefix + raw).hexdigest()
    learn("helix", "https://helix.dev/docs", "Helix", "llm")
    assert set(load_learned()) == {"zed", "helix"}


def test_read_permission_failure_preserves_file_and_hides_details(isolated_mapping, monkeypatch, caplog):
    raw = b'{"zed":{"url":"https://zed.dev/docs"}}'
    isolated_mapping.write_bytes(raw)
    original = Path.open
    def denied(path, *args, **kwargs):
        if path == isolated_mapping:
            raise PermissionError("private-path https://user:password@example.org token=secret")
        return original(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", denied)
        assert load_learned() == {}
        assert learned_docs.official_mapping_identity() is None
        assert learn("helix", "https://helix.dev/docs", "Helix", "llm") == {}
        assert _harvest_zed() == []
    assert isolated_mapping.read_bytes() == raw
    assert "private-path" not in caplog.text and "password" not in caplog.text


@pytest.mark.parametrize("operation", ["learn", "harvest"])
def test_failed_replace_preserves_original_and_cleans_only_owned_temp(
        isolated_mapping, monkeypatch, operation):
    isolated_mapping.write_bytes(b"{}")
    unrelated = isolated_mapping.with_suffix(".json.tmp")
    unrelated.write_bytes(b"unrelated")
    def denied(*args, **kwargs):
        raise PermissionError("replacement denied")
    monkeypatch.setattr(Path, "replace", denied)
    result = learn("zed", "https://zed.dev/docs", "Zed", "llm") if operation == "learn" else _harvest_zed()
    assert not result
    assert isolated_mapping.read_bytes() == b"{}"
    assert list(isolated_mapping.parent.glob("*.tmp")) == [unrelated]
    assert unrelated.read_bytes() == b"unrelated"


def test_new_mapping_cannot_exceed_read_limit(isolated_mapping, monkeypatch):
    isolated_mapping.write_bytes(b"{}")
    monkeypatch.setattr(learned_docs, "_MAX_MAPPING_BYTES", 32)
    assert learn("zed", "https://zed.dev/docs", "Zed", "llm") == {}
    assert _harvest_zed() == []
    assert isolated_mapping.read_bytes() == b"{}"


def test_harvest_skips_bad_items_and_keeps_valid_later_evidence(isolated_mapping, caplog):
    items = [{"url": url, "title": "Zed"} for url in (None, 123, "https://[bad/docs", "file:///docs",
               "https://zed.dev@evil.com/docs", "https://zed.dev:invalid/docs",
               "https://zed.dev:8080/docs")]
    items += [{"url": "https://zed.dev/docs", "title": {}},
              {"url": "https://zed.dev/docs", "title": "Zed"}]
    assert len(_harvest_zed(items)) == 1
    assert load_learned()["zed"]["title"] == "Zed"
    assert len(caplog.records) == 1


@pytest.mark.parametrize("error", [BudgetPersistenceError("budget"), StaleBudgetAuthorityError("lease"),
                                    DeepChoiceError("authority"), asyncio.CancelledError()])
@pytest.mark.parametrize("operation", ["load", "identity", "learn", "harvest"])
def test_authority_budget_and_cancellation_are_never_optional(monkeypatch, error, operation):
    def fail():
        raise error
    monkeypatch.setattr(learned_docs, "_read_mapping", fail)
    monkeypatch.setattr(learned_docs, "_READONLY", False)
    invoke = {"load": load_learned, "identity": learned_docs.official_mapping_identity,
              "learn": lambda: learn("zed", "https://zed.dev/docs", "Zed", "llm"),
              "harvest": _harvest_zed}[operation]
    with pytest.raises(type(error)) as caught:
        invoke()
    assert caught.value is error


def test_hostname_identity_does_not_borrow_userinfo():
    assert not domain_label_match("zed", "https://zed.dev@evil.com/docs")
    assert domain_label_match("zed", "https://zed.dev:443/docs")
