from ..agents.conclusion_synthesizer import clean_label
from .basis import (
    escape_markdown_text,
    source_provenance_note,
    used_sources,
)
from .coverage import derive_data_source_note


def _lang(query: str) -> str:
    return "zh" if any('一' <= c <= '鿿' for c in query) else "en"


def _cell(value) -> str:
    """A markdown table cell: one line, and no cell separator inside it."""
    return " ".join(str(value or "").split()).replace("|", "\\|") or "—"


def _has_body(src: dict) -> bool:
    from ..utils.candidate_identity import has_factual_content

    return has_factual_content(src)


def _claim_source(conflict: dict, key: str, lang: str) -> str:
    """A dispute claim's source, or a stated gap when it carries no body.

    The source title labels the link; the body excerpt follows as plain, escaped
    text. Historical rows without a stored title keep the claim-as-label fallback.
    The link stays visible, but a page whose body was never collected is labelled
    as such instead of being shown as the claim's source.
    """
    src = conflict.get(key, {}) or {}
    title = " ".join(str(src.get("title") or "").split())
    claim = conflict.get("claim_a" if key == "source_a" else "claim_b", "") or ""
    claim = " ".join(str(claim).split())
    if len(claim) > 240:
        claim = claim[:240].rstrip() + "…"
    label = escape_markdown_text(title or claim or "N/A")
    url = src.get("url", "")
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
    query = task.get("query", "Technology Comparison")
    # The request may contain newlines; a heading is display-only and stays on
    # one line while the full request remains preserved in the task/state.
    title_query = " ".join(str(query).split())
    chains = state.get("evidence_chains", [])
    conflicts = state.get("conflicts", [])
    lang = _lang(query)

    L = {
        "title": {"en": f"# {title_query} — Candidate Comparison",
                  "zh": f"# {title_query} — 候选对比"},
        "col_candidate": {"en": "Candidate", "zh": "候选"},
        "col_fit": {"en": "Constraint fit", "zh": "约束适配"},
        "col_rationale": {"en": "Why", "zh": "理由"},
        "col_strength": {"en": "Advantage", "zh": "优势"},
        "col_weakness": {"en": "Limitation", "zh": "局限"},
        "no_candidates": {"en": "The synthesis produced no per-candidate comparison.",
                          "zh": "本次合成结果没有给出按候选的对比。"},
        "no_data": {"en": "not stated", "zh": "未给出"},
        "disputes_title": {"en": "## Disputes & Conflicts", "zh": "## 争议与分歧"},
        "dispute": {"en": "Dispute", "zh": "争议"},
        "claim_a": {"en": "Side A", "zh": "A方"},
        "claim_b": {"en": "Side B", "zh": "B方"},
        "resolution": {"en": "Resolution", "zh": "裁决"},
        "basis": {"en": "Basis", "zh": "依据"},
        "unresolved": {"en": "Unresolved", "zh": "未解决"},
        "no_disputes": {"en": "No significant disputes found in this search.", "zh": "本次搜索未发现显著争议。"},
        "recommendation_title": {"en": "## Recommendation", "zh": "## 建议"},
        "scene": {"en": "Scene", "zh": "场景"},
        "scene_solo": {"en": "Solo Developer", "zh": "个人开发者"},
        "scene_team": {"en": "Mid-size Team", "zh": "中型团队"},
        "scene_enterprise": {"en": "Enterprise", "zh": "企业级"},
        "recommend": {"en": "Recommendation", "zh": "推荐"},
        "ranking": {"en": "### Ranking", "zh": "### 排序"},
        "tradeoffs": {"en": "### Trade-offs", "zh": "### 权衡"},
        "scene_fit": {"en": "Scene Fit", "zh": "场景适配"},
        "sources_used": {"en": "### Sources Used", "zh": "### 使用的来源"},
        "no_used_source": {"en": "The synthesis result cites no traceable source.",
                           "zh": "本次合成结果没有引用任何可追溯的来源。"},
        "confidence": {"en": "Confidence", "zh": "置信度"},
        "next_steps": {"en": "### Next Steps", "zh": "### 下一步"},
        "step1": {"en": "1. Independently verify the cited sources", "zh": "1. 独立验证所引来源"},
        "step2": {"en": "2. Run targeted supplementary searches on disputed items", "zh": "2. 对争议点做针对性补充搜索"},
        "step3": {"en": "3. Build a quick prototype with the recommended option", "zh": "3. 用推荐方案做快速原型验证"},
    }

    rec = state.get("final_recommendation", {}) or {}

    # The comparison comes from the synthesis result's own per-candidate
    # explanations. The previous version sorted retrieval hits into five fixed
    # "dimensions" by matching keywords in their titles and snippets and labelled
    # each row with an "evidence strength" taken from its retrieval score — a
    # judgement the pipeline never reached, built from a keyword table.
    lines = [
        L["title"][lang],
        "",
    ]
    data_note = derive_data_source_note(state)
    if data_note:
        lines.extend([f"> {data_note}", ""])

    options = [o for o in (rec.get("ranked_options") or []) if isinstance(o, dict)]
    if options:
        lines.append(f"| {L['col_candidate'][lang]} | {L['col_fit'][lang]} | "
                     f"{L['col_rationale'][lang]} | {L['col_strength'][lang]} | "
                     f"{L['col_weakness'][lang]} |")
        lines.append("|---|---|---|---|---|")
        for opt in options:
            cells = [f"**#{opt.get('rank', '?')} {opt.get('name', '')}**",
                     _cell(opt.get("constraint_fit")),
                     _cell(opt.get("rationale")),
                     _cell(opt.get("key_strength")),
                     _cell(opt.get("key_weakness"))]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    else:
        lines.extend([L["no_candidates"][lang], ""])

    lines.extend(["", L["disputes_title"][lang], ""])
    check = state.get("conflict_check") or {}
    outcomes = (check.get("scan_outcomes") or {}) if isinstance(check, dict) else {}
    unscanned = int(outcomes.get("unscanned") or 0)
    scanned = int(check.get("pairs_scanned") or 0) if isinstance(check, dict) else 0
    arb_failed = (int(check.get("pairs_arbitration_failed") or 0)
                  if isinstance(check, dict) else 0)
    excluded_no_body = (int(check.get("sources_without_comparable_claim") or 0)
                        if isinstance(check, dict) else 0)
    if conflicts:
        for i, c in enumerate(conflicts):
            lines.append(f"### {L['dispute'][lang]} {i+1}")
            for label, key in ((L["claim_a"][lang], "source_a"),
                               (L["claim_b"][lang], "source_b")):
                lines.append(f"- {label}: {_claim_source(c, key, lang)}")
            lines.append(f"- {L['resolution'][lang]}: **{c.get('resolution', L['unresolved'][lang])}**")
            lines.append(f"- {L['basis'][lang]}: {c.get('reasoning', '')}")
            lines.append("")
    else:
        # "No disputes" is only a finding when the check ran to completion.
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
            lines.append(L["no_disputes"][lang])
    if excluded_no_body:
        lines.append(
            f"另有 {excluded_no_body} 个高相关来源没有取得正文，未参与冲突比较；"
            f"这不代表它们之间没有分歧。" if lang == "zh" else
            f"{excluded_no_body} high-scoring source(s) had no collected body and "
            f"were not compared for conflicts; this does not establish that they agree."
        )

    winner = rec.get("winner", "")
    if not winner and rec.get("ranked_options"):
        winner = (rec.get("ranked_options") or [{}])[0].get("name", "")

    lines.extend(["", L["recommendation_title"][lang], ""])
    scene = task.get("scene_context", "team")
    scene_map = {"solo": L["scene_solo"][lang], "team": L["scene_team"][lang], "enterprise": L["scene_enterprise"][lang]}
    lines.append(f"{L['scene'][lang]}: **{scene_map.get(scene, scene)}**")

    if winner:
        lines.append(f"\n**Winner: {winner}**")
        if rec.get("winner_rationale"):
            lines.append(f"*{rec['winner_rationale']}*")

    if rec.get("recommendation"):
        lines.append("")
        lines.append(f"**{L['recommend'][lang]}:** {rec['recommendation']}")
        if rec.get("ranked_options"):
            lines.append("")
            lines.append(L["ranking"][lang])
            for opt in rec["ranked_options"]:
                lines.append(f"- **#{opt.get('rank', '?')} {opt.get('name', '')}**: {opt.get('rationale', '')}")
        if rec.get("trade_offs"):
            lines.append("")
            lines.append(L["tradeoffs"][lang])
            for t in rec["trade_offs"]:
                # A dimension is a display label; a saved snapshot may still carry
                # a raw source number in it, so it is cleaned for display exactly
                # as the other format does.
                lines.append(f"- **{clean_label(t.get('dimension', ''))}**: "
                             f"{t.get('finding', '')}")
        if rec.get("scene_fit_note"):
            lines.append(f"\n*{L['scene_fit'][lang]}: {rec['scene_fit_note']}*")
    else:
        lines.extend(["", L["no_candidates"][lang], ""])

    # The sources this report actually relies on, derived like every other format.
    used = used_sources(rec, chains)
    lines.extend(["", L["sources_used"][lang], ""])
    if used:
        for src in used[:12]:
            note = source_provenance_note(src, lang)
            lines.append(f"- [{escape_markdown_text(src['title'])}]({src['url']}){note}")
    else:
        lines.append(L["no_used_source"][lang])

    lines.extend([
        "",
        f"**{L['confidence'][lang]}:** {rec.get('confidence', state.get('confidence', 'unknown'))}",
        "",
        L["next_steps"][lang],
        L["step1"][lang],
        L["step2"][lang],
        L["step3"][lang],
    ])

    return "\n".join(lines)
