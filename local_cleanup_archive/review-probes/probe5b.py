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
print("citation anchors injected:", ann.count('class="cite"'))
print("nav kept as plain markdown link:", f"[link]({NAV['url']})" in ann)
print("numbered target is only the real url:", [r["url"] for r in reg])
