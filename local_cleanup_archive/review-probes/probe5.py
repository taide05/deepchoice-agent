import re
from deepchoice.formats.citations import number_sources, inject_citations, build_toc
from deepchoice.formats.what_why_how import render
NAV = {"url": "https://www.postgresql.org/docs/", "title": "PostgreSQL - Official Documentation",
       "snippet": "", "has_body": False, "score": 6.8}
REAL = {"url": "https://example.com/bench", "title": "pgvector HNSW benchmark",
        "snippet": "body", "has_body": True, "score": 7.5}
chains = [{"conclusion": "c", "evidence_strength": "moderate", "disputed": False,
           "sources": [NAV, REAL]}]
st = {"task": {"query": "q", "candidate_techs": ["PostgreSQL"]}, "evidence_chains": chains,
      "conflicts": [], "knowledge_gaps": [], "final_recommendation": {}, "confidence": "low"}
reg = number_sources(chains)
ann = inject_citations(render(st), reg)
_toc, ann = build_toc(ann)
print("registry:", [r["url"] for r in reg])
print("nav link still a plain markdown link in annotated HTML:", f"[link]({NAV['url']})" in ann)
print("nav link got a citation anchor:", bool(re.search(re.escape(NAV["url"]) + r"[^\n]*class=\"cite\"", ann)))
print("real link got a citation anchor:", bool(re.search(re.escape(REAL["url"]) + r"[^\n]*class=\"cite\"", ann)))
