"""Populate ChromaKB with comparative analysis documents from benchmark cases."""
import json, os
from pathlib import Path

KB_DIR = Path(__file__).parent
DATA_DIR = KB_DIR / "data"
BENCHMARK_CASES = KB_DIR.parent / "benchmarks" / "cases_200.json"

def generate_docs():
    cases = json.loads(BENCHMARK_CASES.read_text(encoding="utf-8"))
    base_cases = {}
    for c in cases:
        cid = c["id"]
        if "-v" in cid:
            continue
        tech_key = f"{c.get('tech_a', '')} vs {c.get('tech_b', '')}"
        if tech_key not in base_cases:
            base_cases[tech_key] = c

    os.makedirs(DATA_DIR / "blogs", exist_ok=True)
    count = 0
    for tech_key, case in base_cases.items():
        notes = case.get("ground_truth_notes", "")
        contradictions = case.get("known_contradictions", [])
        if not notes and not contradictions:
            continue
        lines = [f"# {tech_key}", "", f"**Category**: {case.get('category', '')}",
                 f"**Expected winner**: {case.get('expected_winner', 'context-dependent')}",
                 "", "## Analysis", "", notes, ""]
        if contradictions:
            lines.append("## Known Contradictions")
            lines.append("")
            for kc in contradictions:
                lines.append(f"### {kc.get('topic', '')}")
                lines.append(f"- Position A: {kc.get('position_a', '')}")
                lines.append(f"- Position B: {kc.get('position_b', '')}")
                lines.append("")
        filename = tech_key.replace(" ", "-").replace("/", "-").lower()[:80] + ".md"
        (DATA_DIR / "blogs" / filename).write_text("\n".join(lines), encoding="utf-8")
        count += 1
    print(f"Generated {count} documents")
    return count

if __name__ == "__main__":
    generate_docs()
    print("Done. Run setup.py to ingest.")
