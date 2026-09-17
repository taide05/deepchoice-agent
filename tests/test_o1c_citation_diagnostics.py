"""Offline failure classification; no URL/error details or live calls."""
import asyncio
import json
import logging

import httpx
import pytest

from deepchoice.budget_errors import BudgetPersistenceError, StaleBudgetAuthorityError
from deepchoice.citations import verifier
from deepchoice.outbound.channels import OutboundConfig
from deepchoice.outbound.resolver import ChannelResolver
from deepchoice.outbound.throttle import ProviderAdmissionError, ProviderRateLimitError
from deepchoice.security.urls import SafeFetchFailure, SafeUrlPolicy, UnsafeUrlError


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["local-proxy", "self-forward", "none"])
async def test_route_classification_refuses_transport_without_fallback(route):
    probes = []

    async def probe(_source, channel):
        probes.append(channel.name)
        return route != "none"

    def forbidden_transport(*_args):
        pytest.fail("unsupported route must not create a target transport")

    configured = "direct" if route == "none" else route
    resolver = ChannelResolver(
        cfg=OutboundConfig(channel_order=(configured, "direct"),
                           local_proxy="http://127.0.0.1:7897",
                           fwd_base="https://relay.example/"),
        probe_fn=probe, safe_transport_factory=forbidden_transport,
    )
    with pytest.raises(UnsafeUrlError) as caught:
        await resolver.safe_fetch("official", "https://docs.example/")
    expected = SafeFetchFailure.ROUTE_UNAVAILABLE if route == "none" else SafeFetchFailure.ROUTE_UNSUPPORTED
    assert caught.value.failure is expected
    if route != "none":
        assert probes == [route]  # No implicit direct reroute.


@pytest.mark.asyncio
@pytest.mark.parametrize("answers", [[], ["93.184.216.34", "10.0.0.1"], OSError("private DNS data")])
async def test_dns_uncertainty_is_distinct_from_private_address_rejection(answers):
    async def dns(_host, _port):
        if isinstance(answers, Exception):
            raise answers
        return answers

    with pytest.raises(UnsafeUrlError) as caught:
        await SafeUrlPolicy(resolver=dns).resolve("https://docs.example/")
    expected = SafeFetchFailure.SAFETY_REJECTED if isinstance(answers, list) and answers else SafeFetchFailure.DNS_UNCERTAIN
    assert caught.value.failure is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("error, category", [
    *[(UnsafeUrlError("private error data", failure=kind), kind.value) for kind in SafeFetchFailure],
    (TimeoutError("private error data"), "timeout"),
    (httpx.ReadTimeout("private error data"), "timeout"),
    (httpx.ConnectError("private error data"), "transport_uncertain"),
    (OSError("private error data"), "transport_uncertain"),
    (ProviderRateLimitError("private error data"), "rate_limited"),
    (ProviderAdmissionError("private error data"), "admission_denied"),
    (RuntimeError("private error data"), "unexpected_error"),
])
async def test_unknown_has_fixed_log_category_and_no_raw_details(monkeypatch, caplog, error, category):
    settlements = []

    async def fetch(*_args, **_kwargs):
        raise error

    async def unknown(reservations):
        settlements.append(reservations)

    monkeypatch.setattr(verifier, "safe_fetch", fetch)
    monkeypatch.setattr(verifier, "unknown_call", unknown)
    with caplog.at_level(logging.WARNING, logger=verifier.__name__):
        result, chains = await verifier.verify_citations(
            {"winner_rationale": "Useful remote evidence. [Source: Docs]",
             "evidence_summary": "More remote evidence. [Source: Docs]"},
            [{"sources": [{"title": "Docs", "url": "https://docs.example/?private-query"}]}],
        )
    assert len(settlements) == 1  # Once per logical URL, not per claim.
    assert result.status_counts.unknown == 2
    assert all(check.reason.value == "network_uncertain" for check in result.checks)
    assert caplog.messages == [f"citation_fetch_unknown category={category}"]
    public = json.dumps(result.model_dump(mode="json"))
    assert "private error data" not in public + caplog.text
    assert "docs.example" not in caplog.text
    assert "private-query" not in caplog.text
    assert "category" not in public
    assert chains[0]["sources"][0]["verification_status"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [BudgetPersistenceError(), StaleBudgetAuthorityError(), asyncio.CancelledError()])
async def test_correctness_errors_and_cancellation_are_not_network_fallback(monkeypatch, caplog, error):
    async def fetch(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(verifier, "safe_fetch", fetch)
    with pytest.raises(type(error)):
        await verifier._fetch_one(0, "https://docs.example/")
    assert not caplog.messages


def test_legacy_unsafe_url_error_and_untrusted_category_stay_bounded():
    assert UnsafeUrlError().failure is SafeFetchFailure.SAFETY_REJECTED
    assert UnsafeUrlError().args == ()
    assert UnsafeUrlError("legacy", "detail").args == ("legacy", "detail")
    assert UnsafeUrlError("legacy message").args == ("legacy message",)
    assert UnsafeUrlError("legacy", failure="private input").failure is SafeFetchFailure.SAFETY_REJECTED


def test_previous_synthesis_prompt_revision_is_readable_but_not_resumable():
    from deepchoice.contracts.errors import DeepChoiceError
    from deepchoice.contracts.manifest import (
        RunManifest, _expected_manifest_id, build_run_manifest, ensure_run_manifest_compatible,
    )

    task = {"report_format": "what_why_how"}
    current = build_run_manifest(task)
    prompts = tuple(prompt.model_copy(update={"version": "v1"})
                    if prompt.prompt_id == "conclusion_synthesizer.synthesis_prompt" else prompt
                    for prompt in current.prompts)
    old = current.model_copy(update={"prompts": prompts})
    old = old.model_copy(update={"manifest_id": _expected_manifest_id(old)})
    restored = RunManifest.model_validate_json(old.model_dump_json())
    assert restored.manifest_id == _expected_manifest_id(restored)
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, task)
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


@pytest.mark.asyncio
async def test_synthesis_clause_instruction_does_not_auto_fill_missing_citations(monkeypatch):
    from deepchoice.agents import conclusion_synthesizer as synthesis

    async def model(prompt, **kwargs):
        content = prompt[0]["content"]
        assert "Each independent clause before AND after a semicolon" in content
        assert "never borrow a nearby citation" in content
        return {"winner": "SQLite", "recommendation": "SQLite is simple; PostgreSQL scales [[1]]."}

    monkeypatch.setattr(synthesis, "call_model", model)
    result = await synthesis.ConclusionSynthesizerAgent().run({
        "task": {"query": "SQLite vs PostgreSQL"},
        "evidence_chains": [{"sources": [{"title": "Docs", "url": "https://docs.example/"}]}],
    })
    text = result["final_recommendation"]["recommendation"]
    assert text == "SQLite is simple; PostgreSQL scales [Source: Docs]."
    claims, _ = verifier._extract_claims(result["final_recommendation"])
    assert [claim.source_title for claim in claims] == [None, "Docs"]
