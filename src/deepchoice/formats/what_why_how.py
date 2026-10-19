import re

from .basis import (
    escape_markdown_text,
    source_provenance_note,
    used_sources,
)
from .coverage import derive_data_source_note
from ..agents.conclusion_synthesizer import clean_label


def _lang(query: str) -> str:
    return "zh" if any('一' <= c <= '鿿' for c in query) else "en"


def _field_source_links(rec: dict, locator: str, text: str,
                        chains: list[dict]) -> list[str]:
    """Sources the field cites, in citation order, as title+URL links.

    Current runs carry the registered identity of each resolved citation, so the
    link is read from that map and a title shared by two sources still links to
    the right one. Historical material without the map falls back to a full-title
    lookup that resolves only a title naming exactly one source; an unknown or
    ambiguous title is left unlinked rather than guessed.
    """
    from ..agents.conclusion_synthesizer import CITATION_SOURCES_KEY

    identity_map = (rec or {}).get(CITATION_SOURCES_KEY)
    links: list[str] = []
    if isinstance(identity_map, dict) and locator in identity_map:
        for binding in identity_map.get(locator) or []:
            if not isinstance(binding, dict):
                continue
            title = str(binding.get("title") or "")
            url = str(binding.get("url") or "")
            label = escape_markdown_text(title)
            link = f"[{label}]({url})" if url else label
            if link and link not in links:
                links.append(link)
        # Show every registered identity bound to the field. The previous cap of
        # three hid the rest of a field's citation set while the binding map knew
        # about them, so the report claimed fewer sources than the answer used.
        return links
    from .basis import unique_sources_for_title

    # No identity for this field: either a historical record, or a partial map
    # covering a field that was revised. Resolve full titles only when they name
    # exactly one source; never guess.
    for title in re.findall(r"\[Source:\s*([^\]]+)\]", text or ""):
        for part in re.split(r",\s*Source:\s*", title):
            sources = unique_sources_for_title(chains, part.strip())
            if len(sources) != 1:
                continue
            src = sources[0]
            url = str(src.get("url") or "")
            label = escape_markdown_text(part.strip())
            link = f"[{label}]({url})" if url else label
            if link not in links:
                links.append(link)
    return links


_DANGLING_PUNCT_RE = re.compile(r"\s+([。，、；：！？])")


def _display_text(text: str) -> str:
    """Clean a display-only fragment without deleting any factual content.

    Citation markers may be stripped from a label for readability; removing a
    marker can leave a space before sentence punctuation. That is a presentational
    leftover, not a reason to remove the surrounding statement.
    """
    cleaned = clean_label(text)
    return _DANGLING_PUNCT_RE.sub(r"\1", cleaned)


def _one_line(value) -> str:
    """Collapse model text to a single markdown line.

    A newline inside a value breaks the bullet it is placed in and truncates the
    rest of that candidate's explanation.
    """
    return " ".join(str(value or "").split())


def _has_body(src: dict) -> bool:
    from ..utils.candidate_identity import has_factual_content

    return has_factual_content(src)


def _claim_source(conflict: dict, key: str, lang: str) -> str:
    """A dispute claim's source, or a stated gap when it has no body.

    New conflict rows carry the source title and a body excerpt separately: the
    link label is the source title (identity), and the excerpt is shown as plain
    text. A body-less navigation link may be shown as a plain link — the reader
    must be able to reach the page — but it is labelled as carrying no content and
    is never numbered as a citable source. Historical rows without a title keep
    the old claim-as-label fallback.
    """
    src = conflict.get(key, {}) or {}
    title = _one_line(src.get("title") or "")
    claim = _one_line(conflict.get("claim_a" if key == "source_a" else "claim_b", ""))
    if len(claim) > 240:
        claim = claim[:240].rstrip() + "…"
    label = escape_markdown_text(title or claim or "N/A")
    url = src.get("url", "")
    if url:
        link = f"[{label}]({url})"
    else:
        link = label
    excerpt = ""
    if title and claim and claim != title:
        excerpt = f" — {escape_markdown_text(claim)}"
    score = src.get("score", "N/A")
    if _has_body(src):
        return f"{link}{excerpt} (score: {score})"
    note = "无正文（仅导航链接），不能作为依据。" if lang == "zh" else \
        "no body collected (navigation link only); not usable as a basis."
    return f"{link}{excerpt} — {note}"


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
        "why": {"en": "## Why: How the Sources Were Used", "zh": "## Why: 依据的实际使用"},
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
        "impact": {"en": "Impact", "zh": "影响"},
        "constraint_fit_reason": {"en": "Constraint-fit basis", "zh": "约束适配依据"},
        "evidence_summary": {"en": "### Evidence Summary", "zh": "### 证据摘要"},
        "scene_fit": {"en": "Scene Fit", "zh": "场景适配"},
        "starting_point": {"en": "### Starting Point", "zh": "### 起点"},
        "starting_hint": {"en": "Based on the evidence above, start with the highest-scored option that matches your scene context.", "zh": "基于以上证据，从匹配你场景上下文的最高分方案开始。"},
        "references": {"en": "### References", "zh": "### 参考来源"},
    }

    # A request can contain newlines (the query is preserved verbatim); a
    # Markdown heading must stay on one line, so the title is a display-only
    # one-line form of the request. The report body still carries the full text.
    title_query = _one_line(query)
    lines = [f"# {title_query}{T['title_suffix'][lang]}", ""]

    data_note = derive_data_source_note(state)
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
                fit_reason = _one_line(opt.get("constraint_fit_reason"))
                if fit_reason:
                    lines.append(f"- {T['constraint_fit_reason'][lang]}: {fit_reason}")
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

        # The cited-source list lives in the References section at the end, where
        # it is derived once from the sources the synthesis actually used. Keeping
        # a second copy here made the two drift apart.

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
                lines.append(f"- [{escape_markdown_text(title)}]({url})")
            lines.append("")

    lines.extend([T["why"][lang], ""])

    # What the recommendation actually used. A retrieval hit is not a finding: the
    # previous version turned every scored result into a heading with an "evidence
    # strength" derived from its metadata score, which presented a search result
    # as an established judgment. The basis is now the set of sources the
    # synthesis result cites; everything else stays in the raw retrieval record
    # (source_scores / search_results in the snapshot) and is not a basis here.
    used = used_sources(rec, chains)
    if used:
        if lang == "zh":
            lines.append(f"本次推荐实际引用了 {len(used)} 个来源；引用次数表示该来源在推荐中被使用的次数，"
                         "不表示其支持强度：")
        else:
            lines.append(f"The recommendation cites {len(used)} source(s). The citation "
                         "count shows how often a source is used, not how strongly it "
                         "supports a claim:")
        lines.append("")
        for src in used[:12]:
            note = source_provenance_note(src, lang)
            lines.append(f"- [{escape_markdown_text(src['title'])}]({src['url']}) ×{src['citations']}{note}")
        lines.append("")
    else:
        lines.extend([
            "本次合成结果没有引用任何可追溯的来源；这不代表检索没有返回材料，"
            "只代表本报告没有用它作为依据。" if lang == "zh"
            else "The synthesis result cites no traceable source. That does not mean "
                 "retrieval returned nothing; it means this report does not rely on it.",
            "",
        ])

    retrieved = sum(len(c.get("sources") or []) for c in chains)
    if retrieved > len(used):
        lines.extend([
            f"其余 {retrieved - len(used)} 条检索结果未进入本报告的依据，保留在原始检索记录中。"
            if lang == "zh"
            else f"The other {retrieved - len(used)} retrieved item(s) are not part of "
                 f"this report's basis and remain in the raw retrieval record.",
            "",
        ])

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
    excluded_no_body = (int(check.get("sources_without_comparable_claim") or 0)
                        if isinstance(check, dict) else 0)
    if excluded_no_body:
        if lang == "zh":
            lines.extend([f"> 另有 {excluded_no_body} 个高相关来源没有取得正文，未参与冲突比较；"
                          f"这不代表它们之间没有分歧。", ""])
        else:
            lines.extend([f"> {excluded_no_body} high-scoring source(s) had no collected "
                          f"body and were not compared for conflicts; this does not "
                          f"establish that they agree.", ""])
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

    # Open questions and material gaps are both "what we don't know yet". The
    # model writes `unresolved_questions` into the recommendation, but nothing
    # rendered them, so questions the synthesis itself flagged disappeared. They
    # are shown here, de-duplicated against the gaps the review recorded.
    unresolved = [str(q).strip() for q in (rec.get("unresolved_questions") or [])
                  if str(q).strip()]
    unknown_items: list[str] = []
    for item in list(unresolved) + [str(g).strip() for g in gaps if str(g).strip()]:
        if item and item not in unknown_items:
            unknown_items.append(item)
    if unknown_items:
        lines.extend([T["unknown"][lang], ""])
        for item in unknown_items:
            # Display-only text: a raw source number the model left in a gap is
            # not a followable citation, and stripping it may leave a dangling
            # space before punctuation. Neither justifies deleting the gap text.
            lines.append(f"- {_display_text(item)}")
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
        winner_basis = _one_line(rec.get("winner_rationale"))
        recommendation_text = _one_line(rec.get("recommendation"))
        # Do not print the same recommendation twice. The synthesis prompt asks
        # winner_rationale for the decisive basis and recommendation for the
        # action; a suffix/duplicate is display noise, not a second finding.
        if winner_basis and winner_basis not in recommendation_text:
            lines.append(f"*{winner_basis}*")
        lines.append("")
        lines.append(f"**{T['confidence'][lang]}:** {rec.get('confidence', state.get('confidence', 'unknown'))}")
        if rec.get("confidence_rationale"):
            lines.append(f"*{rec['confidence_rationale']}*")
        lines.append("")

    if rec.get("recommendation"):
        lines.append(f"**{T['recommendation'][lang]}:** {rec['recommendation']}")
        lines.append("")

    # A field's Sources line reads the identity map the citation pass recorded.
    # Only fact-bearing sources are registered, so a navigation link was never
    # bound and can never appear here.
    if rec.get("ranked_options"):
        lines.append(T["ranked_options"][lang])
        for opt in rec["ranked_options"]:
            rationale = opt.get('rationale', '')
            lines.append(f"- **#{opt.get('rank', '?')} {opt.get('name', '')}**: {rationale}")
            locator = f"option={opt.get('name') or '?'}/rationale"
            linked = _field_source_links(rec, locator, rationale, chains)
            if linked:
                lines.append(f"  *Sources: {'; '.join(linked)}*")
        lines.append("")
    if rec.get("trade_offs"):
        lines.append(T["trade_offs"][lang])
        for t in rec["trade_offs"]:
            finding = t.get('finding', '')
            # The label is display-only. A saved snapshot may still carry a raw
            # source number from before the label was normalised, so it is
            # cleaned here with the same helper the synthesis and the self-review
            # locating use — one identity for display and for locating.
            lines.append(f"- **{clean_label(t.get('dimension', ''))}**: {finding}")
            locator = f"trade-off={t.get('dimension') or '?'}/finding"
            linked = _field_source_links(rec, locator, finding, chains)
            if linked:
                lines.append(f"  *Sources: {'; '.join(linked)}*")
            impact = _one_line(t.get("impact"))
            if impact:
                impact_locator = f"trade-off={t.get('dimension') or '?'}/impact"
                impact_links = _field_source_links(rec, impact_locator, impact, chains)
                lines.append(f"  - {T['impact'][lang]}: {impact}")
                if impact_links:
                    lines.append(f"    *Sources: {'; '.join(impact_links)}*")
        lines.append("")
    if rec.get("evidence_summary"):
        summary = _one_line(rec.get("evidence_summary"))
        lines.append(T["evidence_summary"][lang])
        lines.append(summary)
        summary_links = _field_source_links(rec, "evidence_summary", summary, chains)
        if summary_links:
            lines.append(f"*Sources: {'; '.join(summary_links)}*")
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
    # References are the same set the Why section just derived: the sources the
    # synthesis result actually used. Retrieving a page does not make it a
    # reference for a claim, so unused material is not listed here.
    refs = used_sources(rec, chains)
    for src in refs[:12]:
        note = source_provenance_note(src, lang)
        lines.append(f"- [{escape_markdown_text(src['title'])}]({src['url']}){note}")
    if len(refs) > 12:
        lines.append(f"*(+{len(refs) - 12} more sources used)")
    if not refs:
        lines.append("- 本次没有可追溯的引用来源。" if lang == "zh"
                     else "- No traceable source was used in this run.")

    return "\n".join(lines)
