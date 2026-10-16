"""Verify the candidate-identity fix against the failed run's own inputs."""
import sys
import json
import pathlib
import asyncio

sys.path.insert(0, r"D:\deepchoice-precodex\src")

from deepchoice.retrievers.official import OfficialSearch, TECH_DOCS
from deepchoice.utils.candidate_identity import (
    bounded_content_summary,
    candidate_tokens,
    mapping_key_for,
    split_navigation_label,
)
from deepchoice.formats.what_why_how import render

results = []


def check(label, ok, detail=""):
    results.append((label, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")


snap = json.loads((pathlib.Path(r"D:\deepchoice-precodex\outputs"
                                r"\e3b1c837-d2e1-46a1-b77c-c46eefe41dea")
                   / "research_snapshot.json").read_text(encoding="utf-8"))
candidates = snap["task"]["candidate_techs"]
print("candidates:", candidates)

print("\n--- 1. ordinary words must not introduce an out-of-list product ---")
keys = set(mapping_key_for(candidates, TECH_DOCS))
print("  mapping keys named by candidates:", sorted(keys))
check("'vector' is not treated as a candidate term",
      "vector" not in candidate_tokens(candidates),
      str(candidate_tokens(candidates)))
check("vector.dev is not among the keys candidates name",
      "vector" not in keys)
# The failing path: an adapted query full of ordinary words.
adapted = ["vector database comparison", "semantic search latency benchmark",
           "ann index memory usage"]
search = OfficialSearch()


async def run_retriever(cands):
    return await search._do_search(
        "which vector store", [], 7, adapted_queries=adapted, candidate_techs=cands)


out = asyncio.run(run_retriever(candidates))
urls = [r["url"] for r in out]
print("  official results:", urls)
check("no vector.dev result", not any("vector.dev" in u for u in urls))
check("candidate PostgreSQL docs still selected",
      any("postgresql.org" in u for u in urls), str(urls))

no_candidates = asyncio.run(run_retriever([]))
check("no declared candidate yields no official source",
      no_candidates == [], str(no_candidates))

print("\n--- 2. a navigation caption cannot stand in for a finding ---")
content, nav = split_navigation_label("Official documentation site for vector")
check("caption recognised as navigation only", nav and content == "")
summary = bounded_content_summary(
    {"title": "vector — Official Documentation", "snippet":
     "Official documentation site for vector", "url": "https://vector.dev/docs/"})
check("summary states a gap instead of the caption",
      "NO CONTENT RETRIEVED" in summary, summary[:90])
real = bounded_content_summary(
    {"title": "Postgres With pgvector vs Pinecone",
     "snippet": "The 2024 HNSW deep-dive reports pgvector HNSW at sub-20ms for top-10 "
                "queries on a 1M 768-dimension dataset."})
check("real body text is preserved", "sub-20ms" in real, real[:80])

print("\n--- 3. saved URLs and bodies reach the synthesis input ---")
from deepchoice.agents.conclusion_synthesizer import _summarize_chains

text, mapping = _summarize_chains(snap.get("evidence_chains", []), candidates)
check("declared candidates listed in the prompt",
      all(c in text for c in candidates), str([c for c in candidates if c not in text]))
check("source URLs present", "url: http" in text)
check("bounded content present", "content:" in text)
check("no bare title+score lines remain",
      "score:" in text and "url:" in text and "content:" in text)
check("navigation-only source is marked as carrying no content",
      "NO CONTENT RETRIEVED" in text or "content: " in text)
check("out-of-list product is not offered as a candidate",
      "vector.dev" not in text.split("Evidence sources")[0])

print("\n--- 4. all candidates appear in What even with zero strong chains ---")
strong = sum(1 for c in snap.get("evidence_chains", [])
             if c.get("evidence_strength") == "strong")
out_report = render(snap)
what = out_report.split("## Why")[0]
check("this run indeed has zero strong chains", strong == 0, f"strong={strong}")
for candidate in candidates:
    check(f"What renders candidate: {candidate[:38]}", candidate in what)

print("\n--- 5. the renderer no longer guesses citations ---")
from deepchoice.formats.what_why_how import _cited_sources

chain_sources = {c.get("conclusion", "").lower(): [f"[{s.get('title')}]({s.get('url')})"]
                 for c in snap.get("evidence_chains", []) for s in c.get("sources", [])[:1]}
uncited = "No citation here at all, just prose about latency."
check("text without a citation yields no attached sources",
      _cited_sources(uncited, chain_sources) == [])
cited = "Latency is bounded [[1]] and costs less [Source: Pinecone — Official Documentation]."
got = _cited_sources(cited, chain_sources)
check("only the cited source is attached",
      all("Pinecone" in g for g in got), str(got))

print("\n--- summary ---")
failed = [r for r in results if not r[1]]
for label, ok, _ in results:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
print(f"  {len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
