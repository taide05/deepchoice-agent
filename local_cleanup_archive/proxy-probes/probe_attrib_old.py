"""Attribution count comparison that works on both revisions (no names_candidate)."""
import json

from deepchoice.utils.candidate_identity import UNASSIGNED, candidate_for_source, index_sources_by_candidate

REAL = r"D:\deepchoice-precodex\outputs\e3b1c837-d2e1-46a1-b77c-c46eefe41dea\research_snapshot.json"
snap = json.load(open(REAL, encoding="utf-8"))
cands = snap["task"]["candidate_techs"]
sources = snap.get("source_scores", [])

print("counterexample 1:", candidate_for_source(
    {"title": "PostgreSQL 17 release notes", "url": "https://www.postgresql.org/docs/release-17"},
    ["PostgreSQL", "Amazon Aurora PostgreSQL with pgvector"]))
print("counterexample 1b:", candidate_for_source(
    {"title": "Amazon Aurora PostgreSQL with pgvector pricing", "url": "https://aws.amazon.com/rds/aurora"},
    ["PostgreSQL", "Amazon Aurora PostgreSQL with pgvector"]))

idx = index_sources_by_candidate(sources, cands)
for c in cands + [UNASSIGNED]:
    print(f"  {c!r}: {len(idx.get(c, []))}")
for c in cands:
    for s in idx.get(c, []):
        print(f"    [{c}] {s.get('title')!r}")
