from .basis import source_provenance_note, used_sources
from .coverage import derive_data_source_note


def _lang(query: str) -> str:
    return "zh" if any('一' <= c <= '鿿' for c in query) else "en"


def _link(text: str, src: dict) -> str:
    url = (src or {}).get("url", "")
    return f"[{text}]({url})" if url else text


def _has_body(src: dict) -> bool:
    from ..utils.candidate_identity import has_factual_content

    return has_factual_content(src)


def _claim_source(conflict: dict, key: str, lang: str) -> str:
    """A dispute claim's source, or a stated gap when it carries no body.

    The link stays visible so the reader can reach the page, but it is labelled
    as carrying no content and is never presented as a usable basis.
    """
    src = conflict.get(key, {}) or {}
    claim = conflict.get("claim_a" if key == "source_a" else "claim_b", "")
    if _has_body(src):
        return _link(claim, src)
    url = src.get("url", "")
    link = f"[{claim}]({url})" if url else claim
    note = "无正文（仅导航链接）" if lang == "zh" else \
        "no body collected (navigation link only)"
    return f"{link} — {note}"


def render(state: dict) -> str:
    task = state.get("task", {})
    query = task.get("query", "Technology Selection")
    chains = state.get("evidence_chains", [])
    conflicts = state.get("conflicts", [])
    lang = _lang(query)

    T = {
        "title_suffix": {"en": " — Evidence Brief", "zh": " — 证据简报"},
        "conclusion": {"en": "## Conclusion", "zh": "## 结论"},
        "insufficient": {"en": "Insufficient evidence to draw a conclusion.", "zh": "证据不足以得出结论。"},
        "trust": {"en": "## Why Trust This Conclusion", "zh": "## 证据可信度"},
        "sources_used": {"en": "The conclusion cites {n} source(s). The count shows how "
                               "often a source is used, not how strongly it supports a claim:",
                         "zh": "本次结论实际引用了 {n} 个来源；引用次数表示使用次数，不表示支持强度："},
        "no_used_source": {"en": "The synthesis result cites no traceable source. That does "
                                 "not mean retrieval returned nothing; it means this report "
                                 "does not rely on it.",
                           "zh": "本次合成结果没有引用任何可追溯的来源；这不代表检索没有返回材料，"
                                 "只代表本报告没有用它作为依据。"},
        "navigation": {"en": "**Navigation links (no body collected; not usable as a basis)**",
                       "zh": "**导航链接（无正文，不能作为依据）**"},
        "unused_note": {"en": "The other {n} retrieved item(s) are not part of this report's "
                              "basis and remain in the raw retrieval record.",
                        "zh": "其余 {n} 条检索结果未进入本报告的依据，保留在原始检索记录中。"},
        "disputes": {"en": "## Disputes", "zh": "## 争议"},
        "no_disputes": {"en": "No major disputes detected.", "zh": "未检测到重大争议。"},
        "claim_a": {"en": "Claim A", "zh": "主张 A"},
        "claim_b": {"en": "Claim B", "zh": "主张 B"},
        "unknown": {"en": "## What We Don't Know", "zh": "## 知识盲区"},
        "confidence": {"en": "Confidence", "zh": "置信度"},
        "decision": {"en": "## If You're Making a Decision", "zh": "## 决策建议"},
        "step1": {"en": "1. Verify the strongest evidence source independently", "zh": "1. 独立验证最强证据来源"},
        "step2": {"en": "2. Check if the disputed claims affect your use case", "zh": "2. 检查争议项是否影响你的使用场景"},
        "step3": {"en": "3. Run a quick prototype with the recommended option", "zh": "3. 用推荐方案做快速原型验证"},
    }

    rec = state.get("final_recommendation", {})
    winner = rec.get("winner", "")
    if not winner and rec.get("ranked_options"):
        winner = (rec.get("ranked_options") or [{}])[0].get("name", "")

    lines = [
        f"# {query}{T['title_suffix'][lang]}",
        "",
    ]
    data_note = derive_data_source_note(state)
    if data_note:
        lines.extend([f"> {data_note}", ""])
    lines.append(T["conclusion"][lang])
    if winner:
        lines.append(f"**Winner: {winner}**")
        if rec.get("winner_rationale"):
            lines.append(f"*{rec['winner_rationale']}*")
        lines.append("")
    if rec.get("recommendation"):
        lines.append(rec["recommendation"])
        if rec.get("confidence_rationale"):
            lines.append("")
            lines.append(f"*{rec['confidence_rationale']}*")
    else:
        lines.append(T["insufficient"][lang])
    lines.extend(["", T["trust"][lang], ""])

    # The basis is what the synthesis result cites, derived the same way as in
    # every other format. A retrieved page is not a finding: rendering each hit
    # as a "conclusion" with a strength taken from its retrieval score presented
    # a search result as an established judgement.
    used = used_sources(rec, chains)
    if used:
        lines.append(T["sources_used"][lang].format(n=len(used)))
        lines.append("")
        for src in used[:12]:
            note = source_provenance_note(src, lang)
            lines.append(f"- [{src['title']}]({src['url']}) ×{src['citations']}{note}")
        lines.append("")
    else:
        lines.append(T["no_used_source"][lang])
        lines.append("")

    # Discovered links with no body stay reachable, labelled as navigation.
    nav = [s for c in chains for s in c.get("sources", []) if not _has_body(s)]
    if nav:
        seen = set()
        for src in nav:
            url = src.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            note = ("导航链接，无正文，不能作为依据。" if lang == "zh"
                    else "navigation link only, no body collected; not usable "
                         "as a basis.")
            lines.append(f"- [{src.get('title', '')}]({url}) — {note}")
        lines.append("")

    retrieved = sum(len(c.get("sources") or []) for c in chains)
    if retrieved > len(used):
        lines.append(T["unused_note"][lang].format(n=retrieved - len(used)))
        lines.append("")

    lines.extend(["", T["disputes"][lang], ""])
    if conflicts:
        for c in conflicts:
            lines.append(f"- {c.get('resolution', 'unresolved')}: {c.get('reasoning', '')[:200]}")
            for label, key in ((T["claim_a"][lang], "source_a"),
                               (T["claim_b"][lang], "source_b")):
                lines.append(f"  - {label}: {_claim_source(c, key, lang)}")
    else:
        # As in the other renderers: absence of a dispute is a finding only when
        # the conflict check actually completed.
        check = state.get("conflict_check") or {}
        outcomes = (check.get("scan_outcomes") or {}) if isinstance(check, dict) else {}
        unscanned = int(outcomes.get("unscanned") or 0)
        scanned = int(check.get("pairs_scanned") or 0) if isinstance(check, dict) else 0
        arb_failed = (int(check.get("pairs_arbitration_failed") or 0)
                      if isinstance(check, dict) else 0)
        if not check or unscanned or arb_failed or scanned == 0:
            if arb_failed:
                lines.append(
                    f"发现 {arb_failed} 组潜在分歧，但未完成裁定。" if lang == "zh"
                    else f"{arb_failed} candidate pair(s) showed a potential "
                         f"disagreement that was not resolved."
                )
            else:
                lines.append(
                    "冲突检查未完成，缺失争议不代表来源一致。" if lang == "zh"
                    else "The conflict check did not complete; a missing dispute does "
                         "not mean the sources agree."
                )
        else:
            lines.append(T["no_disputes"][lang])

    lines.extend(["", T["unknown"][lang], "", f"**{T['confidence'][lang]}:** {rec.get('confidence', state.get('confidence', 'unknown'))}"])
    for g in state.get("knowledge_gaps", []):
        lines.append(f"- {g}")

    lines.extend([
        "",
        T["decision"][lang],
        "",
        T["step1"][lang],
        T["step2"][lang],
        T["step3"][lang],
    ])

    return "\n".join(lines)
