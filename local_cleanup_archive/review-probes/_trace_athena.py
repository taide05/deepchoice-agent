"""Problem B: Athena has a body yet is reported as having no material.

Trace the Athena source through every stage of the captured run.
"""
import io
import json
import pathlib
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"D:\deepchoice-precodex\src")

RUN = pathlib.Path(r"D:\deepchoice-precodex\outputs"
                   r"\8049500c-bd39-44e4-81bb-a1fbbebac780")
state = json.loads((RUN / "research_snapshot.json").read_text(encoding="utf-8"))

print("=== 1. stage: search_results (raw retrieval) ===")
for ch in state.get("search_results") or []:
    for r in ch.get("results") or []:
        if "athena" in f"{r.get('title','')} {r.get('url','')}".lower():
            print(f"  [{ch.get('source')}] {r.get('title')}")
            print(f"      url: {r.get('url')}")
            print(f"      snippet len: {len(r.get('snippet') or '')}")
            print(f"      has_body key: {'has_body' in r} -> {r.get('has_body', '<absent>')}")

print("\n=== 2. stage: source_scores (after evaluation) ===")
for s in state.get("source_scores") or []:
    if "athena" in f"{s.get('title','')} {s.get('url','')}".lower():
        print(f"  {s.get('title')}")
        print(f"      score={s.get('total_score')} type={s.get('source_type')}")
        print(f"      snippet len: {len(s.get('snippet') or '')}")
        print(f"      has_body key: {'has_body' in s} -> {s.get('has_body', '<absent>')}")
        print(f"      snippet[:100]: {(s.get('snippet') or '')[:100]!r}")

print("\n=== 3. stage: evidence_chains ===")
for c in state.get("evidence_chains") or []:
    for s in c.get("sources", []):
        if "athena" in f"{s.get('title','')} {s.get('url','')}".lower():
            print(f"  chain: {c.get('conclusion')[:60]}")
            print(f"  strength={c.get('evidence_strength')} disputed={c.get('disputed')}")
            print(f"      snippet len: {len(s.get('snippet') or '')}")
            print(f"      has_body key: {'has_body' in s} -> {s.get('has_body', '<absent>')}")

print("\n=== 4. stage: candidate attribution (the index the What section uses) ===")
from deepchoice.utils.candidate_identity import candidate_for_source, has_factual_content

candidates = state["task"]["candidate_techs"]
print(f"  candidates: {candidates}")
seen = set()
for c in state.get("evidence_chains") or []:
    for s in c.get("sources", []):
        key = (s.get("title"), s.get("url"))
        if key in seen:
            continue
        seen.add(key)
        if "athena" not in f"{s.get('title','')} {s.get('url','')}".lower():
            continue
        print(f"  source: {s.get('title')}")
        print(f"      has_factual_content: {has_factual_content(s)}")
        print(f"      attributed to: {candidate_for_source(s, candidates)!r}")
        # What would the What-section see for the Athena candidate?
        for cand in candidates:
            from deepchoice.utils.candidate_identity import names_candidate
            print(f"      names_candidate(title, {cand[:30]!r}) = "
                  f"{names_candidate(s.get('title',''), cand)}")
