"""Offline tests for bounded, unapproved official-source capture."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest

from benchmarks import product_optimization_source_capture as capture


@pytest.fixture
def frozen_plan(monkeypatch, tmp_path):
    target = SimpleNamespace(
        target_id="p01-demo-guide",
        parent_catalog_key="demo",
        case_ids=("P01",),
        evidence_topics=("backup",),
        url="https://docs.example.com/guide",
        locator_label_unverified="Demo Guide",
    )
    plan = SimpleNamespace(
        plan_id="product-optimization-official-intake-v3",
        byte_sha256="a" * 64,
        canonical_plan_sha256="b" * 64,
        development_fixture_id="product-optimization-dev-requests-v1",
        targets=(target,),
    )
    monkeypatch.setattr(capture, "load_official_intake_plan", lambda: plan)
    (tmp_path / "outputs").mkdir()
    monkeypatch.setattr(capture, "ROOT", tmp_path)
    monkeypatch.setattr(capture, "CAPTURE_ROOT", tmp_path / "outputs" / "product-optimization-captures")
    return plan


def _response(body: bytes, *, url: str = "https://docs.example.com/guide", status: int = 200,
              content_type: str = "text/html; charset=utf-8") -> httpx.Response:
    return httpx.Response(
        status, request=httpx.Request("GET", url), content=body,
        headers={"content-type": content_type},
    )


@pytest.mark.asyncio
async def test_capture_uses_safe_fetch_and_writes_candidate_receipt(tmp_path, monkeypatch, frozen_plan):
    body = b"<html><body><h1>Reference</h1><script>SECRET</script><p>Public fact.</p></body></html>"
    calls = []

    async def fake_fetch(url):
        calls.append(url)
        return _response(body)

    monkeypatch.setattr(capture, "_capture_safe_fetch", fake_fetch)
    result = await capture.capture_official_target("p01-demo-guide")
    destination = result.directory
    assert len(calls) == 1
    assert calls == ["https://docs.example.com/guide"]
    assert result.directory == destination
    assert destination.parent == capture.CAPTURE_ROOT
    assert (destination / "response.html").read_bytes() == body
    text = (destination / "body.txt").read_text(encoding="utf-8")
    assert text == "Reference\nPublic fact."
    assert "SECRET" not in text
    receipt_bytes = (destination / "receipt.json").read_bytes()
    receipt = json.loads(receipt_bytes)
    assert receipt["status"] == "candidate_unapproved"
    assert receipt["target_id"] == "p01-demo-guide"
    assert receipt["parent_catalog_key"] == "demo"
    assert receipt["case_ids"] == ["P01"]
    assert receipt["evidence_topics"] == ["backup"]
    assert receipt["locator_label_unverified"] == "Demo Guide"
    assert receipt["plan_byte_sha256"] == frozen_plan.byte_sha256
    assert receipt["plan_canonical_sha256"] == frozen_plan.canonical_plan_sha256
    assert receipt["development_fixture_id"] == frozen_plan.development_fixture_id
    assert receipt["raw_sha256"] == hashlib.sha256(body).hexdigest()
    assert receipt["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert result.receipt_sha256 == hashlib.sha256(receipt_bytes).hexdigest()


@pytest.mark.asyncio
async def test_unknown_or_old_catalog_key_and_wrong_root_fail_before_fetch(
    tmp_path, monkeypatch, frozen_plan
):
    async def forbidden_fetch(*args, **kwargs):
        raise AssertionError("fetch must not be called")

    monkeypatch.setattr(capture, "_capture_safe_fetch", forbidden_fetch)
    for value in ("other", "demo"):
        with pytest.raises(capture.SourceCaptureError, match="not in the frozen"):
            await capture.capture_official_target(value)
    monkeypatch.setattr(capture, "CAPTURE_ROOT", tmp_path / "docs")
    with pytest.raises(capture.SourceCaptureError, match="dedicated local output"):
        await capture.capture_official_target("p01-demo-guide")


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    _response(b"<p>text</p>", status=404),
    _response(b"<p>text</p>", content_type="application/pdf"),
    _response(b"<p>text</p>", url="https://docs.example.com/guide?token=private"),
    _response(b"<p>text</p>", url="http://docs.example.com/guide"),
    _response(b"\xff"),
    _response(b""),
])
async def test_invalid_response_leaves_no_capture(tmp_path, monkeypatch, frozen_plan, response):
    async def fake_fetch(*args, **kwargs):
        return response

    monkeypatch.setattr(capture, "_capture_safe_fetch", fake_fetch)
    with pytest.raises(capture.SourceCaptureError):
        await capture.capture_official_target("p01-demo-guide")
    assert not list(capture.CAPTURE_ROOT.iterdir())


@pytest.mark.asyncio
async def test_fetch_exception_does_not_include_body_in_message(tmp_path, monkeypatch, frozen_plan):
    async def broken_fetch(*args, **kwargs):
        raise RuntimeError("private upstream details")

    monkeypatch.setattr(capture, "_capture_safe_fetch", broken_fetch)
    with pytest.raises(capture.SourceCaptureError) as caught:
        await capture.capture_official_target("p01-demo-guide")
    assert "private upstream details" not in str(caught.value)
    assert caught.value.failure is None


@pytest.mark.asyncio
async def test_known_safe_fetch_failure_is_preserved_as_public_category(
    monkeypatch, frozen_plan
):
    from deepchoice.security.urls import SafeFetchFailure, UnsafeUrlError

    async def broken_fetch(*args, **kwargs):
        raise UnsafeUrlError(
            "private upstream details", failure=SafeFetchFailure.ROUTE_UNSUPPORTED
        )

    monkeypatch.setattr(capture, "_capture_safe_fetch", broken_fetch)
    with pytest.raises(capture.SourceCaptureError) as caught:
        await capture.capture_official_target("p01-demo-guide")
    assert str(caught.value) == "bounded official source fetch failed"
    assert caught.value.failure == "route_unsupported"


def test_capture_resolver_uses_only_existing_direct_safe_route(monkeypatch):
    monkeypatch.setenv("OUTBOUND_CHANNELS", "local-proxy,self-forward,direct")
    monkeypatch.setenv("OUTBOUND_CHANNELS_OFFICIAL", "local-proxy,self-forward,direct")
    monkeypatch.setenv("LOCAL_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setattr(capture, "_capture_resolver", None)

    resolver = capture._get_capture_resolver()

    assert resolver.cfg.order_for("official") == ("direct",)
    assert resolver.cfg.channel_order == ("direct",)
    assert [channel.kind for channel in resolver.channels] == ["direct"]
    assert resolver.cfg.v6_enabled is False
    assert resolver._probe_fn is capture._capture_direct_probe


@pytest.mark.asyncio
async def test_capture_resolver_fetches_only_the_exact_target(monkeypatch):
    monkeypatch.setenv("OUTBOUND_CHANNELS", "direct")
    monkeypatch.setattr(capture, "_capture_resolver", None)
    resolver = capture._get_capture_resolver()
    requested = []

    async def fake_direct(url, **kwargs):  # type: ignore[no-untyped-def]
        requested.append(url)
        return _response(b"<p>Public fact.</p>", url=url)

    monkeypatch.setattr(resolver, "_safe_fetch_direct", fake_direct)
    monkeypatch.setattr(capture, "_get_capture_resolver", lambda: resolver)

    response = await capture._capture_safe_fetch("https://docs.example.com/guide")

    assert response.status_code == 200
    assert requested == ["https://docs.example.com/guide"]
    assert [(item.kind, item.channel) for item in resolver.audit] == [
        ("probe", "direct"),
        ("route", "direct"),
    ]


@pytest.mark.asyncio
async def test_capture_safe_fetch_uses_frozen_limits(monkeypatch):
    calls = []

    class FakeResolver:
        async def safe_fetch(self, source, url, **kwargs):  # type: ignore[no-untyped-def]
            calls.append((source, url, kwargs))
            return _response(b"<p>Public fact.</p>")

    monkeypatch.setattr(capture, "_get_capture_resolver", lambda: FakeResolver())
    await capture._capture_safe_fetch("https://docs.example.com/guide")

    assert calls == [(
        "official",
        "https://docs.example.com/guide",
        {
            "method": "GET",
            "allowed_content_types": ("text/html", "application/xhtml+xml"),
            "max_response_bytes": capture.MAX_RESPONSE_BYTES,
            "max_redirects": 0,
            "timeout_s": capture.CAPTURE_TIMEOUT_S,
        },
    )]
    assert capture.CAPTURE_TIMEOUT_S == 30.0


@pytest.mark.asyncio
async def test_query_in_start_url_fails_before_fetch(monkeypatch, frozen_plan):
    frozen_plan.targets[0].url = "https://docs.example.com/guide?token=private"

    async def forbidden_fetch(*args, **kwargs):
        raise AssertionError("fetch must not be called")

    monkeypatch.setattr(capture, "_capture_safe_fetch", forbidden_fetch)
    with pytest.raises(capture.SourceCaptureError, match="canonical HTTPS"):
        await capture.capture_official_target("p01-demo-guide")


@pytest.mark.asyncio
async def test_final_url_must_equal_exact_frozen_target(monkeypatch, frozen_plan):
    async def fake_fetch(*args, **kwargs):
        return _response(b"<p>Public fact.</p>", url="https://docs.example.com/other")

    monkeypatch.setattr(capture, "_capture_safe_fetch", fake_fetch)
    with pytest.raises(capture.SourceCaptureError, match="differs from the frozen target"):
        await capture.capture_official_target("p01-demo-guide")
    assert not list(capture.CAPTURE_ROOT.iterdir())


@pytest.mark.asyncio
async def test_write_failure_cleans_private_stage_and_does_not_publish(
    monkeypatch, frozen_plan
):
    async def fake_fetch(*args, **kwargs):
        return _response(b"<p>Public fact.</p>")

    writes = 0
    original = capture._write_exclusive

    def fail_second_write(path, payload):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("private local path")
        original(path, payload)

    monkeypatch.setattr(capture, "_capture_safe_fetch", fake_fetch)
    monkeypatch.setattr(capture, "_write_exclusive", fail_second_write)
    with pytest.raises(capture.SourceCaptureError, match="could not be published") as caught:
        await capture.capture_official_target("p01-demo-guide")
    assert "private local path" not in str(caught.value)
    assert not list(capture.CAPTURE_ROOT.iterdir())


@pytest.mark.asyncio
async def test_publish_rename_failure_cleans_private_stage(monkeypatch, frozen_plan):
    async def fake_fetch(*args, **kwargs):
        return _response(b"<p>Public fact.</p>")

    original_rename = capture.Path.rename

    def reject_publish(path, target):
        if path.name.startswith(".pending-"):
            raise OSError("private local path")
        return original_rename(path, target)

    monkeypatch.setattr(capture, "_capture_safe_fetch", fake_fetch)
    monkeypatch.setattr(capture.Path, "rename", reject_publish)
    with pytest.raises(capture.SourceCaptureError, match="could not be published") as caught:
        await capture.capture_official_target("p01-demo-guide")
    assert "private local path" not in str(caught.value)
    assert not list(capture.CAPTURE_ROOT.iterdir())
