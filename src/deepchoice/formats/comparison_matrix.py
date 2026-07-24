def _lang(query: str) -> str:
    return "zh" if any('一' <= c <= '鿿' for c in query) else "en"


def render(state: dict) -> str:
    task = state.get("task", {})
    query = task.get("query", "Technology Comparison")
    chains = state.get("evidence_chains", [])
    conflicts = state.get("conflicts", [])
    lang = _lang(query)

    L = {
        "title": {"en": f"# {query} — 5-Dimension Comparison Matrix", "zh": f"# {query} — 五维对比矩阵"},
        "col_dim": {"en": "Dimension", "zh": "维度"},
        "col_criterion": {"en": "Criterion", "zh": "判据"},
        "col_strength": {"en": "Evidence Strength", "zh": "证据强度"},
        "no_data": {"en": "Insufficient data", "zh": "数据不足"},
        "detail_table": {"en": "## Detailed Comparison", "zh": "## 技术对比详表"},
        "no_evidence": {"en": "Insufficient evidence", "zh": "证据不足"},
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
        "top_basis": {"en": "Top basis", "zh": "首选依据"},
        "best_available": {"en": "Best available basis", "zh": "最佳可用依据"},
        "confidence": {"en": "Confidence", "zh": "置信度"},
        "next_steps": {"en": "### Next Steps", "zh": "### 下一步"},
        "step1": {"en": "1. Independently verify the strongest evidence source", "zh": "1. 验证最强证据来源的独立性"},
        "step2": {"en": "2. Run targeted supplementary searches on disputed items", "zh": "2. 对争议点做针对性补充搜索"},
        "step3": {"en": "3. Build a quick prototype with the recommended option", "zh": "3. 用推荐方案做快速原型验证"},
    }

    dims = {
        "functionality": {
            "label_en": "Functionality", "label_zh": "功能覆盖",
            "kw_en": ["feature", "api", "capability", "coverage", "support"],
            "kw_zh": ["功能", "特性", "接口", "覆盖"],
        },
        "performance": {
            "label_en": "Performance", "label_zh": "性能表现",
            "kw_en": ["performance", "throughput", "latency", "benchmark", "speed", "fast"],
            "kw_zh": ["性能", "吞吐", "延迟", "基准"],
        },
        "ecosystem": {
            "label_en": "Ecosystem", "label_zh": "生态与社区",
            "kw_en": ["ecosystem", "community", "plugin", "documentation", "star"],
            "kw_zh": ["生态", "社区", "插件", "文档"],
        },
        "dx": {
            "label_en": "Developer Experience", "label_zh": "开发体验",
            "kw_en": ["learning", "developer", "debug", "productivity", "experience", "simple"],
            "kw_zh": ["学习", "开发", "调试", "效率", "简单"],
        },
        "scenario": {
            "label_en": "Scenario Fit", "label_zh": "场景适配",
            "kw_en": ["scenario", "fit", "deploy", "production", "scale", "solo"],
            "kw_zh": ["场景", "部署", "生产", "规模", "个人"],
        },
    }

    tech_names = _extract_techs(query)

    # Classify evidence chains into dimensions
    dim_results = {}
    for dim_key, dim_info in dims.items():
        rows = []
        keywords = dim_info["kw_en"] + dim_info["kw_zh"]
        for chain in chains:
            conclusion = chain.get("conclusion", "").lower()
            snippet = ""
            for s in chain.get("sources", []):
                snippet = s.get("snippet", "")
                break
            if any(kw in conclusion for kw in keywords) or any(kw in snippet.lower() for kw in keywords):
                strength = chain["evidence_strength"]
                strength_label = {"strong": "strong", "moderate": "moderate", "weak": "weak"}
                dispute = " [disputed]" if chain.get("disputed") else ""
                rows.append(f"- {chain['conclusion']} ({strength_label[strength]}){dispute}")
        dim_results[dim_key] = rows

    lines = [
        L["title"][lang],
        "",
        f"| {L['col_dim'][lang]} | {L['col_criterion'][lang]} | {L['col_strength'][lang]} |",
        f"|------|------|---------|",
    ]

    for dim_key, dim_info in dims.items():
        label = dim_info[f"label_{lang}"]
        rows = dim_results[dim_key]
        if rows:
            first_row = rows[0].lstrip("- ")
            lines.append(f"| **{label}** | {first_row} | |")
            for row in rows[1:]:
                lines.append(f"| | {row.lstrip('- ')} | |")
        else:
            lines.append(f"| **{label}** | {L['no_data'][lang]} | — |")

    lines.extend(["", L["detail_table"][lang], ""])

    if tech_names and len(tech_names) >= 2:
        lines.append(f"| {L['col_dim'][lang]} | {tech_names[0]} | {tech_names[1]} | Winner |")
        lines.append("|------|------|------|------|")
        for dim_key in ["functionality", "performance", "ecosystem", "dx", "scenario"]:
            dim_info = dims[dim_key]
            label = dim_info[f"label_{lang}"]
            rows_text = " ".join(dim_results[dim_key]) if dim_results[dim_key] else L["no_evidence"][lang]
            lines.append(f"| **{label}** | See evidence chains | See evidence chains | — |")

    lines.extend(["", L["disputes_title"][lang], ""])
    if conflicts:
        for i, c in enumerate(conflicts):
            lines.append(f"### {L['dispute'][lang]} {i+1}")
            lines.append(f"- {L['claim_a'][lang]}: {c.get('claim_a', 'N/A')}")
            lines.append(f"- {L['claim_b'][lang]}: {c.get('claim_b', 'N/A')}")
            lines.append(f"- {L['resolution'][lang]}: **{c.get('resolution', L['unresolved'][lang])}**")
            lines.append(f"- {L['basis'][lang]}: {c.get('reasoning', '')}")
            lines.append("")
    else:
        lines.append(L["no_disputes"][lang])

    rec = state.get("final_recommendation", {})
    winner = rec.get("winner", "")
    if not winner and rec.get("ranked_options"):
        winner = rec["ranked_options"][0]["name"]

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
                lines.append(f"- **#{opt['rank']} {opt['name']}**: {opt.get('rationale', '')}")
        if rec.get("trade_offs"):
            lines.append("")
            lines.append(L["tradeoffs"][lang])
            for t in rec["trade_offs"]:
                lines.append(f"- **{t.get('dimension', '')}**: {t.get('finding', '')}")
        if rec.get("scene_fit_note"):
            lines.append(f"\n*{L['scene_fit'][lang]}: {rec['scene_fit_note']}*")
    else:
        strong = [c for c in chains if c["evidence_strength"] == "strong" and not c.get("disputed")]
        if strong:
            lines.append(f"{L['top_basis'][lang]}: {strong[0]['conclusion']}")
        else:
            top_chain = chains[0] if chains else None
            if top_chain:
                strength = top_chain['evidence_strength']
                lines.append(f"{L['best_available'][lang]}: {top_chain['conclusion']} (strength: {strength})")

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


def _extract_techs(query: str) -> list[str]:
    for sep in [" vs ", " VS ", " versus ", " 对比 ", " 比较 "]:
        if sep in query:
            parts = query.split(sep)
            return [p.strip() for p in parts[:2]]
    return ["Option A", "Option B"]
