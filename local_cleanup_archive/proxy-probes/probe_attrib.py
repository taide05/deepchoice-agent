"""Attribution counterexamples. Read-only; prints counts for HEAD and (optionally) 1b010f4."""
import json
import sys

from deepchoice.utils.candidate_identity import (
    UNASSIGNED,
    candidate_for_source,
    index_sources_by_candidate,
    names_candidate,
)

REAL = r"D:\deepchoice-precodex\outputs\e3b1c837-d2e1-46a1-b77c-c46eefe41dea\research_snapshot.json"

print("### counterexample 1: 'PostgreSQL 17 release notes'")
cands = ["PostgreSQL", "Amazon Aurora PostgreSQL with pgvector"]
src = {"title": "PostgreSQL 17 release notes",
       "url": "https://www.postgresql.org/docs/release-17"}
print("   candidate_for_source ->", candidate_for_source(src, cands))
print("   names candidate 'Amazon Aurora PostgreSQL with pgvector'?",
      names_candidate(src["title"], "Amazon Aurora PostgreSQL with pgvector"))
print("   names candidate 'PostgreSQL'?", names_candidate(src["title"], "PostgreSQL"))

print("### counterexample 2: real snapshot 29 sources vs its own candidate list")
snap = json.load(open(REAL, encoding="utf-8"))
cands = snap["task"]["candidate_techs"]
print("   candidates:", cands)
sources = snap.get("source_scores", [])
print("   source_scores:", len(sources))

idx = index_sources_by_candidate(sources, cands)
for c in cands + [UNASSIGNED]:
    print(f"   {c!r}: {len(idx.get(c, []))}")

print("   -- per attributed source: does title/url name the candidate? --")
bad = 0
for c in cands:
    for s in idx.get(c, []):
        named = names_candidate(s.get("title", ""), c) or names_candidate(s.get("url", ""), c)
        if not named:
            bad += 1
            print("   !! NOT NAMED:", c, "|", s.get("title"), "|", s.get("url"))
print("   sources attributed to a candidate they do not name:", bad)

print("   -- attributed sources --")
for c in cands:
    for s in idx.get(c, []):
        print(f"     [{c}] {s.get('title')!r} {s.get('url')}")

print("   -- unassigned sources --")
for s in idx.get(UNASSIGNED, []):
    print(f"     {s.get('title')!r} {s.get('url')}")

print("### chain sources (29) too")
chains = snap.get("evidence_chains", [])
flat = [s for c in chains for s in c.get("sources", [])]
idx2 = index_sources_by_candidate(flat, cands)
for c in cands + [UNASSIGNED]:
    print(f"   {c!r}: {len(idx2.get(c, []))}")
bad2 = sum(1 for c in cands for s in idx2.get(c, [])
           if not (names_candidate(s.get("title", ""), c) or names_candidate(s.get("url", ""), c)))
print("   not-named count:", bad2)
