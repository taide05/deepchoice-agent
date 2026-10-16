"""End-to-end: does a body-less source still reach a finished report through the API?

Read-only; drives the real FastAPI app with an in-memory snapshot.
"""
import json

from fastapi.testclient import TestClient

import deepchoice.server.app as app_module
from deepchoice.agents.conclusion_synthesizer import _bind_citations, _sanitize_citations
from deepchoice.formats.what_why_how import render as render_www
from deepchoice.formats.evidence_first import render as render_ef
from deepchoice.utils.candidate_identity import has_factual_content

BODYLESS = {"title": "PostgreSQL — Official Documentation",
            "url": "https://www.postgresql.org/docs/",
            "snippet": "", "has_body": False, "score": 8.0}
REAL = {"title": "PostgreSQL — Official Documentation and Release Notes",
        "url": "https://www.postgresql.org/docs/release-17",
        "snippet": "Release 17 adds incremental sort and improves vacuum.", "score": 7.5}

print("has_factual_content(bodyless) =", has_factual_content(BODYLESS),
      "| has_factual_content(real) =", has_factual_content(REAL))

CHAIN = {"conclusion": "PostgreSQL is the base for pgvector", "evidence_strength": "strong",
         "disputed": False, "sources": [BODYLESS, REAL]}
CHAINS = [CHAIN]

# --- the live synthesis sequence: sanitize -> bind -> render -----------------
model_out = {
    "recommendation": "Adopt pgvector on RDS [Source: PostgreSQL — Official Documentation].",
    "ranked_options": [
        {"rank": 1, "name": "pgvector",
         "rationale": "Managed Postgres keeps ops low [Source: PostgreSQL — Official Documentation]."},
    ],
    "trade_offs": [
        {"dimension": "Ops", "finding": "One system, fewer moving parts "
                                        "[Source: PostgreSQL — Official Documentation]."},
    ],
}
res = _sanitize_citations(dict(model_out), CHAINS)
res = _bind_citations(res, {1: REAL["title"]})
print("\n--- after _sanitize_citations + _bind_citations ---")
print("recommendation:", res["recommendation"])
print("rationale     :", res["ranked_options"][0]["rationale"])
print("finding       :", res["trade_offs"][0]["finding"])

state = {"task": {"query": "pgvector on Amazon RDS for PostgreSQL vs Pinecone",
                  "candidate_techs": ["pgvector on Amazon RDS for PostgreSQL", "Pinecone"]},
         "evidence_chains": CHAINS, "conflicts": [], "knowledge_gaps": [],
         "final_recommendation": res, "confidence": "medium",
         "conflict_check": {"pairs_scanned": 1, "scan_outcomes": {"unscanned": 0}}}

md = render_www(state)
print("\n--- what_why_how: lines mentioning the body-less URL ---")
hits = [l for l in md.splitlines() if BODYLESS["url"] in l]
print("\n".join(hits) if hits else "  (none)")

md2 = render_ef(state)
print("--- evidence_first: lines mentioning the body-less URL ---")
hits2 = [l for l in md2.splitlines() if BODYLESS["url"] in l]
print("\n".join(hits2) if hits2 else "  (none)")

# --- through the real API --------------------------------------------------
SNAP = {"task": {"query": state["task"]["query"], "report_format": "what_why_how",
                 "candidate_techs": state["task"]["candidate_techs"]},
        "evidence_chains": CHAINS, "conflicts": [], "knowledge_gaps": [],
        "final_recommendation": res, "confidence": "medium",
        "conflict_check": state["conflict_check"]}
app_module.load_snapshot = lambda _tid: dict(SNAP)
client = TestClient(app_module.app)

ann = client.get("/research/t1/annotated", params={"format": "what_why_how"})
data = ann.json()
print("\n--- GET /annotated ---")
print("citations registry:", data["citations"])
print("body-less URL in report:", BODYLESS["url"] in data["report"])
print("numbered badge next to it:",
      f'[{data["citations"][0]["n"]}]' if data["citations"] else "no citations at all")

exp = client.get("/research/t1/export", params={"format": "pdf", "report_format": "what_why_how"})
print("\n--- GET /export?format=pdf ---")
print("status:", exp.status_code, "content-type:", exp.headers.get("content-type"))
if exp.status_code == 200:
    import re
    print("pdf bytes:", len(exp.content))
    # crude: look for the URL in any uncompressed stream text
    print("body-less URL present in pdf bytes:",
          BODYLESS["url"].encode() in exp.content)

mdx = client.get("/research/t1/export", params={"format": "md"})
print("\n--- GET /export?format=md ---")
print("body-less URL in md export:", BODYLESS["url"] in mdx.text)
print("lines:")
for l in mdx.text.splitlines():
    if BODYLESS["url"] in l:
        print("   ", l)
