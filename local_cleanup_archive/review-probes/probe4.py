"""End-to-end drive: real retriever -> evaluator -> chain -> report, and the
discriminating case has_body=False with a REAL-LOOKING non-empty snippet."""
from __future__ import annotations

import asyncio

import deepchoice
print("### module:", deepchoice.__file__)

from deepchoice.agents.evidence_chain import build_evidence_chain
from deepchoice.agents.source_evaluator import SourceEvaluatorAgent
from deepchoice.formats.citations import number_sources
from deepchoice.formats.evidence_first import render as render_ef
from deepchoice.formats.what_why_how import render as render_www
from deepchoice.retrievers.official import OfficialSearch
from deepchoice.utils.candidate_identity import has_factual_content

print("\n== (a) real official retriever -> evaluator -> chain -> report ==")
res = asyncio.run(OfficialSearch()._do_search(
    "pgvector on Amazon RDS for PostgreSQL", [], 10, [], ["PostgreSQL"]))
print("   retriever entries:", [(r["url"], r.get("has_body")) for r in res])

ev = asyncio.run(SourceEvaluatorAgent().run({"search_results": [
    {"source": "official", "results": res},
    {"source": "tavily", "results": [
        {"url": "https://example.com/bench", "title": "pgvector HNSW benchmark",
         "snippet": "sub-20ms on 1M vectors.", "has_body": True}]}]}))
for s in ev["source_scores"]:
    print(f"   evaluator: {s['title'][:44]!r} has_body={s.get('has_body')!r} score={s['total_score']}")

chains = build_evidence_chain(ev["source_scores"], [])
for c in chains:
    src = c["sources"][0]
    print(f"   chain: strength={c['evidence_strength']:8s} has_body={src.get('has_body')!r} "
          f"citable_at_report={has_factual_content(src)} url={src['url']}")
reg = number_sources(chains)
print("   registry:", [r["url"] for r in reg])
nav_urls = [s["url"] for s in ev["source_scores"] if s.get("has_body") is False]
st = {"task": {"query": "pgvector on RDS", "candidate_techs": ["PostgreSQL"]},
      "evidence_chains": chains, "conflicts": [], "knowledge_gaps": [],
      "final_recommendation": {}, "confidence": "medium"}
for nm, rend in (("what_why_how", render_www), ("evidence_first", render_ef)):
    body = rend(st)
    print(f"   {nm}: body-less URLs linked as [title](url): "
          f"{[u for u in nav_urls if f']({u})' in body and f'[{next(s for s in ev['source_scores'] if s['url'] == u)['title']}]({u})' in body]}")
    print(f"   {nm}: numbered in registry: {[u for u in nav_urls if u in {r['url'] for r in reg}]}")

print("\n== (b) has_body=False with a REAL-LOOKING snippet (no marker-shaped text) ==")
tricky = {"url": "https://www.postgresql.org/docs/", "has_body": False,
          "title": "PostgreSQL — Official Documentation",
          "snippet": "PostgreSQL 17 improves vacuum performance by 30% on large tables."}
print("   snippet shape alone would pass as content:", has_factual_content({"snippet": tricky["snippet"]}))
print("   with the marker present, citable:", has_factual_content(tricky))
print("   numbered by number_sources:", bool(number_sources([{"sources": [tricky]}])))
from deepchoice.agents.conclusion_synthesizer import _sanitize_citations, _summarize_chains
_t, m = _summarize_chains([{"conclusion": "c", "evidence_strength": "moderate",
                            "sources": [tricky]}], ["PostgreSQL"])
print("   in the synthesis citation mapping:", tricky["title"] in m.values())
print("   survives the citation sanitiser:",
      tricky["title"] in _sanitize_citations(
          {"recommendation": "x [Source: " + tricky["title"] + "]."},
          [{"conclusion": "c", "sources": [tricky]}])["recommendation"])
sec = render_ef({"task": {"query": "q", "candidate_techs": ["PostgreSQL"]},
                 "evidence_chains": [{"conclusion": "c", "evidence_strength": "moderate",
                                      "sources": [tricky]}], "conflicts": [],
                 "knowledge_gaps": [], "final_recommendation": {}, "confidence": "low"}
                ).split("### Strongest Evidence")[-1].split("### Supporting")[0]
print("   listed under Strongest Evidence:",
      ("[" + tricky["title"] + "](" + tricky["url"] + ")") in sec)
print("   chain survives with marker:",
      build_evidence_chain([{**tricky, "total_score": 6.8, "scores": {},
                             "supporting_sources": []}], [])[0]["sources"][0].get("has_body"))
