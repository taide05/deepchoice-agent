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
    if not partial_failures:
        return ""

    total = len(state.get("search_results") or [])
    available = max(0, total - len(partial_failures))
    query = str((state.get("task") or {}).get("query", ""))
    is_zh = bool(_ZH.search(query))
    if is_zh:
        return (f"数据覆盖: {available}/{total} 个来源可用。"
                f"不可用: {', '.join(partial_failures)}。"
                f"结论基于可用来源，可能遗漏不可用来源的视角。")
    return (f"Data coverage: {available}/{total} sources available. "
            f"Unavailable: {', '.join(partial_failures)}. "
            f"Conclusions are based on the available sources and may miss "
            f"perspectives from unavailable ones.")
