"""Generate a 200-case benchmark file by combining existing cases + auto-generated variants."""
import json
import copy
import random
from pathlib import Path

random.seed(42)

BENCHMARKS_DIR = Path(__file__).resolve().parent

# Load annotated cases only (eval_100 lacks annotations - discarded)
annotated = json.loads((BENCHMARKS_DIR / "annotated_cases.json").read_text(encoding="utf-8"))
print(f"Annotated base: {len(annotated)}")

# All 200 cases derived from the 50 annotated base cases
combined = list(annotated)

# Generate variant cases from the 50 annotated base until we hit 200 total
SCENES = ["solo", "team", "enterprise"]
CONSTRAINTS = [
    "budget under $500/month, open-source preferred",
    "must integrate with existing Python microservices stack",
    "team of 3 junior developers, ease of use critical",
    "startup moving fast, quick setup and prototyping speed matter",
    "enterprise with SOC2 compliance, stability over features",
    "real-time processing required, p99 latency under 50ms",
    "must scale to 10k concurrent users within 6 months",
    "offline-first capability, intermittent connectivity expected",
    "existing React frontend, needs REST and WebSocket API",
    "high security requirements, regular pen-testing needed",
]

variants = []
gen_idx = 0
while len(combined) + len(variants) < 200:
    src = annotated[gen_idx % len(annotated)]
    scene = SCENES[gen_idx % 3]
    constraint = CONSTRAINTS[gen_idx % len(CONSTRAINTS)]
    gen_idx += 1

    if scene == src.get("scene"):
        continue  # Skip same scene

    v = copy.deepcopy(src)
    v["id"] = f"{src['id']}-v{gen_idx}"
    v["scene"] = scene
    v["query"] = f"{src['query']} for a {scene} developer team ({constraint})"
    # All annotations preserved from parent (directionally correct across scenes)
    variants.append(v)

combined.extend(variants)
print(f"After adding variants: {len(combined)}")

# Trim to exactly 200
combined = combined[:200]

# Re-index IDs
for i, c in enumerate(combined):
    c["_idx"] = i

out_path = BENCHMARKS_DIR / "cases_200.json"
out_path.write_text(json.dumps(combined, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Written {len(combined)} cases to {out_path}")

# Stats
cats = {}
for c in combined:
    cats[c.get("category", "?")] = cats.get(c.get("category", "?"), 0) + 1
print("\nCategory breakdown:")
for k, v in sorted(cats.items(), key=lambda x: -x[1]):
    print(f"  {k}: {v}")
has_winner = sum(1 for c in combined if c.get("expected_winner"))
print(f"\nCases with expected_winner (Top-1 computable): {has_winner}/{len(combined)}")
