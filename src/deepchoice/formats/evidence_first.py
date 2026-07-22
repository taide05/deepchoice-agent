def _lang(query: str) -> str:
    return "zh" if any('一' <= c <= '鿿' for c in query) else "en"


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
        "unknown": {"en": "## What We Don't Know", "zh": "## 知识盲区"},
        "confidence": {"en": "Confidence", "zh": "置信度"},
        "decision": {"en": "## If You're Making a Decision", "zh": "## 决策建议"},
        "step1": {"en": "1. Verify the strongest evidence source independently", "zh": "1. 独立验证最强证据来源"},
        "step2": {"en": "2. Check if the disputed claims affect your use case", "zh": "2. 检查争议项是否影响你的使用场景"},
        "step3": {"en": "3. Run a quick prototype with the recommended option", "zh": "3. 用推荐方案做快速原型验证"},
    }

    strong = [c for c in chains if c["evidence_strength"] == "strong"]
    top = strong[0] if strong else (chains[0] if chains else None)

    rec = state.get("final_recommendation", {})
    lines = [
        f"# {query}{T['title_suffix'][lang]}",
        "",
        T["conclusion"][lang],
    ]
    if rec.get("recommendation"):
        lines.append(rec["recommendation"])
        if rec.get("confidence_rationale"):
            lines.append("")
            lines.append(f"*{rec['confidence_rationale']}*")
    else:
        lines.append(top['conclusion'] if top else T["insufficient"][lang])
    lines.extend(["", T["trust"][lang]])

    if top:
        lines.append(T["strongest"][lang])
        for src in top["sources"]:
            lines.append(f"- [{src['title']}]({src['url']}) (score: {src['score']})")
        lines.append("")
        lines.append(T["supporting"][lang])
        moderate = [c for c in chains if c["evidence_strength"] == "moderate"][:3]
        for c in moderate:
            lines.append(f"- {c['conclusion']}")

    lines.extend(["", T["counter"][lang], ""])
    disputed = [c for c in chains if c["disputed"]]
    if disputed:
        for c in disputed:
            lines.append(f"- {c['conclusion']} (disputed)")
    else:
        lines.append(T["no_counter"][lang])

    lines.extend(["", T["disputes"][lang], ""])
    if conflicts:
        for c in conflicts:
            lines.append(f"- {c.get('resolution', 'unresolved')}: {c.get('reasoning', '')[:200]}")
    else:
        lines.append(T["no_disputes"][lang])

    lines.extend(["", T["unknown"][lang], "", f"**{T['confidence'][lang]}:** {state.get('confidence', 'unknown')}"])
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
