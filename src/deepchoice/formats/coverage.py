"""Derive the data-coverage note at render time.

The note used to be written into a node's local copy of the state by
`report_generator`, which did not return it, so it never entered the graph state.
Every artefact rendered afterwards — including the final report the reviewer
re-rendered — lost it, even though `partial_failures` still recorded that a
source had failed. Deriving it here means every render entry (`report.md`, the
report endpoint, the annotated view and the exports) computes the same note from
the same recorded failures.
"""
from __future__ import annotations

import re

_ZH = re.compile(r"[\u4e00-\u9fff]")


def derive_data_source_note(state: dict) -> str:
    """A statement of which sources were unavailable, or "" when none failed.

    Reads only what the run already recorded: `partial_failures` and
    `search_results`. An explicit `data_source_note` is still honoured for older
    snapshots that carry one.
    """
    explicit = str(state.get("data_source_note") or "").strip()
    if explicit:
        return explicit

    partial_failures = [str(f) for f in (state.get("partial_failures") or []) if str(f)]
    empty_sources = [_empty_source_name(f) for f in (state.get("empty_sources") or [])]
    page_failures = _page_fetch_failures(state.get("search_results") or [])
    if not partial_failures and not page_failures and not empty_sources:
        return ""

    total = len(state.get("search_results") or [])
    available = max(0, total - len(partial_failures) - len(empty_sources))
    query = str((state.get("task") or {}).get("query", ""))
    is_zh = bool(_ZH.search(query))
    if is_zh:
        note = f"数据覆盖: {available}/{total} 个渠道可用。"
        if partial_failures:
            note += f"不可用: {', '.join(partial_failures)}。"
        if empty_sources:
            note += f"空结果: {', '.join(empty_sources)}。"
        if page_failures:
            note += (f"另有 {page_failures['count']} 个页面未返回可用正文"
                     f"（{page_failures['summary']}）。")
        return note + "结论基于已取得的正文与检索摘要，可能遗漏失败页面的视角。"
    note = f"Data coverage: {available}/{total} sources available."
    if partial_failures:
        note += f" Unavailable: {', '.join(partial_failures)}."
    if empty_sources:
        note += f" Empty: {', '.join(empty_sources)}."
    if page_failures:
        note += (f" {page_failures['count']} page(s) returned no usable body "
                 f"({page_failures['summary']}).")
    return (note + " Conclusions are based on the retrieved bodies and snippets and "
            "may miss perspectives from the failed pages.")


def _empty_source_name(item) -> str:
    """A readable channel name for an empty-source record.

    Snapshots carry `empty_sources` as dicts ({"source": "chroma", "reason": ...});
    str(dict) printed raw in the note before (round-five validation F200-151).
    """
    if isinstance(item, dict):
        return str(item.get("source") or item.get("name") or item.get("channel")
                   or "未知渠道")
    return str(item)


def _page_fetch_failures(search_results: list[dict]) -> dict | None:
    """Count pages whose body fetch failed (connect errors, timeouts, 404s).

    The round-two validation (F200-151, 2026-11-03) showed the coverage note only
    listed channel-level failures, hiding that four official documentation pages
    failed to fetch; a reader could not see why the decisive evidence was thin.
    Only recorded fetch outcomes are counted; a bodyless navigation link with no
    recorded error is not a failure.
    """
    from collections import Counter

    errors: list[str] = []
    for item in search_results or []:
        if not isinstance(item, dict):
            continue
        for result in item.get("results") or []:
            if not isinstance(result, dict) or result.get("has_body"):
                continue
            raw_error = str(result.get("body_error") or "").strip()
            if not raw_error:
                continue
            if "not_prose" in raw_error.lower():
                # Fetched successfully but rejected as navigation/non-prose; not a
                # network failure, so it is labelled separately in the note.
                label = "非正文"
            elif "ConnectError" in raw_error:
                label = "ConnectError"
            elif "timeout" in raw_error.lower():
                label = "timeout"
            elif raw_error.startswith("http:"):
                label = "HTTP"
            elif "ReadError" in raw_error:
                label = "ReadError"
            else:
                label = "fetch error"
            errors.append(label)
    if not errors:
        return None
    counts = Counter(errors)
    summary = "、".join(f"{name} ×{count}" if count > 1 else name
                       for name, count in counts.most_common())
    return {"count": len(errors), "summary": summary}
