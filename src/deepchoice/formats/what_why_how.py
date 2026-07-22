def render(state: dict) -> str:
    task = state.get("task", {})
    chains = state.get("evidence_chains", [])
    conflicts = state.get("conflicts", [])
    gaps = state.get("knowledge_gaps", [])

    lines = [
        f"# {task.get('query', 'Technology Selection')} — Decision Brief",
        "",
    ]

    data_note = state.get("data_source_note", "")
    if data_note:
        lines.extend([f"> {data_note}", ""])

    lines.extend([
        "## What: Understanding the Candidates",
        "",
    ])

    strong_chains = [c for c in chains if c["evidence_strength"] == "strong"]
    for c in strong_chains[:5]:
        lines.append(f"- **{c['conclusion']}**")
        for src in c["sources"]:
            lines.append(f"  - Source: [{src['title']}]({src['url']}) (score: {src['score']})")

    lines.extend(["", "## Why: Evidence-Driven Judgment", ""])

    for c in chains:
        tag = " [DISPUTED]" if c["disputed"] else ""
        lines.append(f"### {c['conclusion']}{tag}")
        lines.append(f"**Evidence strength:** {c['evidence_strength']}")
        for src in c["sources"]:
            lines.append(f"- [{src['title']}]({src['url']}) — score: {src['score']}")
        lines.append("")

    if conflicts:
        lines.extend(["## Disputes & Resolutions", ""])
        for i, c in enumerate(conflicts):
            lines.append(f"### Conflict {i+1}: {c.get('resolution', 'unresolved')}")
            lines.append(f"- Claim A: {c.get('claim_a', '')} (score: {c.get('source_a', {}).get('score', 'N/A')})")
            lines.append(f"- Claim B: {c.get('claim_b', '')} (score: {c.get('source_b', {}).get('score', 'N/A')})")
            lines.append(f"- Resolution: {c.get('reasoning', '')}")
            lines.append(f"- Key factor: {c.get('key_factor', '')}")
            lines.append(f"- Confidence: {c.get('confidence', 'low')}")
            lines.append("")

    if gaps:
        lines.extend(["## What We Don't Know Yet", ""])
        for g in gaps:
            lines.append(f"- {g}")
        lines.append("")

    rec = state.get("final_recommendation", {})
    lines.extend([
        "## How: Action Path",
        "",
    ])
    if rec.get("recommendation"):
        lines.append(f"**Recommendation:** {rec['recommendation']}")
        lines.append("")
        lines.append(f"**Confidence:** {rec.get('confidence', state.get('confidence', 'unknown'))}")
        if rec.get("confidence_rationale"):
            lines.append(f"*{rec['confidence_rationale']}*")
        lines.append("")
        if rec.get("ranked_options"):
            lines.append("### Ranked Options")
            for opt in rec["ranked_options"]:
                lines.append(f"- **#{opt['rank']} {opt['name']}**: {opt.get('rationale', '')}")
            lines.append("")
        if rec.get("trade_offs"):
            lines.append("### Trade-offs")
            for t in rec["trade_offs"]:
                lines.append(f"- **{t.get('dimension', '')}**: {t.get('finding', '')}")
            lines.append("")
        if rec.get("scene_fit_note"):
            lines.append(f"**Scene Fit:** {rec['scene_fit_note']}")
            lines.append("")
    else:
        lines.extend([
            f"**Confidence:** {state.get('confidence', 'unknown')}",
            "",
            "### Starting Point",
            "Based on the evidence above, start with the highest-scored option that matches your scene context.",
            "",
        ])
    lines.extend([
        "### References",
    ])
    for c in chains:
        for src in c["sources"]:
            lines.append(f"- [{src['title']}]({src['url']})")

    return "\n".join(lines)
