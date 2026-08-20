"""OfficialSearch LLM fallback: unmapped tech terms get an LLM-proposed URL,
validated (term is a host label + URL reachable) and persisted to the cache."""
import pytest

from deepchoice.retrievers import official as official_mod
from deepchoice.retrievers import learned_docs
from deepchoice.retrievers.learned_docs import load_learned


class _FakeResp:
    status_code = 200
    headers = {"content-type": "text/html"}

    def json(self):
        return {"info": {"version": "1.0", "summary": "s", "package_url": "https://pypi.org/project/x/"}}

    def raise_for_status(self):
        pass


class _FakeClient:
    def __init__(self, fail_urls=()):
        self.fail_urls = fail_urls
        self.called_urls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        self.called_urls.append(url)
        if url in self.fail_urls:
            return type("R", (), {"status_code": 404, "headers": {}})()
        if "pypi.org" in url:
            return _FakeResp()
        return type("R", (), {"status_code": 200, "headers": {"content-type": "text/html"}})()


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.setattr(learned_docs, "LEARNED_DOCS_PATH", tmp_path / "learned.json")
    yield


async def _run_search(monkeypatch, llm_result, fail_urls=()):
    monkeypatch.setattr(official_mod, "httpx", type("httpx", (), {
        "AsyncClient": lambda *a, **kw: _FakeClient(fail_urls),
    })())

    async def fake_call_model(prompt, model=None, response_format=None, timeout=None, **kw):
        return llm_result

    monkeypatch.setattr(official_mod, "call_model", fake_call_model)
    retriever = official_mod.OfficialSearch()
    return await retriever._do_search("supabase vs firebase", [], 10, ["supabase"])


class TestLLMFallback:
    def test_proposes_verifies_and_learns(self, monkeypatch):
        import asyncio
        out = asyncio.run(_run_search(monkeypatch, {"url": "https://supabase.com/docs"}))
        urls = [r["url"] for r in out]
        assert "https://supabase.com/docs" in urls
        assert load_learned()["supabase"]["via"] == "llm"

    def test_url_not_matching_term_domain_is_rejected(self, monkeypatch):
        import asyncio
        out = asyncio.run(_run_search(monkeypatch, {"url": "https://evil.example.com/docs"}))
        urls = [r["url"] for r in out]
        assert "https://evil.example.com/docs" not in urls
        assert "supabase" not in load_learned()

    def test_unreachable_url_is_rejected(self, monkeypatch):
        import asyncio
        out = asyncio.run(_run_search(
            monkeypatch, {"url": "https://supabase.com/docs"},
            fail_urls=("https://supabase.com/docs",),
        ))
        assert all("supabase.com" not in r["url"] for r in out)

    def test_llm_unsure_returns_null(self, monkeypatch):
        import asyncio
        out = asyncio.run(_run_search(monkeypatch, {"url": None}))
        assert all(r["url"] != "" and "supabase" not in r["url"] for r in out)


class TestSeedPrecedence:
    """Regression: a harvested entry for a term that exists in the curated
    TECH_DOCS seed must NEVER override the seed (e.g. 'python' was learned
    as python.langchain.com, shadowing the real docs.python.org)."""

    def test_seed_wins_over_learned_entry(self, monkeypatch):
        import asyncio
        monkeypatch.setattr(official_mod, "load_learned",
                            lambda: {"python": {"url": "https://python.langchain.com/docs",
                                                "title": "wrong", "via": "harvest"}})
        async def fake_call_model(prompt, model=None, response_format=None, timeout=None, **kw):
            return {"url": None}
        monkeypatch.setattr(official_mod, "call_model", fake_call_model)
        monkeypatch.setattr(official_mod, "httpx", type("httpx", (), {
            "AsyncClient": lambda *a, **kw: _FakeClient(),
        })())

        out = asyncio.run(official_mod.OfficialSearch()._do_search(
            "python vs go", [], 10, None))
        urls = [r["url"] for r in out]
        assert any("docs.python.org" in u for u in urls), urls
        assert not any("python.langchain.com" in u for u in urls)


class TestFallbackGenericFilter:
    """Regression: generic English words ('docs', 'code', 'url') must not
    trigger the LLM fallback — they are not tech names."""

    def test_generic_term_never_reaches_llm(self, monkeypatch):
        import asyncio
        calls = []
        async def fake_call_model(prompt, model=None, response_format=None, timeout=None, **kw):
            calls.append(prompt[-1]["content"])
            return {"url": None}
        monkeypatch.setattr(official_mod, "call_model", fake_call_model)
        monkeypatch.setattr(official_mod, "httpx", type("httpx", (), {
            "AsyncClient": lambda *a, **kw: _FakeClient(),
        })())

        asyncio.run(official_mod.OfficialSearch()._do_search(
            "docs", [], 10, ["docs", "code", "url"]))
        assert calls == [], f"LLM called for generic terms: {calls}"


class TestNGramMatching:
    """Regression: multi-word seed keys ('aws-lambda', 'github-actions') were
    unreachable — query tokens are space-separated, so 'AWS Lambda' could
    never match the 'aws-lambda' key. N-gram normalized matching fixes it."""

    async def _search(self, query, monkeypatch, llm_calls):
        async def fake_call_model(prompt, model=None, response_format=None, timeout=None, **kw):
            llm_calls.append(prompt[-1]["content"])
            return {"url": None}
        monkeypatch.setattr(official_mod, "call_model", fake_call_model)
        monkeypatch.setattr(official_mod, "httpx", type("httpx", (), {
            "AsyncClient": lambda *a, **kw: _FakeClient(),
        })())
        retriever = official_mod.OfficialSearch()
        return await retriever._do_search(query, [], 10, None)

    def test_space_separated_multiword_matches_seed(self, monkeypatch):
        import asyncio
        llm_calls = []
        out = asyncio.run(self._search("AWS Lambda vs Azure Functions", monkeypatch, llm_calls))
        urls = [r["url"] for r in out]
        assert any("aws.amazon.com/lambda" in u for u in urls), urls
        assert not any("for: aws" in c or "for: lambda" in c for c in llm_calls), llm_calls

    def test_hyphenated_and_dotted_multiword_match(self, monkeypatch):
        import asyncio
        llm_calls = []
        out = asyncio.run(self._search("github actions vs gitlab ci", monkeypatch, llm_calls))
        urls = [r["url"] for r in out]
        assert any("docs.github.com" in u for u in urls), urls
        assert any("docs.gitlab.com" in u for u in urls), urls

    def test_ngram_components_skip_llm_fallback(self, monkeypatch):
        import asyncio
        llm_calls = []
        asyncio.run(self._search("AWS Lambda", monkeypatch, llm_calls))
        assert llm_calls == [], f"fallback fired for n-gram components: {llm_calls}"


class TestPyPIPassRestriction:
    """Regression (open-scenario poisoning): the PyPI fallback must only run
    for vs-style comparison queries. On scenario queries, generic words like
    'feature'/'flags'/'gradual' polluted evidence chains with junk packages
    (e.g. the 'flag' PyPI package) and the synthesizer recommended them."""

    def _client_with_recorder(self, monkeypatch):
        client = _FakeClient()
        monkeypatch.setattr(official_mod, "httpx", type("httpx", (), {
            "AsyncClient": lambda *a, **kw: client,
        })())
        return client

    async def _search(self, query, monkeypatch, llm_result=None):
        async def fake_call_model(prompt, model=None, response_format=None, timeout=None, **kw):
            return llm_result if llm_result is not None else {"url": None}
        monkeypatch.setattr(official_mod, "call_model", fake_call_model)
        retriever = official_mod.OfficialSearch()
        return await retriever._do_search(query, [], 10, None)

    def test_scenario_query_skips_pypi(self, monkeypatch):
        import asyncio
        client = self._client_with_recorder(monkeypatch)
        asyncio.run(self._search(
            "Our team wants feature flags with gradual rollout", monkeypatch))
        assert not any("pypi.org" in u for u in client.called_urls), \
            f"PyPI called on scenario query: {client.called_urls}"

    def test_vs_query_still_uses_pypi(self, monkeypatch):
        import asyncio
        client = self._client_with_recorder(monkeypatch)
        asyncio.run(self._search("FastAPI vs Flask", monkeypatch))
        assert any("pypi.org" in u for u in client.called_urls)
