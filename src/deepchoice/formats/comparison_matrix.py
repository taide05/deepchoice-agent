def render(state: dict) -> str:
    task = state.get("task", {})
    chains = state.get("evidence_chains", [])
    conflicts = state.get("conflicts", [])

    # Extract tech names from query: "A vs B" -> ["A", "B"]
    query = task.get("query", "Technology Comparison")
    tech_names = _extract_techs(query)

    # Build dimension scores from evidence chains
    dimensions = {
        "functionality": {"label": "功能覆盖", "rows": [], "score": "—"},
        "performance": {"label": "性能表现", "rows": [], "score": "—"},
        "ecosystem": {"label": "生态与社区", "rows": [], "score": "—"},
        "dx": {"label": "开发体验", "rows": [], "score": "—"},
        "scenario": {"label": "场景适配", "rows": [], "score": "—"},
    }

    dim_keywords = {
        "functionality": ["feature", "功能", "api", "capability", "coverage", "support"],
        "performance": ["performance", "性能", "throughput", "latency", "benchmark", "speed", "fast"],
        "ecosystem": ["ecosystem", "生态", "community", "plugin", "documentation", "star"],
        "dx": ["learning", "学习", "developer", "debug", "productivity", "experience", "simple"],
        "scenario": ["scenario", "场景", "fit", "deploy", "production", "scale", "solo"],
    }

    for chain in chains:
        conclusion = chain.get("conclusion", "").lower()
        snippet = ""
        for s in chain.get("sources", []):
            snippet = s.get("snippet", "")
            break

        for dim, keywords in dim_keywords.items():
            if any(kw in conclusion for kw in keywords) or any(kw in snippet.lower() for kw in keywords):
                strength = chain["evidence_strength"]
                dim_label = {"strong": "强", "moderate": "中", "weak": "弱"}[strength]
                dispute = " [争议]" if chain.get("disputed") else ""
                dim["rows"].append(f"- {chain['conclusion']} ({dim_label}){dispute}")

    lines = [
        f"# {query} — 五维对比矩阵",
        "",
        "| 维度 | 判据 | 证据强度 |",
        "|------|------|---------|",
    ]

    for dim_key, dim_data in dimensions.items():
        label = dim_data["label"]
        if dim_data["rows"]:
            first_row = dim_data["rows"][0].lstrip("- ")
            lines.append(f"| **{label}** | {first_row} | |")
            for row in dim_data["rows"][1:]:
                lines.append(f"| | {row.lstrip('- ')} | |")
        else:
            lines.append(f"| **{label}** | 数据不足 | — |")

    lines.extend(["", "## 技术对比详表", ""])

    # Build tech comparison rows
    if tech_names and len(tech_names) >= 2:
        lines.append(f"| 维度 | {tech_names[0]} | {tech_names[1]} | 胜出 |")
        lines.append("|------|------|------|------|")
        for dim_key in ["functionality", "performance", "ecosystem", "dx", "scenario"]:
            dim_data = dimensions[dim_key]
            findings = " ".join(dim_data["rows"]) if dim_data["rows"] else "证据不足"
            lines.append(f"| **{dim_data['label']}** | 见证据链 | 见证据链 | — |")

    lines.extend(["", "## 争议与分歧", ""])
    if conflicts:
        for i, c in enumerate(conflicts):
            lines.append(f"### 争议 {i+1}")
            lines.append(f"- A方: {c.get('claim_a', 'N/A')}")
            lines.append(f"- B方: {c.get('claim_b', 'N/A')}")
            lines.append(f"- 裁决: **{c.get('resolution', '未解决')}**")
            lines.append(f"- 依据: {c.get('reasoning', '')}")
            lines.append("")
    else:
        lines.append("本次搜索未发现显著争议。")

    rec = state.get("final_recommendation", {})
    lines.extend(["", "## 建议", ""])
    scene = task.get("scene_context", "team")
    scene_map = {"solo": "个人开发者", "team": "中型团队", "enterprise": "企业级"}
    lines.append(f"场景: **{scene_map.get(scene, scene)}**")

    if rec.get("recommendation"):
        lines.append("")
        lines.append(f"**推荐:** {rec['recommendation']}")
        if rec.get("ranked_options"):
            lines.append("")
            lines.append("### 排序")
            for opt in rec["ranked_options"]:
                lines.append(f"- **#{opt['rank']} {opt['name']}**: {opt.get('rationale', '')}")
        if rec.get("trade_offs"):
            lines.append("")
            lines.append("### 权衡")
            for t in rec["trade_offs"]:
                lines.append(f"- **{t.get('dimension', '')}**: {t.get('finding', '')}")
        if rec.get("scene_fit_note"):
            lines.append(f"\n*场景适配: {rec['scene_fit_note']}*")
    else:
        # Pick top finding
        strong = [c for c in chains if c["evidence_strength"] == "strong" and not c.get("disputed")]
        if strong:
            lines.append(f"首选依据: {strong[0]['conclusion']}")
        else:
            top_chain = chains[0] if chains else None
            if top_chain:
                lines.append(f"最佳可用依据: {top_chain['conclusion']} (强度: {top_chain['evidence_strength']})")

    lines.extend([
        "",
        f"**置信度:** {rec.get('confidence', state.get('confidence', 'unknown'))}",
        "",
        "### 下一步",
        "1. 验证最强证据来源的独立性",
        "2. 对争议点做针对性补充搜索",
        "3. 用推荐方案做快速原型验证",
    ])

    return "\n".join(lines)


def _extract_techs(query: str) -> list[str]:
    for sep in [" vs ", " VS ", " versus ", " 对比 ", " 比较 "]:
        if sep in query:
            parts = query.split(sep)
            return [p.strip() for p in parts[:2]]
    return ["方案A", "方案B"]
