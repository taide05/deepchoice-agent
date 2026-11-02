from .basis import (
    escape_markdown_text,
    research_question_line,
    short_report_title,
    source_display_title,
    source_provenance_note,
    unused_retrieved_count,
    used_sources,
)
from .coverage import derive_data_source_note
from .report_quality import finalize_report_text, sanitize_arbitration_text
from ..utils.decision import (
    CONDITIONAL, INSUFFICIENT, INVALID, RECOMMENDED, decision_view,
)


def _lang(query: str) -> str:
    return "zh" if any('一' <= c <= '鿿' for c in query) else "en"


def _has_body(src: dict) -> bool:
    from ..utils.candidate_identity import has_factual_content

    return has_factual_content(src)


def _claim_source(conflict: dict, key: str, lang: str) -> str:
    """A dispute claim's source, or a stated gap when it carries no body.

    The source title labels the link; the body excerpt follows as plain, escaped
    text. Historical rows without a stored title keep the claim-as-label fallback.
    The link stays visible so the reader can reach the page, but a source that
    carries no body is labelled as such and never presented as a usable basis.
    """
    src = conflict.get(key, {}) or {}
    title = " ".join(str(src.get("title") or "").split())
    claim = conflict.get("claim_a" if key == "source_a" else "claim_b", "")
    claim = " ".join(str(claim or "").split())
    if len(claim) > 240:
        claim = claim[:240].rstrip() + "…"
    url = src.get("url", "")
    if title and url:
        # Locatable label: retriever-generated "<owner> — deep documentation"
        # titles get a path suffix so a wrong page cannot hide behind the owner.
        label = escape_markdown_text(
            source_display_title({"title": title, "url": url}))
    else:
        label = escape_markdown_text(title or claim or "N/A")
    link = f"[{label}]({url})" if url else label
    excerpt = ""
    if title and claim and claim != title:
        excerpt = f" — {escape_markdown_text(claim)}"
    if _has_body(src):
        return f"{link}{excerpt}"
    note = "无正文（仅导航链接）" if lang == "zh" else \
        "no body collected (navigation link only)"
    return f"{link}{excerpt} — {note}"


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
    decision = decision_view(rec)
    status = decision["status"]
    winner = decision["winner"]

    lines = [
        f"# {short_report_title(task, rec)}{T['title_suffix'][lang]}",
        "",
    ]
    question = research_question_line(task, lang)
    if question:
        lines.extend([question, ""])
    data_note = derive_data_source_note(state)
    if data_note:
        lines.extend([f"> {data_note}", ""])
    lines.append(T["conclusion"][lang])
    if status == RECOMMENDED and winner:
        lines.append(f"**Winner: {winner}**")
        if rec.get("winner_rationale"):
            lines.append(f"*{rec['winner_rationale']}*")
        lines.append("")
    elif status == CONDITIONAL:
        lines.append(("**Conditional decision — no single winner; choose by the "
                      "conditions below**" if lang == "en" else
                      "**条件选择——无唯一胜者，按下列条件选择**"))
        lines.append("")
    elif status == INSUFFICIENT:
        lines.append(T["insufficient"][lang])
        lines.append("")
    else:
        lines.append(("**Decision unavailable — model output invalid or execution "
                      "failed**" if lang == "en" else
                      "**决策未生成——模型输出无效或执行失败**"))
        lines.append("")
    if rec.get("recommendation") and status != "invalid":
        lines.append(rec["recommendation"])
        if rec.get("confidence_rationale"):
            lines.append("")
            lines.append(f"*{rec['confidence_rationale']}*")
    elif status == INVALID:
        lines.append(("No valid hold or recommendation was generated."
                      if lang == "en" else "未生成有效的暂缓或推荐。"))
    lines.extend(["", T["trust"][lang], ""])

    # The basis is what the synthesis result cites, derived the same way as in
    # every other format. A retrieved page is not a finding: rendering each hit
    # as a "conclusion" with a strength taken from its retrieval score presented
    # a search result as an established judgement.
    used = used_sources(rec, chains)
    if used:
        lines.append(T["sources_used"][lang].format(n=len(used)))
        lines.append("")
        for src in used:
            note = source_provenance_note(src, lang)
            lines.append(f"- [{escape_markdown_text(source_display_title(src))}]({src['url']}) ×{src['citations']}{note}")
        lines.append("")
    else:
        lines.append(T["no_used_source"][lang])
        lines.append("")

    # Discovered links with no body stay reachable, labelled as navigation. The
    # displayed list keeps only links whose title or URL names a declared
    # candidate; the rest are generic retrieval hits and stay in the raw record.
    candidates = [str(c).strip() for c in (task.get("candidate_techs") or [])
                  if str(c).strip()]
    nav = [s for c in chains for s in c.get("sources", []) if not _has_body(s)]
    if nav and candidates:
        from ..utils.candidate_identity import names_candidate

        seen = set()
        shown = 0
        for src in nav:
            url = src.get("url", "")
            if not url or url in seen:
                continue
            title = str(src.get("title", ""))
            if not any(names_candidate(f"{title} {url}", candidate)
                       for candidate in candidates):
                continue
            seen.add(url)
            note = ("导航链接，无正文，不能作为依据。" if lang == "zh"
                    else "navigation link only, no body collected; not usable "
                         "as a basis.")
            lines.append(f"- [{escape_markdown_text(title)}]({url}) — {note}")
            shown += 1
            if shown >= 6:
                break
        if shown:
            lines.append("")

    unused = unused_retrieved_count(chains, used)
    if unused:
        lines.append(T["unused_note"][lang].format(n=unused))
        lines.append("")

    lines.extend(["", T["disputes"][lang], ""])
    check = state.get("conflict_check") or {}
    outcomes = (check.get("scan_outcomes") or {}) if isinstance(check, dict) else {}
    unscanned = int(outcomes.get("unscanned") or 0)
    scanned = int(check.get("pairs_scanned") or 0) if isinstance(check, dict) else 0
    arb_failed = (int(check.get("pairs_arbitration_failed") or 0)
                  if isinstance(check, dict) else 0)
    excluded_no_body = (int(check.get("sources_without_comparable_claim") or 0)
                        if isinstance(check, dict) else 0)
    if conflicts:
        for c in conflicts:
            lines.append(f"- {sanitize_arbitration_text(c.get('resolution', 'unresolved'))}: {sanitize_arbitration_text(c.get('reasoning', ''))[:200]}")
            for label, key in ((T["claim_a"][lang], "source_a"),
                               (T["claim_b"][lang], "source_b")):
                lines.append(f"  - {label}: {_claim_source(c, key, lang)}")
    else:
        # As in the other renderers: absence of a dispute is a finding only when
        # the conflict check actually completed.
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
    if excluded_no_body:
        # No count: the exclusion population differs from the visible navigation
        # list, so a printed number read as a miscount (final-200 review).
        # G1 review (F200-164): with zero recorded conflicts, saying the sources
        # "were not compared for conflicts" was redundant next to the no-conflict
        # statement; the no-conflict case now says no arbitrable conflict was
        # recorded instead of implying the comparison happened and agreed.
        if lang == "zh":
            lines.append(
                "另有高相关来源没有取得正文（无正文来源不能作为依据），未参与冲突比较；"
                "这不代表它们之间没有分歧。" if conflicts else
                "另有高相关来源没有取得正文（无正文来源不能作为依据）；"
                "本次没有记录可裁决的争议，但这不代表这些来源之间没有分歧。")
        else:
            lines.append(
                "Some high-scoring source(s) had no collected body and were not "
                "compared for conflicts; this does not establish that they agree."
                if conflicts else
                "Some high-scoring source(s) had no collected body (a page without a "
                "collected body is not evidence); no arbitrable conflict was recorded "
                "here, which does not establish that these sources agree.")

    lines.extend(["", T["unknown"][lang], "", f"**{T['confidence'][lang]}:** {rec.get('confidence', state.get('confidence', 'unknown'))}"])
    # User-facing gaps come from the synthesis result. `knowledge_gaps` on the
    # state are self-review retry search targets and are not report prose.
    from .what_why_how import _display_text

    for gap in rec.get("unresolved_questions") or []:
        item = str(gap).strip()
        if item:
            lines.append(f"- {_display_text(item)}")

    lines.extend([
        "",
        T["decision"][lang],
        "",
        T["step1"][lang],
        T["step2"][lang],
        T["step3"][lang],
    ])

    return finalize_report_text("\n".join(lines))
