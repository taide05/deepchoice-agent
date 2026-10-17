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
        "strongest": {"en": "### Strongest Evidence", "zh": "### 最强证据"},
        "supporting": {"en": "### Supporting Evidence Chain", "zh": "### 支撑证据链"},
        "counter": {"en": "## Counter-Evidence", "zh": "## 反面证据"},
        "no_counter": {"en": "No significant counter-evidence found.", "zh": "未发现显著反面证据。"},
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

    strong = [c for c in chains if c.get("evidence_strength") == "strong"]
    top = strong[0] if strong else (chains[0] if chains else None)

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
        lines.append(top.get('conclusion', '') if top else T["insufficient"][lang])
    lines.extend(["", T["trust"][lang]])

    if top:
        lines.append(T["strongest"][lang])
        # Only fact-bearing sources are evidence. A discovered link whose body was
        # never collected is navigation and must not be listed as this chain's
        # strongest evidence, or exported as if it were.
        factual_top = [s for s in top.get("sources", []) if _has_body(s)]
        links_top = [s for s in top.get("sources", []) if not _has_body(s)]
        if factual_top:
            for src in factual_top:
                lines.append(f"- [{src.get('title', '')}]({src.get('url', '')}) (score: {src.get('score', 'N/A')})")
        else:
            lines.append("No fact-bearing source was collected for this chain; "
                         "recorded as a material gap." if lang != "zh"
                         else "本条未取得正文来源，记为资料缺口。")
        # A discovered link stays reachable even when it is not evidence.
        for src in links_top:
            lines.append(f"- [{src.get('title', '')}]({src.get('url', '')}) — "
                         + ("导航链接，无正文，不能作为依据。" if lang == "zh"
                            else "navigation link only, no body collected; not usable "
                                 "as a basis."))
        lines.append("")
        lines.append(T["supporting"][lang])
        moderate = [c for c in chains if c.get("evidence_strength") == "moderate"][:3]
        for c in moderate:
            lines.append(f"- {c.get('conclusion', '')}")

    lines.extend(["", T["counter"][lang], ""])
    disputed = [c for c in chains if c.get("disputed")]
    if disputed:
        for c in disputed:
            lines.append(f"- {c.get('conclusion', '')} (disputed)")
    else:
        lines.append(T["no_counter"][lang])

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
