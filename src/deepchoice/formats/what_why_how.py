def _lang(query: str) -> str:
    return "zh" if any('一' <= c <= '鿿' for c in query) else "en"


def _link(text: str, src: dict) -> str:
    url = (src or {}).get("url", "")
    return f"[{text}]({url})" if url else text


def _cited_sources(text: str, chain_sources: dict[str, list[str]]) -> list[str]:
    """Sources the text itself cites, in the order it cites them.

    The synthesizer already binds each claim to its real source and writes
    '[Source: <title>]'. The renderer therefore reports the citation that exists
    instead of guessing one: matching the text against source titles by shared
    words attached unrelated sources to a claim.
    """
    import re

    listed: list[str] = []
    for title in re.findall(r"\[Source:\s*([^\]]+)\]", text or ""):
        title = title.strip()
        for srcs in chain_sources.values():
            for link in srcs:
                if link.startswith(f"[{title}]"):
                    if link not in listed:
                        listed.append(link)
    return listed[:3]


def _content_or_gap(src: dict) -> str:
    """The source's body text, or an explicit statement that there is none."""
    from ..utils.candidate_identity import bounded_content_summary

    return bounded_content_summary(src, limit=300)


def _has_body(src: dict) -> bool:
    from ..utils.candidate_identity import has_factual_content

    return has_factual_content(src)


def _claim_source(conflict: dict, key: str, lang: str) -> str:
    """A dispute claim's source, or a stated gap when it has no body.

    A body-less navigation link may be shown as a plain link — the reader must be
    able to reach the page — but it is labelled as carrying no content and is
    never numbered as a citable source.
    """
    src = conflict.get(key, {}) or {}
    claim = conflict.get("claim_a" if key == "source_a" else "claim_b", "")
    url = src.get("url", "")
    score = src.get("score", "N/A")
    if _has_body(src):
        return f"{_link(claim, src)} (score: {score})"
    link = f"[{claim}]({url})" if url else claim
    note = "无正文（仅导航链接），不能作为依据。" if lang == "zh" else \
        "no body collected (navigation link only); not usable as a basis."
    return f"{link} — {note}"


from ..utils.candidate_identity import (  # noqa: E402
    UNASSIGNED,
    index_sources_by_candidate,
)


def render(state: dict) -> str:
    task = state.get("task", {})
    query = task.get("query", "Technology Selection")
    chains = state.get("evidence_chains", [])
    conflicts = state.get("conflicts", [])
    gaps = state.get("knowledge_gaps", [])
    lang = _lang(query)

    T = {
        "title_suffix": {"en": " — Decision Brief", "zh": " — 技术决策简报"},
        "what": {"en": "## What: Understanding the Candidates", "zh": "## What: 了解候选方案"},
        "why": {"en": "## Why: Evidence-Driven Judgment", "zh": "## Why: 证据驱动的判断"},
        "evidence_strength": {"en": "Evidence strength", "zh": "证据强度"},
        "disputes": {"en": "## Disputes & Resolutions", "zh": "## 争议与裁决"},
        "conflict": {"en": "Conflict", "zh": "争议"},
        "claim_a": {"en": "Claim A", "zh": "主张 A"},
        "claim_b": {"en": "Claim B", "zh": "主张 B"},
        "resolution": {"en": "Resolution", "zh": "裁决"},
        "key_factor": {"en": "Key factor", "zh": "关键因素"},
        "confidence": {"en": "Confidence", "zh": "置信度"},
        "unknown": {"en": "## What We Don't Know Yet", "zh": "## 尚未可知"},
        "how": {"en": "## How: Action Path", "zh": "## How: 行动路径"},
        "recommendation": {"en": "Recommendation", "zh": "建议"},
        "no_single_winner": {"en": "No single winner — the choice depends on your constraints", "zh": "无唯一胜者——选择取决于你的约束条件"},
        "ranked_options": {"en": "### Ranked Options", "zh": "### 方案排名"},
        "trade_offs": {"en": "### Trade-offs", "zh": "### 权衡"},
        "scene_fit": {"en": "Scene Fit", "zh": "场景适配"},
        "starting_point": {"en": "### Starting Point", "zh": "### 起点"},
        "starting_hint": {"en": "Based on the evidence above, start with the highest-scored option that matches your scene context.", "zh": "基于以上证据，从匹配你场景上下文的最高分方案开始。"},
        "references": {"en": "### References", "zh": "### 参考来源"},
    }

    lines = [f"# {query}{T['title_suffix'][lang]}", ""]

    data_note = state.get("data_source_note", "")
    if data_note:
        lines.extend([f"> {data_note}", ""])

    lines.extend([T["what"][lang], ""])

    # The candidates themselves, from the same structure the rest of the report
    # uses. This is not gated on evidence strength: with no strong chain the
    # section used to render empty, which left the reader without the options the
    # report is about. Insufficient material is stated, not hidden.
    candidates = [str(c).strip() for c in (task.get("candidate_techs") or []) if str(c).strip()]
    if candidates:
        # Explicit association: a source belongs to a candidate only when its own
        # name, site or URL identifies that candidate. Sharing a word such as
        # 'serverless' is not an association, so unmatched material is listed as
        # unassigned instead of being dealt onto whichever candidate matches a
        # keyword.
        all_sources = [src for c in chains for src in c.get("sources", [])]
        seen_urls: set[str] = set()
        flattened: list[dict] = []
        for src in all_sources:
            url = src.get("url", "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            flattened.append(src)
        index = index_sources_by_candidate(flattened, candidates)

        for candidate in candidates:
            lines.append(f"### {candidate}")
            basis = index.get(candidate) or []
            # A body-less link is not material for the candidate. Reporting one
            # as its basis, with a score, both presented a link as evidence and
            # suppressed the honest "no material" gap line.
            material = [src for src in basis if _has_body(src)]
            links = [src for src in basis if not _has_body(src)]
            if material:
                for src in material[:2]:
                    lines.append(f"- {src.get('title', '')} — "
                                 f"[link]({src.get('url', '')}) (score: {src.get('score', 'N/A')})")
                    lines.append(f"  - {_content_or_gap(src)}")
            else:
                lines.append("- 本次检索未取得明确指向该候选的材料；"
                             "不代表该候选不适用，只代表本轮没有资料。"
                             if lang == "zh"
                             else "- No retrieved material explicitly covered this "
                                  "candidate; that is a gap in this run, not a judgement "
                                  "on the candidate.")
            if links:
                lines.append("  - 仅有导航链接（无正文），不能作为该候选的依据："
                             if lang == "zh" else
                             "  - Navigation link(s) only, no body collected; not usable "
                             "as this candidate's basis:")
                for src in links[:3]:
                    lines.append(f"    - [{src.get('title', '')}]({src.get('url', '')})")
            lines.append("")

        unassigned = index.get(UNASSIGNED) or []
        if unassigned:
            lines.append("**未归属材料**" if lang == "zh" else "**Unassigned material**")
            lines.append("")
            lines.append("以下材料无法确认归属到上述任一候选，仅供参考，不作为某候选的依据。"
                         if lang == "zh" else
                         "The following material could not be attributed to any "
                         "candidate above. It is listed for reference only and is not "
                         "presented as any candidate's basis.")
            lines.append("")
            for src in unassigned[:5]:
                lines.append(f"- {src.get('title', '')} — "
                             f"[link]({src.get('url', '')}) (score: {src.get('score', 'N/A')})")
                # Unassigned material may be a link with no body; say which it is
                # rather than leaving it to look like a usable source.
                if not _has_body(src):
                    lines.append("  - 无正文（仅导航链接），不能作为依据。"
                                 if lang == "zh" else
                                 "  - No body collected (navigation link only); not "
                                 "usable as a basis.")
            lines.append("")

    lines.extend([T["why"][lang], ""])

    for c in chains[:10]:
        tag = " [DISPUTED]" if c.get("disputed") else ""
        lines.append(f"### {c.get('conclusion', '')}{tag}")
        lines.append(f"**{T['evidence_strength'][lang]}:** {c.get('evidence_strength', 'unknown')}")
        # Only fact-bearing sources are listed as basis. A navigation link is
        # shown under the navigation note elsewhere, not as evidence here.
        factual = [s for s in c.get("sources", []) if _has_body(s)]
        if factual:
            for src in factual[:2]:
                lines.append(f"- [{src.get('title', '')}]({src.get('url', '')}) — score: {src.get('score', 'N/A')}")
        else:
            lines.append("- 无正文来源；本条无法支撑论断，记为资料缺口。"
                         if lang == "zh" else
                         "- No fact-bearing source; this chain states nothing and is "
                         "recorded as a material gap.")
        lines.append("")
    if len(chains) > 10:
        lines.append(f"*(+{len(chains) - 10} more evidence chains — see full report via API)*")
        lines.append("")

    if conflicts:
        lines.extend([T["disputes"][lang], ""])
        for i, c in enumerate(conflicts):
            lines.append(f"### {T['conflict'][lang]} {i+1}: {c.get('resolution', 'unresolved')}")
            for label, key in ((T["claim_a"][lang], "source_a"),
                               (T["claim_b"][lang], "source_b")):
                lines.append(f"- {label}: {_claim_source(c, key, lang)}")
            lines.append(f"- {T['resolution'][lang]}: {c.get('reasoning', '')}")
            lines.append(f"- {T['key_factor'][lang]}: {c.get('key_factor', '')}")
            lines.append(f"- {T['confidence'][lang]}: {c.get('confidence', 'low')}")
            lines.append("")

    # An empty conflict list is only "no conflicts" when the check actually
    # completed. An unfinished or never-started check is stated as such, so the
    # report cannot pass it off as reassurance.
    check = state.get("conflict_check") or {}
    outcomes = (check.get("scan_outcomes") or {}) if isinstance(check, dict) else {}
    unscanned = int(outcomes.get("unscanned") or 0)
    scanned = int(check.get("pairs_scanned") or 0) if isinstance(check, dict) else 0
    arb_failed = (int(check.get("pairs_arbitration_failed") or 0)
                  if isinstance(check, dict) else 0)
    if not conflicts:
        if not check or unscanned or arb_failed or scanned == 0:
            if lang == "zh":
                if arb_failed:
                    detail = (f"发现 {arb_failed} 组潜在分歧，但**未完成裁定**"
                              f"（已扫描 {scanned} 组）")
                elif unscanned:
                    detail = f"未完成分类的候选对 {unscanned} 组（已扫描 {scanned} 组）"
                elif check:
                    detail = f"没有候选对进入该检查（{check.get('reason', '未记录')}）"
                else:
                    detail = "本次运行没有记录冲突检查覆盖情况"
                lines.extend(["## 冲突检查状态", "",
                              f"**冲突检查未完成。** {detail}。",
                              "缺失冲突不代表来源之间没有分歧，只代表本次没有完成判定。", ""])
            else:
                if arb_failed:
                    detail = (f"{arb_failed} candidate pair(s) showed a potential "
                              f"disagreement and the ruling was not completed "
                              f"(of {scanned} scanned)")
                elif unscanned:
                    detail = (f"{unscanned} candidate pair(s) were not classified "
                              f"(of {scanned} scanned)")
                elif check:
                    detail = (f"no candidate pair reached the check "
                              f"({check.get('reason', 'unrecorded')})")
                else:
                    detail = "this run recorded no conflict-check coverage"
                lines.extend(["## Conflict check status", "",
                              f"**The conflict check did not complete.** {detail}.",
                              "A missing conflict does not mean the sources agree; "
                              "it means the judgement was not finished.", ""])

    if gaps:
        lines.extend([T["unknown"][lang], ""])
        for g in gaps:
            lines.append(f"- {g}")
        lines.append("")

    rec = state.get("final_recommendation", {})
    lines.extend([T["how"][lang], ""])

    winner = rec.get("winner", "")
    if not winner and rec.get("ranked_options"):
        winner = (rec.get("ranked_options") or [{}])[0].get("name", "")

    if winner:
        if winner.lower() == "context_dependent":
            lines.append(f"**Winner:** {T['no_single_winner'][lang]}")
        else:
            lines.append(f"**Winner: {winner}**")
        if rec.get("winner_rationale"):
            lines.append(f"*{rec['winner_rationale']}*")
        lines.append("")
        lines.append(f"**{T['confidence'][lang]}:** {rec.get('confidence', state.get('confidence', 'unknown'))}")
        if rec.get("confidence_rationale"):
            lines.append(f"*{rec['confidence_rationale']}*")
        lines.append("")

    if rec.get("recommendation"):
        lines.append(f"**{T['recommendation'][lang]}:** {rec['recommendation']}")
        lines.append("")

    # Build source citation lookup from evidence chains. Only fact-bearing
    # sources are listed: a navigation link is not a reference for any claim.
    chain_sources: dict[str, list[str]] = {}
    for c in chains:
        conclusion = c.get("conclusion", "").lower()
        for src in c.get("sources", []):
            if not _has_body(src):
                continue
            title = src.get("title", "")
            url = src.get("url", "")
            if title and url:
                chain_sources.setdefault(conclusion, []).append(f"[{title}]({url})")

    if rec.get("ranked_options"):
        lines.append(T["ranked_options"][lang])
        for opt in rec["ranked_options"]:
            rationale = opt.get('rationale', '')
            lines.append(f"- **#{opt.get('rank', '?')} {opt.get('name', '')}**: {rationale}")
            linked = _cited_sources(rationale, chain_sources)
            if linked:
                lines.append(f"  *Sources: {'; '.join(linked)}*")
        lines.append("")
    if rec.get("trade_offs"):
        lines.append(T["trade_offs"][lang])
        for t in rec["trade_offs"]:
            finding = t.get('finding', '')
            lines.append(f"- **{t.get('dimension', '')}**: {finding}")
            linked = _cited_sources(finding, chain_sources)
            if linked:
                lines.append(f"  *Sources: {'; '.join(linked)}*")
        lines.append("")
    if rec.get("scene_fit_note"):
        lines.append(f"**{T['scene_fit'][lang]}:** {rec['scene_fit_note']}")
        lines.append("")

    if not winner and not rec.get("recommendation"):
        lines.extend([
            f"**{T['confidence'][lang]}:** {state.get('confidence', 'unknown')}",
            "",
            T["starting_point"][lang],
            T["starting_hint"][lang],
            "",
        ])

    lines.append(T["references"][lang])
    ref_count = 0
    # References list the sources that actually carry content. A navigation link
    # is not a reference for any claim in this report.
    body_sources = [src for c in chains for src in c.get("sources", []) if _has_body(src)]
    for src in body_sources:
        if ref_count >= 12:
            break
        lines.append(f"- [{src.get('title', '')}]({src.get('url', '')})")
        ref_count += 1
    if len(body_sources) > 12:
        lines.append(f"*(+{len(body_sources) - 12} more sources)")

    return "\n".join(lines)
