"""Bounded, deterministic citation verification without an LLM judge."""

from __future__ import annotations

import asyncio
import hashlib
import html
import ipaddress
import re
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from deepchoice.budget import (
    BudgetAmount,
    BudgetExceededError,
    BudgetResource,
    reserve_call,
    settle_call,
    unknown_call,
)
from deepchoice.outbound import safe_fetch
from deepchoice.security.urls import ALLOWED_PORTS, MAX_URL_LENGTH, UnsafeUrlError

from .contracts import (
    CITATION_POLICY_VERSION,
    CitationCheck,
    CitationReason,
    CitationStatus,
    CitationStatusCounts,
    CitationVerification,
)


MAX_UNIQUE_SOURCE_URLS = 12
MAX_FETCH_CONCURRENCY = 4
MAX_RESPONSE_BYTES = 64 * 1024
MAX_REDIRECTS = 3
FETCH_TIMEOUT_S = 15.0
MAX_CLAIM_TEXT = 500
MAX_CITATION_CHECKS = 96
MAX_FIELD_SENTENCES = 16
MAX_RANKED_OPTIONS = 20
MAX_TRADEOFFS = 20
MAX_REGISTRY_SOURCES = 96
_CITATION_PREFIX = "[source:"
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+")
_LATIN_TOKEN_RE = re.compile(r"[a-z][a-z0-9_+.#/-]*", re.IGNORECASE)
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
_NUMBER_RE = re.compile(
    r"(?<![a-z0-9])v?\d+(?:\.\d+)+(?:[-._][a-z0-9]+)?|(?<![a-z0-9])\d+(?:\.\d+)?%?",
    re.IGNORECASE,
)
_NUMBER_UNIT_RE = re.compile(
    r"(?<![a-z0-9])(v?\d+(?:\.\d+)*)\s*"
    r"(milliseconds?|msecs?|ms|seconds?|secs?|s|minutes?|mins?|hours?|hrs?|"
    r"bytes?|kb|kib|mb|mib|gb|gib|tb|tib|%|percent|x|tokens?|requests?|ops|rps|qps)"
    r"(?![a-z])",
    re.IGNORECASE,
)
_EN_NEGATIONS = frozenset(
    {"not", "no", "never", "without", "cannot", "can't", "doesn't", "isn't"}
)
_ZH_NEGATIONS = ("不支持", "不兼容", "不能", "无法", "没有", "尚未", "未能")
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "because", "by", "can",
        "for", "from", "has", "have", "in", "is", "it", "of", "on", "or",
        "that", "the", "this", "to", "use", "using", "with", "will", "would",
        "why", "than", "its", "their", "into", "more", "most", "should",
    }
)
_STATUS_PRIORITY = {
    CitationStatus.VERIFIED: 0,
    CitationStatus.UNKNOWN: 1,
    CitationStatus.UNREACHABLE: 2,
    CitationStatus.UNSUPPORTED: 3,
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


@dataclass(slots=True)
class _RegistrySource:
    position: tuple[int, int]
    title: str
    normalized_title: str
    canonical_url: str | None


@dataclass(frozen=True, slots=True)
class _Claim:
    claim_id: str
    path: str
    text: str
    source_title: str | None


@dataclass(frozen=True, slots=True)
class _FetchOutcome:
    status: CitationStatus
    reason: CitationReason
    text: str = ""


def canonicalize_source_url(value: Any) -> str | None:
    """Return a syntax-normalized public-web URL, without resolving DNS."""

    if not isinstance(value, str) or not value or len(value) > MAX_URL_LENGTH:
        return None
    if any(ord(char) < 33 or char.isspace() for char in value):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or parsed.username is not None or parsed.password is not None:
        return None
    if not parsed.hostname:
        return None
    raw_host = parsed.hostname.rstrip(".")
    try:
        host = str(ipaddress.ip_address(raw_host))
    except ValueError:
        try:
            host = raw_host.encode("idna").decode("ascii").lower()
        except UnicodeError:
            return None
        if len(host) > 253 or any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or any(not (char.isascii() and (char.isalnum() or char == "-")) for char in label)
            for label in host.split(".")
        ):
            return None
    effective_port = port or (443 if scheme == "https" else 80)
    if effective_port not in ALLOWED_PORTS:
        return None
    host_text = f"[{host}]" if ":" in host else host
    default_port = 443 if scheme == "https" else 80
    authority = host_text if effective_port == default_port else f"{host_text}:{effective_port}"
    return urlunsplit((scheme, authority, parsed.path or "/", parsed.query, ""))


def _normalize_title(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


def _bounded_plain_text(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    clean = _CONTROL_RE.sub(" ", value)
    clean = " ".join(clean.split())
    return clean[:limit].strip()


def _citation_spans(value: str) -> list[tuple[int, int, str]]:
    """Locate citation markers while allowing punctuation and nested brackets in titles."""

    lowered = value.lower()
    spans: list[tuple[int, int, str]] = []
    cursor = 0
    while True:
        start = lowered.find(_CITATION_PREFIX, cursor)
        if start < 0:
            break
        depth = 0
        end = start
        while end < len(value):
            if value[end] == "[":
                depth += 1
            elif value[end] == "]":
                depth -= 1
                if depth == 0:
                    end += 1
                    break
            end += 1
        if depth != 0:
            break
        content_start = start + len(_CITATION_PREFIX)
        spans.append((start, end, value[content_start:end - 1].strip()))
        cursor = end
    return spans


def _strip_citations(value: str) -> str:
    parts: list[str] = []
    cursor = 0
    for start, end, _ in _citation_spans(value):
        parts.append(value[cursor:start])
        parts.append(" ")
        cursor = end
    parts.append(value[cursor:])
    return _bounded_plain_text("".join(parts), limit=MAX_CLAIM_TEXT)


def _split_sentences(value: str) -> list[str]:
    """Split prose while keeping trailing citation markers with the sentence."""

    value = _CONTROL_RE.sub(" ", value).strip()
    if not value:
        return []
    output: list[str] = []
    spans = _citation_spans(value)
    by_start = {start: end for start, end, _ in spans}
    start = 0
    index = 0
    while index < len(value):
        protected_end = by_start.get(index)
        if protected_end is not None:
            index = protected_end
            continue
        if value[index] not in ".!?。！？；;":
            index += 1
            continue
        if (
            value[index] == "."
            and index > 0
            and index + 1 < len(value)
            and value[index - 1].isdigit()
            and value[index + 1].isdigit()
        ):
            index += 1
            continue
        end = index + 1
        cursor = end
        while cursor < len(value) and value[cursor].isspace():
            cursor += 1
        while cursor in by_start:
            cursor = by_start[cursor]
            while cursor < len(value) and value[cursor].isspace():
                cursor += 1
            end = cursor
        chunk = value[start:end].strip()
        if chunk:
            output.append(chunk)
        start = end
        index = end
    tail = value[start:].strip()
    if tail:
        output.append(tail)
    return output


def _iter_claim_fields(recommendation: dict[str, Any]):
    for field in (
        "winner_rationale", "recommendation", "evidence_summary",
        "confidence_rationale", "scene_fit_note",
    ):
        yield f"final_recommendation.{field}", recommendation.get(field)
    ranked_options = recommendation.get("ranked_options", [])
    if not isinstance(ranked_options, list):
        ranked_options = []
    for index, option in enumerate(ranked_options[:MAX_RANKED_OPTIONS]):
        if not isinstance(option, dict):
            continue
        for field in (
            "constraint_fit_reason", "rationale", "key_strength", "key_weakness",
        ):
            yield f"final_recommendation.ranked_options[{index}].{field}", option.get(field)
    trade_offs = recommendation.get("trade_offs", [])
    if not isinstance(trade_offs, list):
        trade_offs = []
    for index, tradeoff in enumerate(trade_offs[:MAX_TRADEOFFS]):
        if not isinstance(tradeoff, dict):
            continue
        for field in ("finding", "impact"):
            yield f"final_recommendation.trade_offs[{index}].{field}", tradeoff.get(field)


def _extract_claims(recommendation: dict[str, Any]) -> tuple[list[_Claim], bool]:
    claims: list[_Claim] = []
    ranked_options = recommendation.get("ranked_options", [])
    trade_offs = recommendation.get("trade_offs", [])
    truncated = (
        isinstance(ranked_options, list) and len(ranked_options) > MAX_RANKED_OPTIONS
    ) or (
        isinstance(trade_offs, list) and len(trade_offs) > MAX_TRADEOFFS
    )
    for path, value in _iter_claim_fields(recommendation):
        if not isinstance(value, str) or not value.strip():
            continue
        sentences = _split_sentences(value)
        if len(sentences) > MAX_FIELD_SENTENCES:
            truncated = True
        for sentence_index, sentence in enumerate(sentences[:MAX_FIELD_SENTENCES]):
            claim_text = _strip_citations(sentence)
            if not claim_text:
                continue
            digest = hashlib.sha256(
                f"{path}\x00{sentence_index}\x00{claim_text}".encode("utf-8")
            ).hexdigest()[:20]
            raw_titles = [
                title.strip()
                for _, _, marker in _citation_spans(sentence)
                for title in re.split(r",\s*Source:\s*|;\s*Source:\s*", marker, flags=re.IGNORECASE)
                if title.strip()
            ]
            if not raw_titles:
                if len(claims) >= MAX_CITATION_CHECKS - 1:
                    truncated = True
                    continue
                claims.append(_Claim(f"claim-{digest}", path, claim_text, None))
                continue
            for title in raw_titles:
                if len(claims) >= MAX_CITATION_CHECKS - 1:
                    truncated = True
                    continue
                claims.append(
                    _Claim(
                        f"claim-{digest}",
                        path,
                        claim_text,
                        _bounded_plain_text(title, limit=300),
                    )
                )
    return claims, truncated


def _source_registry(
    evidence_chains: list[dict[str, Any]],
) -> tuple[list[_RegistrySource], bool]:
    output: list[_RegistrySource] = []
    for chain_index, chain in enumerate(evidence_chains):
        if not isinstance(chain, dict):
            continue
        sources = chain.get("sources", [])
        if not isinstance(sources, list):
            continue
        for source_index, source in enumerate(sources):
            if not isinstance(source, dict):
                continue
            if len(output) >= MAX_REGISTRY_SOURCES:
                return output, True
            title = _bounded_plain_text(source.get("title"), limit=300)
            output.append(
                _RegistrySource(
                    position=(chain_index, source_index),
                    title=title,
                    normalized_title=_normalize_title(title),
                    canonical_url=canonicalize_source_url(source.get("url")),
                )
            )
    return output, False


def _resolve_title(title: str, registry: list[_RegistrySource]) -> tuple[_RegistrySource | None, CitationReason | None]:
    normalized = _normalize_title(title)
    if not normalized:
        return None, CitationReason.SOURCE_NOT_FOUND
    exact = [source for source in registry if source.normalized_title == normalized]
    matches = exact or [
        source for source in registry
        if len(normalized) >= 8 and normalized in source.normalized_title
    ]
    if not matches:
        return None, CitationReason.SOURCE_NOT_FOUND
    identities = {source.canonical_url for source in matches}
    if len(identities) > 1:
        return None, CitationReason.SOURCE_AMBIGUOUS
    return matches[0], None


def _html_to_text(value: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        return _bounded_plain_text(html.unescape(value), limit=MAX_RESPONSE_BYTES)
    return _bounded_plain_text(" ".join(parser.parts), limit=MAX_RESPONSE_BYTES)


def _tokens(value: str) -> set[str]:
    lowered = value.casefold()
    latin: set[str] = set()
    for raw_token in _LATIN_TOKEN_RE.findall(lowered):
        token = raw_token.strip("./-")
        if token in _STOPWORDS or token in _EN_NEGATIONS or len(token) <= 1:
            continue
        # This is intentionally only a tiny English inflection normalizer,
        # not semantic stemming: it lets "support" match "supports" while
        # keeping the verifier deterministic and explainable.
        if token.endswith("s") and len(token) > 4 and not token.endswith("ss"):
            token = token[:-1]
        latin.add(token)
    cjk: set[str] = set()
    for sequence in _CJK_RE.findall(lowered):
        if len(sequence) == 1:
            cjk.add(sequence)
        else:
            cjk.update(sequence[index:index + 2] for index in range(len(sequence) - 1))
    return latin | cjk


def _has_negation(value: str) -> bool:
    lowered = value.casefold()
    # "not only" is additive, not a denial.  Bare Chinese characters such as
    # 未/无 are deliberately excluded because they occur in ordinary words.
    lowered = re.sub(r"\bnot\s+only\b", "", lowered)
    return any(
        re.search(rf"\b{re.escape(negation)}\b", lowered) is not None
        for negation in _EN_NEGATIONS
    ) or any(
        phrase in lowered for phrase in _ZH_NEGATIONS
    )


def _number_units(value: str) -> set[tuple[str, str]]:
    unit_groups = {
        "millisecond": "ms", "milliseconds": "ms", "msec": "ms", "msecs": "ms", "ms": "ms",
        "second": "s", "seconds": "s", "sec": "s", "secs": "s", "s": "s",
        "minute": "min", "minutes": "min", "min": "min", "mins": "min",
        "hour": "h", "hours": "h", "hr": "h", "hrs": "h",
        "byte": "b", "bytes": "b", "kb": "kb", "kib": "kib", "mb": "mb",
        "mib": "mib", "gb": "gb", "gib": "gib", "tb": "tb", "tib": "tib",
        "%": "%", "percent": "%", "x": "x", "token": "token", "tokens": "token",
        "request": "request", "requests": "request", "op": "ops", "ops": "ops",
        "rps": "rps", "qps": "qps",
    }
    return {
        (number.casefold(), unit_groups[unit.casefold()])
        for number, unit in _NUMBER_UNIT_RE.findall(value)
    }


def _language_is_crossed(claim: str, evidence: str) -> bool:
    claim_cjk = len("".join(_CJK_RE.findall(claim)))
    evidence_cjk = len("".join(_CJK_RE.findall(evidence)))
    claim_latin = sum(len(token) for token in _LATIN_TOKEN_RE.findall(claim))
    evidence_latin = sum(len(token) for token in _LATIN_TOKEN_RE.findall(evidence))
    if claim_cjk >= 4 and evidence_cjk == 0:
        return True
    return claim_latin >= 12 and claim_cjk == 0 and evidence_latin == 0 and evidence_cjk >= 8


def _support_status(claim: str, evidence: str) -> tuple[CitationStatus, CitationReason]:
    claim_numbers = {item.casefold() for item in _NUMBER_RE.findall(claim)}
    evidence_numbers = {item.casefold() for item in _NUMBER_RE.findall(evidence)}
    if claim_numbers - evidence_numbers:
        return CitationStatus.UNSUPPORTED, CitationReason.NUMERIC_MISMATCH
    if _number_units(claim) - _number_units(evidence):
        return CitationStatus.UNSUPPORTED, CitationReason.NUMERIC_MISMATCH

    claim_tokens = _tokens(claim)
    evidence_tokens = _tokens(evidence)
    if not claim_tokens or len(evidence_tokens) < 2:
        return CitationStatus.UNKNOWN, CitationReason.CONTENT_INSUFFICIENT
    if _language_is_crossed(claim, evidence):
        return CitationStatus.UNKNOWN, CitationReason.CROSS_LANGUAGE

    for sentence in re.split(r"[.!?。！？；;\n]+", evidence):
        sentence_tokens = _tokens(sentence)
        if not sentence_tokens:
            continue
        overlap = len(claim_tokens & sentence_tokens) / len(claim_tokens)
        if overlap >= 0.6 and _has_negation(claim) != _has_negation(sentence):
            return CitationStatus.UNSUPPORTED, CitationReason.NEGATION_CONFLICT

    matched = len(claim_tokens & evidence_tokens)
    overlap = matched / len(claim_tokens)
    if overlap >= 0.55 and (matched >= 2 or len(claim_tokens) == 1):
        return CitationStatus.VERIFIED, CitationReason.LEXICAL_SUPPORT
    if len(evidence) < 80:
        return CitationStatus.UNKNOWN, CitationReason.CONTENT_INSUFFICIENT
    return CitationStatus.UNSUPPORTED, CitationReason.LEXICAL_MISMATCH


async def _fetch_one(index: int, url: str) -> _FetchOutcome:
    reservations = await reserve_call(
        (BudgetAmount(resource=BudgetResource.HTTP_CALLS, amount=1),),
        # Citation HTTP fetches are not Trace ``external_calls`` rows, so the
        # nullable FK must remain NULL.  The safe ordinal lives only in the
        # budget summary.
        call_id=None,
        summary={"kind": "citation_verification", "citation_index": index + 1},
    )
    try:
        response = await safe_fetch(
            "official",
            url,
            method="GET",
            allowed_content_types=("text/html", "application/xhtml+xml", "text/plain"),
            max_response_bytes=MAX_RESPONSE_BYTES,
            max_redirects=MAX_REDIRECTS,
            timeout_s=FETCH_TIMEOUT_S,
        )
    except BudgetExceededError:
        raise
    except asyncio.CancelledError:
        await unknown_call(reservations)
        raise
    except (UnsafeUrlError, TimeoutError, OSError):
        await unknown_call(reservations)
        return _FetchOutcome(CitationStatus.UNKNOWN, CitationReason.NETWORK_UNCERTAIN)
    except Exception:
        await unknown_call(reservations)
        return _FetchOutcome(CitationStatus.UNKNOWN, CitationReason.NETWORK_UNCERTAIN)

    await settle_call(reservations, {BudgetResource.HTTP_CALLS: 1})
    status_code = response.status_code
    if 200 <= status_code < 300:
        return _FetchOutcome(
            CitationStatus.VERIFIED,
            CitationReason.LEXICAL_SUPPORT,
            _html_to_text(response.text),
        )
    if status_code in {401, 403, 404, 410}:
        return _FetchOutcome(
            CitationStatus.UNREACHABLE,
            CitationReason.NOT_PUBLICLY_ACCESSIBLE,
        )
    return _FetchOutcome(CitationStatus.UNKNOWN, CitationReason.HTTP_UNCERTAIN)


async def _fetch_sources(urls: list[str]) -> dict[str, _FetchOutcome]:
    semaphore = asyncio.Semaphore(MAX_FETCH_CONCURRENCY)

    async def _limited(index: int, url: str) -> tuple[str, _FetchOutcome]:
        async with semaphore:
            return url, await _fetch_one(index, url)

    tasks = [
        asyncio.create_task(_limited(index, url))
        for index, url in enumerate(urls)
    ]
    try:
        results = await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return dict(results)


def _make_check(
    claim: _Claim,
    *,
    source: _RegistrySource | None,
    status: CitationStatus,
    reason: CitationReason,
) -> CitationCheck:
    return CitationCheck(
        claim_id=claim.claim_id,
        claim_path=claim.path,
        claim_text=claim.text,
        source_title=claim.source_title,
        canonical_url=source.canonical_url if source is not None else None,
        status=status,
        reason=reason,
    )


async def verify_citations(
    recommendation: dict[str, Any],
    evidence_chains: list[dict[str, Any]],
) -> tuple[CitationVerification, list[dict[str, Any]]]:
    """Verify cited critical claims and project aggregate status onto sources."""

    registry, registry_truncated = _source_registry(evidence_chains)
    claims, claims_truncated = _extract_claims(recommendation)
    resolved: list[tuple[_Claim, _RegistrySource | None, CitationReason | None]] = []
    for claim in claims:
        if claim.source_title is None:
            resolved.append((claim, None, CitationReason.CITATION_MISSING))
        else:
            source, error = _resolve_title(claim.source_title, registry)
            if registry_truncated and error is CitationReason.SOURCE_NOT_FOUND:
                error = CitationReason.SOURCE_LIMIT
            resolved.append((claim, source, error))

    unique_urls: list[str] = []
    for _, source, error in resolved:
        if error is None and source is not None and source.canonical_url is not None:
            if source.canonical_url not in unique_urls:
                unique_urls.append(source.canonical_url)
    admitted_urls = unique_urls[:MAX_UNIQUE_SOURCE_URLS]
    outcomes = await _fetch_sources(admitted_urls)

    checks: list[CitationCheck] = []
    aggregate: dict[tuple[int, int], tuple[CitationStatus, CitationReason]] = {}
    for claim, source, error in resolved:
        if error is CitationReason.SOURCE_LIMIT:
            check = _make_check(
                claim,
                source=None,
                status=CitationStatus.UNKNOWN,
                reason=error,
            )
        elif error is not None:
            check = _make_check(
                claim,
                source=None,
                status=CitationStatus.UNSUPPORTED,
                reason=error,
            )
        elif source is None or source.canonical_url is None:
            check = _make_check(
                claim,
                source=source,
                status=CitationStatus.UNSUPPORTED,
                reason=CitationReason.URL_INVALID,
            )
        elif source.canonical_url not in outcomes:
            check = _make_check(
                claim,
                source=source,
                status=CitationStatus.UNKNOWN,
                reason=CitationReason.SOURCE_LIMIT,
            )
        else:
            outcome = outcomes[source.canonical_url]
            if outcome.status is CitationStatus.VERIFIED:
                # Search snippets are useful synthesis input but may be stale;
                # only the bounded live response can earn ``verified``.
                status, reason = _support_status(claim.text, outcome.text)
            else:
                status, reason = outcome.status, outcome.reason
            check = _make_check(claim, source=source, status=status, reason=reason)
        checks.append(check)
        if source is not None:
            previous = aggregate.get(source.position)
            candidate = (check.status, check.reason)
            if previous is None or _STATUS_PRIORITY[candidate[0]] > _STATUS_PRIORITY[previous[0]]:
                aggregate[source.position] = candidate

    if claims_truncated:
        checks.append(
            CitationCheck(
                claim_id="claim-limit-summary",
                claim_path="final_recommendation",
                claim_text="Additional citation checks were omitted by the deterministic limit.",
                source_title=None,
                canonical_url=None,
                status=CitationStatus.UNKNOWN,
                reason=CitationReason.SOURCE_LIMIT,
            )
        )

    projected = [dict(chain) for chain in evidence_chains]
    registry_by_position = {item.position: item for item in registry}
    for chain_index, chain in enumerate(projected):
        copied_sources: list[Any] = []
        sources = chain.get("sources", [])
        if not isinstance(sources, list):
            chain["sources"] = []
            continue
        for source_index, source in enumerate(sources):
            if not isinstance(source, dict):
                copied_sources.append(source)
                continue
            copied = dict(source)
            registry_source = registry_by_position.get((chain_index, source_index))
            status, reason = aggregate.get(
                (chain_index, source_index),
                (
                    CitationStatus.UNKNOWN,
                    CitationReason.NOT_CITED
                    if registry_source is not None
                    else CitationReason.SOURCE_LIMIT,
                ),
            )
            copied["canonical_url"] = (
                registry_source.canonical_url
                if registry_source is not None
                else canonicalize_source_url(source.get("url"))
            )
            copied["verification_status"] = status.value
            copied["verification_reason"] = reason.value
            copied_sources.append(copied)
        chain["sources"] = copied_sources

    counts = Counter(check.status.value for check in checks)
    verification = CitationVerification(
        policy_version=CITATION_POLICY_VERSION,
        status_counts=CitationStatusCounts(
            verified=counts[CitationStatus.VERIFIED.value],
            unsupported=counts[CitationStatus.UNSUPPORTED.value],
            unreachable=counts[CitationStatus.UNREACHABLE.value],
            unknown=counts[CitationStatus.UNKNOWN.value],
        ),
        checks=tuple(checks),
    )
    return verification, projected


__all__ = [
    "MAX_FETCH_CONCURRENCY",
    "MAX_RESPONSE_BYTES",
    "MAX_UNIQUE_SOURCE_URLS",
    "canonicalize_source_url",
    "verify_citations",
]
