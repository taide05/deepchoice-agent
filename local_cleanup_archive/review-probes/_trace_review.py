import io
import inspect
import json
import pathlib
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"D:\deepchoice-precodex\src")

RUN = pathlib.Path(r"D:\deepchoice-precodex\outputs"
                   r"\8049500c-bd39-44e4-81bb-a1fbbebac780")
state = json.loads((RUN / "research_snapshot.json").read_text(encoding="utf-8"))

print("=== token_usage as stored (all rows) ===")
for u in state.get("token_usage") or []:
    print("  ", json.dumps(u, ensure_ascii=False))

print("\n=== which agent writes the recommendation the report shows? ===")
TEXT_FIELDS = ("recommendation", "winner_rationale", "evidence_summary",
               "scene_fit_note", "confidence_rationale")
raw_markers = [f for f in TEXT_FIELDS
               if "[[" in str((state.get("final_recommendation") or {}).get(f) or "")]
print("  fields still holding raw [[N]] markers:", raw_markers)
for f in raw_markers:
    print(f"    {f}: {str(state['final_recommendation'][f])[:140]}")

print("\n=== the run path: which nodes ran? ===")
print("  agent_timing keys:", sorted((state.get("agent_timing") or {}).keys()))
qs = state.get("quality_signals") or []
print("  quality_signals agents:", [q.get("agent") for q in qs])
print("  self_reviewer signal present:",
      any(q.get("agent") == "self_reviewer" for q in qs))
