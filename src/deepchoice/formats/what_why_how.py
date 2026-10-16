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


def _one_line(value) -> str:
    """Collapse model text to a single markdown line.

    A newline inside a value breaks the bullet it is placed in and truncates the
    rest of that candidate's explanation.
    """
    return " ".join(str(value or "").split())


def _cited_source_links(rec: dict, chains: list[dict]) -> list[tuple[str, str]]:
    """The links behind the recommendation's own citations.

    Reads the titles the synthesis result cites and resolves them to the URLs in
    the evidence chains, so the candidate explanations and the references come
    from one source of truth. Body-less links are excluded: they are not a basis.
    """
    import re

    from ..utils.candidate_identity import has_factual_content

    by_title: dict[str, str] = {}
    for chain in chains or []:
        for src in chain.get("sources", []):
            title = src.get("title", "")
            url = src.get("url", "")
            if title and url and has_factual_content(src):
                by_title.setdefault(title, url)

    ordered: list[tuple[str, str]] = []
    for opt in (rec or {}).get("ranked_options") or []:
        if not isinstance(opt, dict):
            continue
        blob = " ".join(str(opt.get(f) or "") for f in
                        ("rationale", "constraint_fit_reason", "key_strength",
                         "key_weakness"))
        for name in re.findall(r"\[Source:\s*([^\]]+)\]", blob):
            for part in name.split(", Source:"):
                part = part.strip()
                url = by_title.get(part)
                if url and (part, url) not in ordered:
                    ordered.append((part, url))
    for name in re.findall(r"\[Source:\s*([^\]]+)\]",
                           str((rec or {}).get("recommendation") or "")):
        for part in name.split(", Source:"):
            part = part.strip()
            url = by_title.get(part)
            if url and (part, url) not in ordered:
                ordered.append((part, url))
    return ordered


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


def render(state: dict) -> str:
    task = state.get("task", {})
    query = task.get("query", "Technology Selection")
    chains = state.get("evidence_chains", [])
    conflicts = state.get("conflicts", [])
    gaps = state.get("knowledge_gaps", [])
    # Read once, before the sections that reuse it, so the candidate
    # explanations, the ranking and the references all come from this one result.
    rec = state.get("final_recommendation", {}) or {}
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

    # Candidate explanations come from the synthesis result, which is the one
    # place that decided what each candidate is for. The renderer used to build
    # its own picture by mapping sources onto candidates, so What and the
    # recommendation could disagree — and that mapping had to guess a page's
    # subject, which a page covering several products cannot answer.
    #
    # Reusing the synthesis result removes a second, competing judgement rather
    # than adding a rule. A candidate with no explanation is stated as such.
    candidates = [str(c).strip() for c in (task.get("candidate_techs") or []) if str(c).strip()]
    if candidates:
        explained = {}
        for opt in (rec or {}).get("ranked_options") or []:
            if isinstance(opt, dict) and str(opt.get("name", "")).strip():
                explained[str(opt["name"]).strip()] = opt

        for candidate in candidates:
            lines.append(f"### {candidate}")
            opt = explained.get(candidate)
            if opt:
                # Model text may carry newlines; a raw one would break the bullet
                # and silently truncate the candidate's explanation.
                if opt.get("constraint_fit"):
                    lines.append(f"- {T['scene_fit'][lang]}: {opt['constraint_fit']}")
                for field, label in (("rationale", "理由" if lang == "zh" else "Rationale"),
                                     ("key_strength", "优势" if lang == "zh" else "Advantage"),
                                     ("key_weakness", "局限" if lang == "zh" else "Limit")):
                    value = _one_line(opt.get(field))
                    if value:
                        lines.append(f"- {label}: {value}")
            else:
                lines.append("- 本次合成未给出该候选的说明；这是本轮的资料缺口，"
                             "不代表该候选不适用。"
                             if lang == "zh" else
                             "- The synthesis produced no explanation for this "
                             "candidate. That is a gap in this run, not a judgement "
                             "on the candidate.")
            lines.append("")

        # The sources behind those explanations, so the reader can reach them.
        # They are listed as the report's references, not assigned to a candidate:
        # a page may discuss several candidates and is not forced to own one.
        lines.append("**引用来源**" if lang == "zh" else "**Cited sources**")
        lines.append("")
        for title, url in _cited_source_links(rec, chains)[:10]:
            lines.append(f"- [{title}]({url})")
        lines.append("")

        # Discovered links are listed separately as navigation. They stay
        # reachable, and saying what they are keeps them from reading as a basis:
        # a page may cover several products, so it is not assigned to one.
        nav_links: list[tuple[str, str]] = []
        for chain in chains:
            for src in chain.get("sources", []):
                if not _has_body(src):
                    url = src.get("url", "")
                    title = src.get("title", "")
                    if url and (title, url) not in nav_links:
                        nav_links.append((title, url))
        if nav_links:
            lines.append("**导航链接（无正文，不能作为依据）**" if lang == "zh"
                         else "**Navigation links (no body collected; not usable as a basis)**")
            lines.append("")
            for title, url in nav_links[:10]:
                lines.append(f"- [{title}]({url})")
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
