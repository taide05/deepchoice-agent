"""Offline tests for the bounded page probe and downstream identity path."""
import asyncio

from deepchoice.evaluation import page_probe


def _fake_fetch(fail_urls=()):
    async def fake(url, budget, deadline_s, max_response_bytes, store_chars):
        if url in fail_urls:
            return {"ok": False, "failure": "not_prose:short_prose_only",
                    "page_role": "navigation"}
        item = next(c for c in page_probe.FROZEN_CHECKS if c["url"] == url)
        body = (f"{item['identity']} documentation. This documentation paragraph "
                "states the mechanism, conditions and consequences. " * 4)
        return {
            "ok": True, "url": url, "title": "Docs",
            "body": body, "has_body": True,
            "body_blocks": [f"{item['identity']} documentation",
                            "This documentation paragraph states the mechanism, "
                            "conditions and consequences."],
            "page_chars": len(body), "stored_chars": len(body),
            "bytes_read": len(body), "bytes_retained": len(body),
            "page_truncated": False, "stored_truncated": False,
            "page_role": "prose_document", "main_block_count": 2,
            "prose_block_count": 1, "heading_context_count": 1,
        }
    return fake


def test_probe_uses_frozen_eight_urls_and_records_consumers(tmp_path):
    result = asyncio.run(page_probe.run_probe(
        fetch_fn=_fake_fetch(), outdir=tmp_path))
    assert len(result["records"]) == 8
    assert result["page_attempts_ok"] is True
    assert result["http_requests_ok"] is True
    assert result["freeze_sha256"] == page_probe.config_sha256()
    assert (tmp_path / "page_probe_freeze.json").is_file()
    assert (tmp_path / "page_probe_result.json").is_file()
    consumers = result["consumers"]
    assert consumers["citable_entries"]
    assert all(entry["source_owner"] for entry in consumers["citable_entries"])
    assert all(entry["body_identity_verified"] is True
               for entry in consumers["citable_entries"])
    assert any(entry["fetch_status"] == "body" for entry in consumers["citable_entries"])


def test_probe_failure_is_recorded_without_retry(tmp_path):
    result = asyncio.run(page_probe.run_probe(
        fetch_fn=_fake_fetch({page_probe.FROZEN_CHECKS[0]["url"]}),
        outdir=tmp_path))
    first = result["records"][0]
    assert first["ok"] is False
    assert first["failure"].startswith("not_prose:")
    assert first["identity_verified"] is False
    assert result["budget"]["page_attempts"] == 8


def test_probe_freeze_is_hash_stable():
    assert page_probe.config_sha256() == page_probe.config_sha256()
    assert len(page_probe.frozen_config()["frozen_checks"]) == 8
    assert len({c["url"] for c in page_probe.FROZEN_CHECKS}) == 8
