"""Phase-A fetch hardening: server-side extraction fallback and real fallback targets.

The official channel fetches pages with a pinned-IP local client; some hosts are
unreachable from this machine (observed 2026-11: huggingface.co TGI docs,
raw.githubusercontent.com). Tavily fetches server-side, so a failed local fetch is
retried through extract and admitted as a labelled body. Tests here use fakes; no
network or paid call is made.
"""
import asyncio

from deepchoice.retrievers import tavily_extract
from deepchoice.retrievers import official as official_mod


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_extract_pages_returns_text_by_url(monkeypatch):
    async def fake_post_with_failover(post, payload=None, **kwargs):
        return _FakeResponse({"results": [
            {"url": "https://docs.example/a", "raw_content": "A" * 900,
             "title": "Docs A"},
            {"url": "https://docs.example/b", "content": ""},  # empty -> omitted
        ]}), "key"

    monkeypatch.setattr(tavily_extract, "post_with_failover", fake_post_with_failover)
    out = asyncio.run(tavily_extract.extract_pages(
        ["https://docs.example/a", "https://docs.example/b"]))
    assert set(out) == {"https://docs.example/a"}
    assert out["https://docs.example/a"]["title"] == "Docs A"


def test_extract_pages_returns_empty_on_api_error(monkeypatch):
    async def failing(post, payload=None, **kwargs):
        raise RuntimeError("no key")

    monkeypatch.setattr(tavily_extract, "post_with_failover", failing)
    assert asyncio.run(tavily_extract.extract_pages(["https://docs.example/a"])) == {}


def _search():
    return official_mod.OfficialSearch()


def _fallback(monkeypatch, failure, text, title="Docs"):
    async def fake_extract(urls):
        return {urls[0]: {"text": text, "title": title}}

    monkeypatch.setattr(official_mod, "extract_pages", fake_extract)
    agent = _search()
    return asyncio.run(agent._tavily_body_fallback(
        "https://docs.example/a", {"ok": False, "failure": failure}))


def test_connect_failure_gets_server_side_body(monkeypatch):
    result = _fallback(monkeypatch, "ConnectError", "prose " * 200)
    assert result is not None
    assert result["ok"] is True
    assert result["fetch_via"] == "tavily_extract"
    assert result["admission"] == "tavily_extract"
    assert result["body"]
    assert result["prose_chars"] == len(result["body_blocks"][0])


def test_non_retryable_failure_sets_no_fallback(monkeypatch):
    assert _fallback(monkeypatch, "http:404", "prose " * 200) is None


def test_short_extraction_is_rejected(monkeypatch):
    assert _fallback(monkeypatch, "timeout", "too short") is None


def test_fallback_targets_no_longer_guess_stable_latest():
    targets = official_mod._fallback_doc_targets("https://elastic.co")
    assert not any(target.rstrip("/").endswith(("/stable", "/latest"))
                   for target in targets)
    assert any("llms.txt" in target for target in targets)

def test_post_with_failover_posts_to_given_endpoint(monkeypatch):
    """Phase-A regression: /extract must not be posted to /search (silent empty)."""
    import asyncio
    from deepchoice.retrievers import tavily_keypool as kp

    calls = []

    class Resp:
        status_code = 200

    async def fake_post(url, json=None, **kw):
        calls.append((url, json))
        return Resp()

    monkeypatch.setattr(kp, "ensure_probed", lambda _post: asyncio.sleep(0))
    async def fake_current():
        return "k-test"
    monkeypatch.setattr(kp, "current", fake_current)
    async def fake_acquire(_key):
        return None
    monkeypatch.setattr(kp, "_acquire_token", fake_acquire)

    resp, key = asyncio.run(kp.post_with_failover(
        fake_post, {"urls": ["https://example.com/docs"]},
        url=kp_extract_url()))
    assert resp.status_code == 200 and key == "k-test"
    assert calls and calls[0][0] == kp_extract_url(), calls
    assert "api_key" in calls[0][1]


def kp_extract_url():
    from deepchoice.retrievers.tavily_extract import TAVILY_EXTRACT_URL
    return TAVILY_EXTRACT_URL


def test_extract_pages_uses_extract_endpoint(monkeypatch):
    """The extract module must pass TAVILY_EXTRACT_URL into the failover helper."""
    import asyncio
    from deepchoice.retrievers import tavily_extract as te

    seen = {}

    class Resp:
        status_code = 200
        def raise_for_status(self):
            return None
        def json(self):
            return {"results": [{"url": "https://example.com/docs",
                                 "raw_content": "prose " * 200,
                                 "title": "Example"}]}

    async def fake_failover(post, payload, url=None):
        seen["url"] = url
        return Resp(), "k-test"

    monkeypatch.setattr(te, "post_with_failover", fake_failover)
    out = asyncio.run(te.extract_pages(["https://example.com/docs"]))
    assert seen["url"] == te.TAVILY_EXTRACT_URL, seen
    assert out["https://example.com/docs"]["title"] == "Example"

def test_finalize_repairs_double_bracket_citation():
    """Regression: `[[Source: ...]]` must not be shredded into truncated-gap markers."""
    from deepchoice.formats.report_quality import finalize_report_text
    out = finalize_report_text("结论 [[Source: Go Fiber — Official Documentation]] 成立")
    assert "[Source: Go Fiber — Official Documentation]" in out
    assert "〔引用未解析" not in out
    # a genuinely truncated numeric citation still becomes an honest gap marker
    out2 = finalize_report_text("见 [[12")
    assert "〔引用未解析" in out2
