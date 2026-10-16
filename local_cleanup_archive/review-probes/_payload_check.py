import io
import json
import pathlib
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"D:\deepchoice-precodex\src")

from deepchoice.utils.candidate_identity import bounded_content_summary

state = json.loads((pathlib.Path(r"D:\deepchoice-precodex\outputs"
                                 r"\8049500c-bd39-44e4-81bb-a1fbbebac780")
                    / "research_snapshot.json").read_text(encoding="utf-8"))

# Rebuild exactly the block the node now builds.
chains_summary = []
for c in state.get("evidence_chains", []):
    strength = c.get("evidence_strength", "unknown")
    conclusion = c.get("conclusion", "")[:200]
    chains_summary.append(f"[{strength}] {conclusion}")
    for s in (c.get("sources") or [])[:2]:
        chains_summary.append(f"    source: {s.get('title', '?')[:80]}")
        chains_summary.append(f"      text: {bounded_content_summary(s, limit=700)}")
chains_text = "\n".join(chains_summary) if chains_summary else "No evidence chains."

print(f"chains_text length: {len(chains_text)} chars")
print("contains the source's real scale '500 亿' :", "500 亿" in chains_text)
print("contains the reported wrong scale '5 万亿':", "5 万亿" in chains_text)
print("contains 'Athena' source text            :",
      "per terabyte scanned" in chains_text.lower() or "athena" in chains_text.lower())
print()
i = chains_text.find("InfoQ")
print("=== the chain that carries the scale claim ===")
print(chains_text[max(0, i - 120):i + 900])
