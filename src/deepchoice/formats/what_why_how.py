def _lang(query: str) -> str:
    return "zh" if any('一' <= c <= '鿿' for c in query) else "en"


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

    strong_chains = [c for c in chains if c["evidence_strength"] == "strong"]
    for c in strong_chains[:5]:
        lines.append(f"- **{c['conclusion']}**")
        for src in c["sources"]:
            lines.append(f"  - Source: [{src['title']}]({src['url']}) (score: {src['score']})")

    lines.extend(["", T["why"][lang], ""])

    for c in chains:
        tag = " [DISPUTED]" if c["disputed"] else ""
        lines.append(f"### {c['conclusion']}{tag}")
        lines.append(f"**{T['evidence_strength'][lang]}:** {c['evidence_strength']}")
        for src in c["sources"]:
            lines.append(f"- [{src['title']}]({src['url']}) — score: {src['score']}")
        lines.append("")

    if conflicts:
        lines.extend([T["disputes"][lang], ""])
        for i, c in enumerate(conflicts):
            lines.append(f"### {T['conflict'][lang]} {i+1}: {c.get('resolution', 'unresolved')}")
            lines.append(f"- {T['claim_a'][lang]}: {c.get('claim_a', '')} (score: {c.get('source_a', {}).get('score', 'N/A')})")
            lines.append(f"- {T['claim_b'][lang]}: {c.get('claim_b', '')} (score: {c.get('source_b', {}).get('score', 'N/A')})")
            lines.append(f"- {T['resolution'][lang]}: {c.get('reasoning', '')}")
            lines.append(f"- {T['key_factor'][lang]}: {c.get('key_factor', '')}")
            lines.append(f"- {T['confidence'][lang]}: {c.get('confidence', 'low')}")
            lines.append("")

    if gaps:
        lines.extend([T["unknown"][lang], ""])
        for g in gaps:
            lines.append(f"- {g}")
        lines.append("")

    rec = state.get("final_recommendation", {})
    lines.extend([T["how"][lang], ""])

    if rec.get("recommendation"):
        lines.append(f"**{T['recommendation'][lang]}:** {rec['recommendation']}")
        lines.append("")
        lines.append(f"**{T['confidence'][lang]}:** {rec.get('confidence', state.get('confidence', 'unknown'))}")
        if rec.get("confidence_rationale"):
            lines.append(f"*{rec['confidence_rationale']}*")
        lines.append("")
        if rec.get("ranked_options"):
            lines.append(T["ranked_options"][lang])
            for opt in rec["ranked_options"]:
                lines.append(f"- **#{opt['rank']} {opt['name']}**: {opt.get('rationale', '')}")
            lines.append("")
        if rec.get("trade_offs"):
            lines.append(T["trade_offs"][lang])
            for t in rec["trade_offs"]:
                lines.append(f"- **{t.get('dimension', '')}**: {t.get('finding', '')}")
            lines.append("")
        if rec.get("scene_fit_note"):
            lines.append(f"**{T['scene_fit'][lang]}:** {rec['scene_fit_note']}")
            lines.append("")
    else:
        lines.extend([
            f"**{T['confidence'][lang]}:** {state.get('confidence', 'unknown')}",
            "",
            T["starting_point"][lang],
            T["starting_hint"][lang],
            "",
        ])

    lines.append(T["references"][lang])
    for c in chains:
        for src in c["sources"]:
            lines.append(f"- [{src['title']}]({src['url']})")

    return "\n".join(lines)
