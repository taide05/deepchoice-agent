def render(state: dict) -> str:
    task = state.get("task", {})
    chains = state.get("evidence_chains", [])
    conflicts = state.get("conflicts", [])

    strong = [c for c in chains if c["evidence_strength"] == "strong"]
    top = strong[0] if strong else (chains[0] if chains else None)

    rec = state.get("final_recommendation", {})
    lines = [
        f"# {task.get('query', 'Technology Selection')} — Evidence Brief",
        "",
        "## Conclusion",
    ]
    if rec.get("recommendation"):
        lines.append(rec["recommendation"])
        if rec.get("confidence_rationale"):
            lines.append("")
            lines.append(f"*{rec['confidence_rationale']}*")
    else:
        lines.append(top['conclusion'] if top else 'Insufficient evidence to draw a conclusion.')
    lines.extend([
        "",
        "## Why Trust This Conclusion",
    ])

    if top:
        lines.append("### Strongest Evidence")
        for src in top["sources"]:
            lines.append(f"- [{src['title']}]({src['url']}) (score: {src['score']})")
        lines.append("")
        lines.append("### Supporting Evidence Chain")
        moderate = [c for c in chains if c["evidence_strength"] == "moderate"][:3]
        for c in moderate:
            lines.append(f"- {c['conclusion']}")

    lines.extend(["", "## Counter-Evidence", ""])
    disputed = [c for c in chains if c["disputed"]]
    if disputed:
        for c in disputed:
            lines.append(f"- {c['conclusion']} (disputed)")
    else:
        lines.append("No significant counter-evidence found.")

    lines.extend(["", "## Disputes", ""])
    if conflicts:
        for c in conflicts:
            lines.append(f"- {c.get('resolution', 'unresolved')}: {c.get('reasoning', '')[:200]}")
    else:
        lines.append("No major disputes detected.")

    lines.extend(["", "## What We Don't Know", "", f"**Confidence:** {state.get('confidence', 'unknown')}"])
    for g in state.get("knowledge_gaps", []):
        lines.append(f"- {g}")

    lines.extend([
        "",
        "## If You're Making a Decision",
        "",
        "1. Verify the strongest evidence source independently",
        "2. Check if the disputed claims affect your use case",
        "3. Run a quick prototype with the recommended option",
    ])

    return "\n".join(lines)
