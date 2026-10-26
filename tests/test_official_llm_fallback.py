"""OfficialSearch LLM fallback: unmapped tech terms get an LLM-proposed URL,
validated (term is a host label + URL reachable) and persisted to the cache."""
import asyncio

import pytest

from deepchoice.retrievers import learned_docs
from deepchoice.retrievers import official as official_mod
from deepchoice.retrievers.learned_docs import load_learned


class _FakeFetch:
    """A bounded page-fetch seam: success returns a body, failure a nav row."""

    def __init__(self, fail_urls=(), body=None):
        self.fail_urls = fail_urls
        self.body = body
        self.called_urls = []

    async def __call__(self, url):
        self.called_urls.append(url)
        if url in self.fail_urls:
            return {"ok": False, "url": url, "error": "http:404"}
        body = self.body or f"Official page for {url} documenting the product."
        return {
            "ok": True, "url": url, "body_url": url, "title": "Official docs",
            "body": body, "source_chars": len(body),
            "stored_chars": len(body), "truncated": False,
            "bytes": len(body), "content_type": "text/html",
        }


def _patch_outbound(monkeypatch, fail_urls=()):
    """Patch the single seam that supplies a bounded official page body."""
    fake = _FakeFetch(fail_urls)

    async def fake_fetch(self, url, **kwargs):
        return await fake(url)

    monkeypatch.setattr(official_mod.OfficialSearch, "_fetch_official_body", fake_fetch)
    return fake


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.setattr(learned_docs, "LEARNED_DOCS_PATH", tmp_path / "learned.json")
    yield


async def _run_search(monkeypatch, llm_result, fail_urls=()):
    _patch_outbound(monkeypatch, fail_urls)

    async def fake_call_model(prompt, model=None, response_format=None, timeout=None, **kw):
        return llm_result

    monkeypatch.setattr(official_mod, "call_model", fake_call_model)
    retriever = official_mod.OfficialSearch()
    # Declared candidates drive the fallback; adapted query words no longer can.
    return await retriever._do_search(
        "supabase vs firebase", [], 10, ["supabase"], ["supabase", "firebase"])


class TestFallbackConcurrency:
    def test_unmapped_terms_resolve_concurrently(self, monkeypatch, tmp_path):
        monkeypatch.setattr(learned_docs, "LEARNED_DOCS_PATH", tmp_path / "learned.json")
        _patch_outbound(monkeypatch)

        entered = 0
        release = asyncio.Event()
        lock = asyncio.Lock()

        async def fake_propose(self, term, usage=None):
            nonlocal entered
            async with lock:
                entered += 1
            if entered == 1:
                await asyncio.wait_for(release.wait(), timeout=3)
            return f"https://{term}.dev/docs"

        async def fake_fetch(self, url, **kwargs):
            body = f"{url} documented body"
            return {"ok": True, "url": url, "body_url": url, "title": "docs",
                    "body": body, "source_chars": len(body),
                    "stored_chars": len(body), "truncated": False,
                    "bytes": len(body), "content_type": "text/html"}

        monkeypatch.setattr(official_mod.OfficialSearch, "_propose_official_url", fake_propose)
        monkeypatch.setattr(official_mod.OfficialSearch, "_fetch_official_body", fake_fetch)

        async def drive():
            retriever = official_mod.OfficialSearch()
            task = asyncio.create_task(
                retriever._do_search("zed vs helix", [], 10, ["zed", "helix"],
                                     ["zed", "helix"])
            )
            try:
                for _ in range(100):
                    if entered >= 2:
                        break
                    await asyncio.sleep(0.02)
                assert entered == 2, "fallback terms must be proposed concurrently"
            finally:
                release.set()
            return await task

        out = asyncio.run(drive())
        urls = [r["url"] for r in out]
        assert "https://zed.dev/docs" in urls
        assert "https://helix.dev/docs" in urls


class TestLLMFallback:
    def test_proposes_verifies_and_learns(self, monkeypatch):
        import asyncio
        out = asyncio.run(_run_search(monkeypatch, {"url": "https://supabase.com/docs"}))
        urls = [r["url"] for r in out]
        assert "https://supabase.com/docs" in urls
        assert load_learned()["supabase"]["via"] == "body_fetch"

    def test_url_not_matching_term_domain_is_rejected(self, monkeypatch):
        import asyncio
        out = asyncio.run(_run_search(monkeypatch, {"url": "https://evil.example.com/docs"}))
        urls = [r["url"] for r in out]
        assert "https://evil.example.com/docs" not in urls
        assert "supabase" not in load_learned()

    def test_unreachable_url_is_kept_only_as_navigation(self, monkeypatch):
        import asyncio
        out = asyncio.run(_run_search(
            monkeypatch, {"url": "https://supabase.com/docs"},
            fail_urls=("https://supabase.com/docs",),
        ))
        nav = [r for r in out if "supabase.com" in r["url"]]
        assert nav, out
        assert all(r["has_body"] is False for r in nav), nav
        assert all(r.get("body_error") for r in nav), nav

    def test_llm_unsure_returns_null(self, monkeypatch):
        import asyncio
        out = asyncio.run(_run_search(monkeypatch, {"url": None}))
        assert all(r["url"] != "" and "supabase" not in r["url"] for r in out)


class TestRetrievedDocumentFirst:
    def test_display_title_alias_still_finds_the_retrieved_document(self, monkeypatch):
        calls = []

        async def fake_propose(self, term, usage=None):
            calls.append(term)
            return None

        async def fake_fetch(self, url, **kwargs):
            body = "Cosign signs OCI images and stores signatures in the registry."
            return {"ok": True, "url": url, "body_url": url,
                    "title": "Cosign signing", "body": body,
                    "source_chars": len(body), "stored_chars": len(body),
                    "truncated": False, "bytes": len(body),
                    "content_type": "text/html"}

        monkeypatch.setattr(official_mod.OfficialSearch, "_propose_official_url", fake_propose)
        monkeypatch.setattr(official_mod.OfficialSearch, "_fetch_official_body", fake_fetch)
        prior = [{"source": "tavily", "status": "success", "results": [{
            "url": "https://docs.sigstore.dev/cosign/signing/overview",
            "title": "Overview - Sigstore",
            "snippet": "Cosign signing and verification overview.",
        }]}]
        out = asyncio.run(official_mod.OfficialSearch().search(
            "choose signing", [], 10, None, ["Sigstore (Cosign)"],
            prior_results=prior))
        rows = [r for r in out["results"] if "docs.sigstore.dev" in r["url"]]
        assert rows, out
        assert rows[0]["has_body"] is True
        assert rows[0]["body_identity_verified"] is True
        assert calls == [], "a retrieved page must not be replaced by a guessed URL"

    def test_candidate_page_is_fetched_before_platform_homepage(self, monkeypatch):
        fetched = []

        async def fake_propose(self, term, usage=None):
            return None

        async def fake_fetch(self, url, **kwargs):
            fetched.append(url)
            body = "Sigstore Cosign documentation."
            return {"ok": True, "url": url, "body_url": url,
                    "title": "Docs", "body": body,
                    "source_chars": len(body), "stored_chars": len(body),
                    "truncated": False, "bytes": len(body),
                    "content_type": "text/html"}

        monkeypatch.setattr(official_mod.OfficialSearch, "_propose_official_url", fake_propose)
        monkeypatch.setattr(official_mod.OfficialSearch, "_fetch_official_body", fake_fetch)
        prior = [{"source": "tavily", "status": "success", "results": [{
            "url": "https://docs.sigstore.dev/cosign/signing/overview",
            "title": "Overview - Sigstore",
            "snippet": "Cosign signing.",
        }]}]
        out = asyncio.run(official_mod.OfficialSearch().search(
            "choose signing", [], 10, None, ["Sigstore (Cosign)"],
            constraints=["生产必须使用 Kubernetes"], prior_results=prior))
        assert fetched, out
        assert "sigstore" in fetched[0], fetched

    def test_platform_page_is_not_fetched_when_another_candidate_is_missing(self, monkeypatch):
        fetched = []

        async def fake_propose(self, term, usage=None):
            return None

        async def fake_fetch(self, url, **kwargs):
            fetched.append(url)
            body = "Sigstore Cosign documentation."
            return {"ok": True, "url": url, "body_url": url,
                    "title": "Docs", "body": body,
                    "source_chars": len(body), "stored_chars": len(body),
                    "truncated": False, "bytes": len(body),
                    "content_type": "text/html"}

        monkeypatch.setattr(official_mod.OfficialSearch, "_propose_official_url", fake_propose)
        monkeypatch.setattr(official_mod.OfficialSearch, "_fetch_official_body", fake_fetch)
        prior = [{"source": "tavily", "status": "success", "results": [{
            "url": "https://docs.sigstore.dev/cosign/signing/overview",
            "title": "Overview - Sigstore",
            "snippet": "Cosign signing.",
        }]}]
        out = asyncio.run(official_mod.OfficialSearch().search(
            "choose signing", [], 10, None,
            ["Sigstore (Cosign)", "Notary Project (Notation)"],
            constraints=["生产必须使用 Kubernetes"], prior_results=prior))
        assert fetched and "sigstore" in fetched[0], fetched
        assert not any("kubernetes.io" in url for url in fetched), fetched
        assert any(r.get("body_error") == "candidate_coverage_incomplete"
                   for r in out["results"] if "kubernetes.io" in r["url"])


class TestUnifiedSourceDiscovery:
    """Candidate and platform-constraint discovery share one identity gate."""

    def test_multiword_candidate_is_not_rejected_by_full_label_equality(self, monkeypatch):
        _patch_outbound(monkeypatch)

        async def fake_propose(self, term, usage=None):
            assert term == "Kata Containers"
            return "https://katacontainers.io/docs/"

        async def fake_fetch(self, url, **kwargs):
            body = "Kata Containers documentation: each Pod runs in a virtual machine."
            return {"ok": True, "url": url, "body_url": url, "title": "Kata Containers",
                    "body": body, "source_chars": len(body), "stored_chars": len(body),
                    "truncated": False, "bytes": len(body), "content_type": "text/html"}

        monkeypatch.setattr(official_mod.OfficialSearch, "_propose_official_url", fake_propose)
        monkeypatch.setattr(official_mod.OfficialSearch, "_fetch_official_body", fake_fetch)
        out = asyncio.run(official_mod.OfficialSearch()._do_search(
            "choose a sandbox", [], 10, None, ["Kata Containers"]))
        kata = [r for r in out if "katacontainers.io" in r["url"]]
        assert kata, out
        assert kata[0]["has_body"] is True
        assert kata[0]["body_identity_verified"] is True
        assert kata[0]["source_owner"] == "Kata Containers"
        assert load_learned()["Kata Containers"]["via"] == "body_fetch"

    def test_similar_lookalike_domain_is_not_official_identity(self, monkeypatch):
        _patch_outbound(monkeypatch)
        fetched = []

        async def fake_propose(self, term, usage=None):
            return "https://katacontainers-blog.example/docs"

        async def fake_fetch(self, url, **kwargs):
            fetched.append(url)
            return {"ok": True, "url": url, "body_url": url, "title": "Kata Containers",
                    "body": "Kata Containers blog body", "source_chars": 25,
                    "stored_chars": 25, "truncated": False, "bytes": 25,
                    "content_type": "text/html"}

        monkeypatch.setattr(official_mod.OfficialSearch, "_propose_official_url", fake_propose)
        monkeypatch.setattr(official_mod.OfficialSearch, "_fetch_official_body", fake_fetch)
        out = asyncio.run(official_mod.OfficialSearch()._do_search(
            "choose a sandbox", [], 10, None, ["Kata Containers"]))
        assert out == []
        assert fetched == []
        assert "Kata Containers" not in load_learned()

    def test_url_identity_alone_is_not_enough(self, monkeypatch):
        _patch_outbound(monkeypatch)

        async def fake_propose(self, term, usage=None):
            return "https://katacontainers.io/docs"

        async def fake_fetch(self, url, **kwargs):
            return {"ok": True, "url": url, "body_url": url, "title": "Unrelated",
                    "body": "An unrelated page about something else.", "source_chars": 39,
                    "stored_chars": 39, "truncated": False, "bytes": 39,
                    "content_type": "text/html"}

        monkeypatch.setattr(official_mod.OfficialSearch, "_propose_official_url", fake_propose)
        monkeypatch.setattr(official_mod.OfficialSearch, "_fetch_official_body", fake_fetch)
        out = asyncio.run(official_mod.OfficialSearch()._do_search(
            "choose a sandbox", [], 10, None, ["Kata Containers"]))
        assert out and out[0]["has_body"] is False
        assert out[0]["body_error"] == "source_identity_unverified"
        assert "Kata Containers" not in load_learned()

    def test_learned_fragment_cannot_own_a_multiword_target(self, monkeypatch):
        """A learned one-token key is a hint, not ownership proof for EKS."""
        async def fake_fetch(self, url, **kwargs):
            return {"ok": True, "url": url, "body_url": url, "title": "Amazon SES",
                    "body": "Amazon SES is an email service.", "source_chars": 32,
                    "stored_chars": 32, "truncated": False, "bytes": 32,
                    "content_type": "text/html"}

        async def fake_propose(self, term, usage=None):
            return None

        monkeypatch.setattr(official_mod, "load_learned", lambda: {
            "amazon": {"url": "https://docs.aws.amazon.com/ses/email.html",
                       "title": "Amazon SES — Official Documentation",
                       "via": "harvest"}})
        monkeypatch.setattr(official_mod.OfficialSearch, "_fetch_official_body", fake_fetch)
        monkeypatch.setattr(official_mod.OfficialSearch, "_propose_official_url", fake_propose)
        out = asyncio.run(official_mod.OfficialSearch()._do_search(
            "choose a sandbox", [], 10, None, ["Amazon EKS"]))
        assert not [r for r in out if r.get("has_body")], out
        assert all("ses" not in r["url"] for r in out), out

    def test_lookalike_path_cannot_supply_a_prior_result(self, monkeypatch):
        async def fake_propose(self, term, usage=None):
            return None

        monkeypatch.setattr(official_mod.OfficialSearch, "_propose_official_url", fake_propose)
        prior = [{"source": "tavily", "status": "success", "results": [{
            "url": "https://kata.example.com/containers",
            "title": "Kata Containers",
            "snippet": "Kata Containers documentation.",
        }]}]
        out = asyncio.run(official_mod.OfficialSearch().search(
            "choose a sandbox", [], 10, None, ["Kata Containers"],
            prior_results=prior))
        assert not [r for r in out["results"] if "kata.example.com" in r["url"]]

    def test_prior_canonical_url_still_needs_fetched_body_identity(self, monkeypatch):
        async def fake_fetch(self, url, **kwargs):
            return {"ok": True, "url": url, "body_url": url, "title": "Unrelated",
                    "body": "This page does not name the declared product.",
                    "source_chars": 45, "stored_chars": 45, "truncated": False,
                    "bytes": 45, "content_type": "text/html"}

        async def fake_propose(self, term, usage=None):
            return None

        monkeypatch.setattr(official_mod.OfficialSearch, "_fetch_official_body", fake_fetch)
        monkeypatch.setattr(official_mod.OfficialSearch, "_propose_official_url", fake_propose)
        prior = [{"source": "tavily", "status": "success", "results": [{
            "url": "https://katacontainers.io/docs",
            "title": "Kata Containers Documentation",
            "snippet": "Kata Containers documentation.",
        }]}]
        out = asyncio.run(official_mod.OfficialSearch().search(
            "choose a sandbox", [], 10, None, ["Kata Containers"],
            prior_results=prior))
        rows = [r for r in out["results"] if "katacontainers.io" in r["url"]]
        assert rows, out
        assert rows[0]["has_body"] is False
        assert rows[0]["body_error"] == "source_identity_unverified"

    def test_one_fallback_failure_does_not_discard_other_targets(self, monkeypatch):
        _patch_outbound(monkeypatch)

        async def fake_propose(self, term, usage=None):
            if term == "Broken":
                raise RuntimeError("proposal failed")
            return f"https://{term.lower()}.dev/docs"

        async def fake_fetch(self, url, **kwargs):
            body = f"{url} documents the product."
            return {"ok": True, "url": url, "body_url": url, "title": "docs",
                    "body": body, "source_chars": len(body), "stored_chars": len(body),
                    "truncated": False, "bytes": len(body), "content_type": "text/html"}

        monkeypatch.setattr(official_mod.OfficialSearch, "_propose_official_url", fake_propose)
        monkeypatch.setattr(official_mod.OfficialSearch, "_fetch_official_body", fake_fetch)
        out = asyncio.run(official_mod.OfficialSearch()._do_search(
            "choose", [], 10, None, ["Broken", "Working"]))
        assert [r["url"] for r in out if r.get("has_body")] == [
            "https://working.dev/docs"]

    def test_platform_constraint_reuses_prior_result_and_verifies_body(self, monkeypatch):
        _patch_outbound(monkeypatch)

        async def fake_call_model(prompt, model=None, response_format=None,
                                  timeout=None, usage=None, **kw):
            if usage is not None:
                usage.append({"model": "deepseek-flash", "prompt_tokens": 10,
                              "completion_tokens": 5, "total_tokens": 15})
            return {"url": None}

        async def fake_fetch(self, url, **kwargs):
            body = "Amazon EKS managed node groups manage the Kubernetes data plane."
            return {"ok": True, "url": url, "body_url": url,
                    "title": "Amazon EKS User Guide", "body": body,
                    "source_chars": len(body), "stored_chars": len(body),
                    "truncated": False, "bytes": len(body), "content_type": "text/html"}

        monkeypatch.setattr(official_mod, "call_model", fake_call_model)
        monkeypatch.setattr(official_mod.OfficialSearch, "_fetch_official_body", fake_fetch)
        prior = [{"source": "tavily", "status": "success", "results": [{
            "url": "https://docs.gvisor.dev/docs/",
            "title": "gVisor documentation",
            "snippet": "gVisor isolates pods.",
        }, {
            "url": "https://docs.aws.amazon.com/eks/latest/userguide/what-is-eks.html",
            "title": "Amazon EKS User Guide",
            "snippet": "Amazon EKS is a managed Kubernetes service.",
        }]}]
        out = asyncio.run(official_mod.OfficialSearch().search(
            "choose a sandbox", [], 10, None, ["gVisor"],
            constraints=["生产必须运行在 Amazon EKS 上"],
            prior_results=prior))
        eks = [r for r in out["results"] if "docs.aws.amazon.com/eks" in r["url"]]
        assert eks, out
        assert eks[0]["source_owner"] == "Amazon EKS"
        assert eks[0]["source_kind"] == "platform_constraint"
        assert eks[0]["has_body"] is True
        assert eks[0]["body_identity_verified"] is True
        # One source row and a mocked fetch seam are reported separately; this
        # unit fixture does not dispatch real HTTP, so the HTTP counter is 0, not
        # the number of source rows.
        assert len(out["results"]) >= 1
        assert out["fetch_stats"]["http_requests"] == 0


class TestFallbackTokenAccounting:
    def test_official_fallback_usage_enters_the_search_envelope(self, monkeypatch):
        _patch_outbound(monkeypatch)

        async def fake_call_model(prompt, model=None, response_format=None,
                                  timeout=None, usage=None, **kw):
            if usage is not None:
                usage.append({"model": "deepseek-flash", "prompt_tokens": 17,
                              "completion_tokens": 3, "total_tokens": 20})
            return {"url": "https://supabase.com/docs"}

        monkeypatch.setattr(official_mod, "call_model", fake_call_model)
        out = asyncio.run(official_mod.OfficialSearch().search(
            "supabase vs firebase", [], 10, None, ["supabase", "firebase"]))
        rows = out.get("token_usage") or []
        assert rows and rows[0]["agent"] == "official_fallback"
        assert rows[0]["calls"] == 2
        assert rows[0]["total_tokens"] == 40
        assert len(out["results"]) >= 1


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
        _patch_outbound(monkeypatch)

        out = asyncio.run(official_mod.OfficialSearch()._do_search(
            "python vs go", [], 10, None, ["python", "go"]))
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
        _patch_outbound(monkeypatch)

        # Ordinary words are search aids, not research targets, so they must not
        # reach the fallback at all.
        out = asyncio.run(official_mod.OfficialSearch()._do_search(
            "docs", [], 10, ["docs", "code", "url"]))
        assert calls == [], f"LLM called for generic terms: {calls}"
        assert out == []


class TestNGramMatching:
    """Regression: multi-word seed keys ('aws-lambda', 'github-actions') were
    unreachable — query tokens are space-separated, so 'AWS Lambda' could
    never match the 'aws-lambda' key. N-gram normalized matching fixes it."""

    async def _search(self, query, monkeypatch, llm_calls):
        async def fake_call_model(prompt, model=None, response_format=None, timeout=None, **kw):
            llm_calls.append(prompt[-1]["content"])
            return {"url": None}
        monkeypatch.setattr(official_mod, "call_model", fake_call_model)
        _patch_outbound(monkeypatch)
        retriever = official_mod.OfficialSearch()
        return await retriever._do_search(query, [], 10, None, self._declared(query))

    @staticmethod
    def _declared(query: str) -> list[str]:
        """Declared candidates for these fixtures, split from the 'vs' query."""
        import re

        return [p.strip() for p in re.split(r"\s+vs\.?\s+", query, flags=re.IGNORECASE)
                if p.strip()]

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
        return _patch_outbound(monkeypatch)

    async def _search(self, query, monkeypatch, llm_result=None, candidate_techs=None):
        async def fake_call_model(prompt, model=None, response_format=None, timeout=None, **kw):
            return llm_result if llm_result is not None else {"url": None}
        monkeypatch.setattr(official_mod, "call_model", fake_call_model)
        retriever = official_mod.OfficialSearch()
        return await retriever._do_search(query, [], 10, None, candidate_techs or [])

    def test_scenario_query_skips_pypi(self, monkeypatch):
        import asyncio
        client = self._client_with_recorder(monkeypatch)
        asyncio.run(self._search(
            "Our team wants feature flags with gradual rollout", monkeypatch))
        assert not any("pypi.org" in u for u in client.called_urls), \
            f"PyPI called on scenario query: {client.called_urls}"

    def test_pypi_is_no_longer_a_source_of_candidates(self, monkeypatch):
        """The PyPI pass resolved candidates from ordinary query words, so a
        package name could enter the run as a research object. Candidate
        identity comes from the declared list instead."""
        import asyncio
        client = self._client_with_recorder(monkeypatch)
        asyncio.run(self._search("FastAPI vs Flask", monkeypatch,
                                 candidate_techs=["FastAPI", "Flask"]))
        assert not any("pypi.org" in u for u in client.called_urls), \
            f"PyPI still resolves candidates from query words: {client.called_urls}"

