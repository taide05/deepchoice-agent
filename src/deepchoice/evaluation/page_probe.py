"""One bounded page-level evidence probe (diagnostic, not a product rule).

The eight URLs and inspection checks are frozen before the first request. The
probe uses the real safe-fetch/extraction path when no fetcher is injected, with
8 page attempts, 24 HTTP requests, 15 s per page, 1 MiB retained per page and a
300 s total wall budget. Test callers inject a fake fetcher; the online entry is
`scripts/page_probe.py`.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import re
import time

PAGE_LIMIT = 8
HTTP_LIMIT = 24
PAGE_DEADLINE_S = 15.0
PAGE_MAX_BYTES = 1_048_576
STORE_CHARS = 20_000
TOTAL_WALL_S = 300.0

# Fixed before dispatch. These are diagnostic URLs, never product aliases or
# candidate rules. Four are prior failed/decisive pages; four are unrelated
# public documentation pages covering body, directory and large-page shapes.
FROZEN_CHECKS = [
    {"url": "https://opentelemetry.io/zh/docs/collector/resiliency",
     "label": "OTel Collector resiliency (prior content_too_large)",
     "identity": "OpenTelemetry Collector", "kind": "candidate",
     "expected_shape": "body"},
    {"url": "https://opentelemetry.io/zh/docs/collector/scaling",
     "label": "OTel Collector scaling (prior snippet-only decisive page)",
     "identity": "OpenTelemetry Collector", "kind": "candidate",
     "expected_shape": "body"},
    {"url": "https://vector.dev/docs/",
     "label": "Vector documentation home (prior TOC-as-evidence)",
     "identity": "Vector", "kind": "candidate",
     "expected_shape": "directory"},
    {"url": "https://kubernetes.io/docs/",
     "label": "Kubernetes docs home (prior content_too_large)",
     "identity": "Kubernetes", "kind": "platform_constraint",
     "expected_shape": "directory"},
    {"url": "https://docs.python.org/3/library/asyncio.html",
     "label": "Python asyncio docs",
     "identity": "Python", "kind": "public_doc", "expected_shape": "body"},
    {"url": "https://www.rfc-editor.org/rfc/rfc9110.html",
     "label": "RFC 9110 HTTP Semantics",
     "identity": "RFC Editor", "kind": "public_doc", "expected_shape": "large"},
    {"url": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Overview",
     "label": "MDN HTTP overview",
     "identity": "Mozilla", "kind": "public_doc", "expected_shape": "body"},
    {"url": "https://docs.docker.com/",
     "label": "Docker documentation home",
     "identity": "Docker", "kind": "public_doc", "expected_shape": "directory"},
]


def frozen_config() -> dict:
    return {
        "probe_version": "page-probe-v1",
        "frozen_checks": [dict(item) for item in FROZEN_CHECKS],
        "limits": {
            "page_attempts": PAGE_LIMIT,
            "http_requests": HTTP_LIMIT,
            "page_deadline_s": PAGE_DEADLINE_S,
            "page_max_bytes": PAGE_MAX_BYTES,
            "store_chars": STORE_CHARS,
            "total_wall_s": TOTAL_WALL_S,
        },
    }


def config_sha256() -> str:
    return hashlib.sha256(json.dumps(frozen_config(), sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _date_or_version(text: str) -> dict:
    return {
        "date_like": bool(re.search(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b", text)),
        "version_like": bool(re.search(r"\bv?\d+\.\d+(?:\.\d+)?\b", text)),
        "note": "presence only; the page must still establish what the value applies to",
    }


async def _default_fetch(url, budget, deadline_s, max_response_bytes, store_chars):
    from ..retrievers.official_fetch import fetch_official_page
    return await fetch_official_page(
        url, budget=budget, deadline_s=deadline_s,
        max_response_bytes=max_response_bytes, max_redirects=3,
        store_chars=store_chars)


async def run_probe(*, fetch_fn=None, outdir=None) -> dict:
    from ..agents.evidence_chain import build_evidence_chain
    from ..agents.conclusion_synthesizer import build_source_registry
    from ..agents.source_evaluator import SourceEvaluatorAgent
    from ..retrievers.official_fetch import OfficialFetchBudget
    from ..utils.candidate_identity import (
        shared_evidence_package, source_identity_verified,
    )

    out = pathlib.Path(outdir) if outdir else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
        (out / "page_probe_freeze.json").write_text(
            json.dumps(frozen_config(), ensure_ascii=False, indent=2),
            encoding="utf-8")
    fetch_fn = fetch_fn or _default_fetch
    budget = OfficialFetchBudget(max_page_attempts=PAGE_LIMIT,
                                 max_http_requests=HTTP_LIMIT)
    started = time.monotonic()
    records = []
    for item in FROZEN_CHECKS:
        if time.monotonic() - started >= TOTAL_WALL_S:
            records.append({**item, "ok": False,
                            "failure": "total_wall_budget_exhausted"})
            break
        if not budget.begin_page():
            records.append({**item, "ok": False,
                            "failure": "page_attempt_budget_exhausted"})
            continue
        try:
            result = await asyncio.wait_for(
                fetch_fn(item["url"], budget, PAGE_DEADLINE_S,
                         PAGE_MAX_BYTES, STORE_CHARS),
                timeout=PAGE_DEADLINE_S)
        except asyncio.TimeoutError:
            result = {"ok": False, "failure": "timeout"}
        except Exception as exc:
            result = {"ok": False,
                      "failure": f"{type(exc).__name__}"}
        ok = bool(result.get("ok"))
        body = str(result.get("body") or "")
        # The fetched page's own title only. A frozen human label is never used
        # as page identity; if the fetch has no title, identity uses URL+body.
        title = str(result.get("title") or "")
        identity_verified = bool(source_identity_verified(
            item["identity"], item["url"], title, body)) if ok else False
        blocks = [str(x) for x in (result.get("body_blocks") or []) if str(x).strip()]
        record = {
            **item,
            "ok": ok,
            "failure": result.get("failure"),
            "body_url": result.get("body_url") or item["url"],
            "page_title": title,
            "has_body": result.get("has_body", ok),
            "content_length_exceeded": result.get("content_length_exceeded"),
            "declared_content_length": result.get("declared_content_length"),
            "page_truncated": result.get("page_truncated"),
            "stored_truncated": result.get("stored_truncated"),
            "truncation_reason": result.get("truncation_reason"),
            "bytes_read": result.get("bytes_read"),
            "bytes_retained": result.get("bytes_retained"),
            "page_chars": result.get("page_chars"),
            "stored_chars": result.get("stored_chars"),
            "page_role": result.get("page_role"),
            "main_block_count": result.get("main_block_count"),
            "prose_block_count": result.get("prose_block_count"),
            "heading_context_count": result.get("heading_context_count"),
            "identity_verified": identity_verified,
            "date_or_version": _date_or_version(body),
            "paragraphs": blocks[:8],
            "body_excerpt": body[:STORE_CHARS],
        }
        records.append(record)
        if out:
            (out / "bodies").mkdir(exist_ok=True)
            (out / "bodies" / f"{len(records):02d}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    elapsed = round(time.monotonic() - started, 3)
    result = {
        "freeze_sha256": config_sha256(),
        "limits": frozen_config()["limits"],
        "elapsed_s": elapsed,
        "budget": budget.snapshot(),
        "records": records,
        "total_wall_ok": elapsed <= TOTAL_WALL_S,
        "page_attempts_ok": budget.page_attempts <= PAGE_LIMIT,
        "http_requests_ok": budget.http_requests <= HTTP_LIMIT,
        "full_body_records": sum(1 for r in records if r.get("ok")),
        "directory_records": sum(1 for r in records if r.get("page_role") == "navigation"),
        "identity_matches": sum(1 for r in records if r.get("identity_verified")),
    }

    # Run the bounded saved material through the actual offline consumer path:
    # source scoring -> evidence chains -> shared package. No model call.
    official_results = []
    for r in records:
        official_results.append({
            "url": r["url"], "title": r.get("label") or r["url"],
            "snippet": r.get("body_excerpt") or "",
            "source_owner": (r["identity"] if r.get("identity_verified") else ""),
            "source_kind": r["kind"],
            "has_body": bool(r.get("ok")),
            "body_identity_verified": bool(r.get("identity_verified")),
            "fetch_status": "body" if r.get("ok") else "navigation",
            "body_error": r.get("failure"),
            "body_page_chars": r.get("page_chars"),
            "body_stored_chars": r.get("stored_chars"),
            "body_page_truncated": r.get("page_truncated"),
            "body_stored_truncated": r.get("stored_truncated"),
            "body_truncated": r.get("page_truncated") or r.get("stored_truncated"),
            "body_admission": r.get("page_role"),
        })
    state = {"task": {"candidate_techs": [x["identity"] for x in FROZEN_CHECKS
                                          if x["kind"] == "candidate"]},
             "search_results": [{"source": "official", "status": "success",
                                 "results": official_results}]}
    scored = await SourceEvaluatorAgent().run(state)
    state.update(scored)
    chains = build_evidence_chain(state["source_scores"], [])
    registry = build_source_registry(chains)
    package = shared_evidence_package(registry["entries"])
    result["consumers"] = {
        "source_scores": [{
            "url": s.get("url"), "source_type": s.get("source_type"),
            "source_owner": s.get("source_owner"),
            "has_body": s.get("has_body"),
            "body_identity_verified": s.get("body_identity_verified"),
            "fetch_status": s.get("fetch_status"),
        } for s in state["source_scores"]],
        "citable_entries": [{
            "url": e.get("url"), "source_type": e.get("source_type"),
            "source_owner": e.get("source_owner"),
            "body_identity_verified": e.get("body_identity_verified"),
            "fetch_status": e.get("fetch_status"),
        } for e in registry["entries"]],
        "navigation": registry["navigation"],
        "package_sources": package["sources"],
        "package_full_included": package["full_included"],
    }
    if out:
        (out / "page_probe_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
