"""The report's evidence basis, derived the same way for every report format.

A retrieved page is not a finding, and its retrieval score is not evidence
strength. The basis is the set of sources the synthesis result actually cites:
each citation the result contains is resolved to the retrieved source that
carries it. Material that was retrieved but never cited stays in the raw
retrieval record (`source_scores` / `search_results`) and is not presented as a
basis here — rendering it as a "conclusion" with a strength derived from its
score would manufacture a judgement the pipeline never made.
"""
from __future__ import annotations

import re

_CITED_TEXT_FIELDS = ("recommendation", "winner_rationale", "confidence_rationale",
                      "evidence_summary", "scene_fit_note")
_CITED_OPTION_FIELDS = ("rationale", "constraint_fit_reason", "key_strength",
                        "key_weakness")
_CITED_TRADEOFF_FIELDS = ("finding", "impact")


def used_sources(rec: dict, chains: list[dict]) -> list[dict]:
    """The sources the synthesis result cites, with provenance and a use count.

    A source belongs here only because the recommendation cites it. Body-less
    links are excluded: a link with no collected body is navigation, not a
    basis. The count says how often the source is used, not how strongly it
    supports anything.
    """
    from ..utils.candidate_identity import has_factual_content

    by_title: dict[str, dict] = {}
    for chain in chains or []:
        for src in chain.get("sources", []):
            title = src.get("title", "")
            if title and src.get("url") and has_factual_content(src):
                by_title.setdefault(title, src)

    blobs: list[str] = [str((rec or {}).get(f) or "") for f in _CITED_TEXT_FIELDS]
    for opt in (rec or {}).get("ranked_options") or []:
        if isinstance(opt, dict):
            blobs.extend(str(opt.get(f) or "") for f in _CITED_OPTION_FIELDS)
    for to in (rec or {}).get("trade_offs") or []:
        if isinstance(to, dict):
            blobs.extend(str(to.get(f) or "") for f in _CITED_TRADEOFF_FIELDS)

    used: dict[str, dict] = {}
    for blob in blobs:
        for marker in re.findall(r"\[Source:\s*([^\]]+)\]", blob):
            for part in marker.split(", Source:"):
                title = part.strip()
                src = by_title.get(title)
                if not src:
                    continue
                entry = used.setdefault(title, {
                    "title": title,
                    "url": src.get("url", ""),
                    "provenance": src.get("provenance", "unknown"),
                    "channel": src.get("channel", ""),
                    "citations": 0,
                })
                entry["citations"] += 1
    return list(used.values())


def source_provenance_note(src: dict, lang: str) -> str:
    """Describe a source's origin honestly, without calling local material public.

    Only material whose origin could be mistaken for something else is
    annotated: locally held documents and evaluation material. A page fetched
    from the web needs no note — its URL already says where it came from.
    """
    provenance = str(src.get("provenance") or "").strip().lower()
    channel = str(src.get("channel") or "").strip().lower()
    url = str(src.get("url", "")).lower()
    if provenance == "benchmark_ground_truth" or channel == "benchmark_ground_truth":
        return "（评测答案材料）" if lang == "zh" else " (benchmark answer material)"
    if channel == "local_kb" or url.startswith("file://"):
        return "（本地知识库文档）" if lang == "zh" else " (local knowledge-base document)"
    if url.startswith(("http://", "https://")):
        return ""
    return "（出处未知）" if lang == "zh" else " (provenance unknown)"
