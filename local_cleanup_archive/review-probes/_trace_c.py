"""Problem C: does the model or the post-processing decide the ranking and numbers?

Also count unconverted citation markers in the rendered report.
"""
import io
import json
import pathlib
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"D:\deepchoice-precodex\src")

RUN = pathlib.Path(r"D:\deepchoice-precodex\outputs"
                   r"\8049500c-bd39-44e4-81bb-a1fbbebac780")
report = (RUN / "report.md").read_text(encoding="utf-8")
state = json.loads((RUN / "research_snapshot.json").read_text(encoding="utf-8"))
rec = state.get("final_recommendation") or {}

print("=== A. what the model returned (stored, post-processed) ===")
print("  winner:", repr(rec.get("winner")))
print("  confidence:", rec.get("confidence"))
print("  ranked_options:", [(o.get("rank"), o.get("name")) for o in rec.get("ranked_options") or []])
print("  trade_offs:", [t.get("dimension") for t in rec.get("trade_offs") or []])

print("\n=== B. unconverted [[N]] markers in the rendered report ===")
markers = re.findall(r"\[\[\d+\]\]", report)
print(f"  count: {len(markers)} -> {sorted(set(markers))[:12]}")
for m in sorted(set(markers)):
    for line in report.splitlines():
        if m in line:
            i = line.find(m)
            print(f"    {m}: ...{line[max(0,i-90):i+30]}...")
            break

print("\n=== C. does the report decide the ranking, or does code? ===")
import inspect

from deepchoice.agents import conclusion_synthesizer as cs

src = inspect.getsource(cs)
for name in ("_validate_winner", "_bind_citations", "_sanitize_citations"):
    print(f"  {name}: {'present' if name in src else 'absent'}")

print("\n  winner validation body:")
body = inspect.getsource(cs._validate_winner)
print("   ", body.replace("\n", "\n    ")[:1200])

print("\n=== D. ranking source: is ranked_options order taken from the model? ===")
for o in rec.get("ranked_options") or []:
    print(f"  #{o.get('rank')} {o.get('name')}")
    print(f"      rationale: {(o.get('rationale') or '')[:160]}")
