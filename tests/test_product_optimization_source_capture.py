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
    entry = SimpleNamespace(
        catalog_key="demo", url="https://docs.example.com/guide",
        title="Demo — Official Documentation", catalog_label_unverified="Official Documentation",
    )
    plan = SimpleNamespace(
        plan_id="product-optimization-official-intake-v1",
        byte_sha256="a" * 64, entries=(entry,),
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

    async def fake_fetch(source, url, **kwargs):
        calls.append((source, url, kwargs))
        return _response(body)

    monkeypatch.setattr(capture.outbound, "safe_fetch", fake_fetch)
    result = await capture.capture_official_entry("demo")
    destination = result.directory
    assert len(calls) == 1
    assert calls[0][0:2] == ("official", "https://docs.example.com/guide")
    assert calls[0][2]["max_response_bytes"] == capture.MAX_RESPONSE_BYTES
    assert calls[0][2]["allowed_content_types"] == ("text/html", "application/xhtml+xml")
    assert calls[0][2]["method"] == "GET"
    assert calls[0][2]["max_redirects"] == 3
    assert calls[0][2]["timeout_s"] == 15.0
    assert result.directory == destination
    assert destination.parent == capture.CAPTURE_ROOT
    assert (destination / "response.html").read_bytes() == body
    text = (destination / "body.txt").read_text(encoding="utf-8")
    assert text == "Reference\nPublic fact."
    assert "SECRET" not in text
    receipt_bytes = (destination / "receipt.json").read_bytes()
    receipt = json.loads(receipt_bytes)
    assert receipt["status"] == "candidate_unapproved"
    assert receipt["catalog_label_unverified"] == "Official Documentation"
    assert receipt["plan_byte_sha256"] == frozen_plan.byte_sha256
    assert receipt["raw_sha256"] == hashlib.sha256(body).hexdigest()
    assert receipt["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert result.receipt_sha256 == hashlib.sha256(receipt_bytes).hexdigest()


@pytest.mark.asyncio
async def test_unknown_key_and_wrong_root_fail_before_fetch(tmp_path, monkeypatch, frozen_plan):
    async def forbidden_fetch(*args, **kwargs):
        raise AssertionError("fetch must not be called")

    monkeypatch.setattr(capture.outbound, "safe_fetch", forbidden_fetch)
    with pytest.raises(capture.SourceCaptureError, match="not in the frozen"):
        await capture.capture_official_entry("other")
    monkeypatch.setattr(capture, "CAPTURE_ROOT", tmp_path / "docs")
    with pytest.raises(capture.SourceCaptureError, match="dedicated local output"):
        await capture.capture_official_entry("demo")


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

    monkeypatch.setattr(capture.outbound, "safe_fetch", fake_fetch)
    with pytest.raises(capture.SourceCaptureError):
        await capture.capture_official_entry("demo")
    assert not list(capture.CAPTURE_ROOT.iterdir())


@pytest.mark.asyncio
async def test_fetch_exception_does_not_include_body_in_message(tmp_path, monkeypatch, frozen_plan):
    async def broken_fetch(*args, **kwargs):
        raise RuntimeError("private upstream details")

    monkeypatch.setattr(capture.outbound, "safe_fetch", broken_fetch)
    with pytest.raises(capture.SourceCaptureError) as caught:
        await capture.capture_official_entry("demo")
    assert "private upstream details" not in str(caught.value)


@pytest.mark.asyncio
async def test_query_in_start_url_fails_before_fetch(monkeypatch, frozen_plan):
    frozen_plan.entries[0].url = "https://docs.example.com/guide?token=private"

    async def forbidden_fetch(*args, **kwargs):
        raise AssertionError("fetch must not be called")

    monkeypatch.setattr(capture.outbound, "safe_fetch", forbidden_fetch)
    with pytest.raises(capture.SourceCaptureError, match="canonical HTTPS"):
        await capture.capture_official_entry("demo")


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

    monkeypatch.setattr(capture.outbound, "safe_fetch", fake_fetch)
    monkeypatch.setattr(capture, "_write_exclusive", fail_second_write)
    with pytest.raises(capture.SourceCaptureError, match="could not be published") as caught:
        await capture.capture_official_entry("demo")
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

    monkeypatch.setattr(capture.outbound, "safe_fetch", fake_fetch)
    monkeypatch.setattr(capture.Path, "rename", reject_publish)
    with pytest.raises(capture.SourceCaptureError, match="could not be published") as caught:
        await capture.capture_official_entry("demo")
    assert "private local path" not in str(caught.value)
    assert not list(capture.CAPTURE_ROOT.iterdir())
