"""Replicate frontend/app.py:1373-1389 verbatim against the live /annotated payload."""
from fastapi.testclient import TestClient

import deepchoice.server.app as app_module

BODYLESS = {"title": "PostgreSQL — Official Documentation",
            "url": "https://www.postgresql.org/docs/",
            "snippet": "", "has_body": False, "score": 8.0}
REAL = {"title": "PostgreSQL 17 release notes",
        "url": "https://www.postgresql.org/docs/release-17",
        "snippet": "Incremental sort and vacuum improvements.", "score": 7.5}
SNAP = {
    "task": {"query": "pgvector on Amazon RDS for PostgreSQL vs Pinecone",
             "report_format": "what_why_how",
             "candidate_techs": ["pgvector on Amazon RDS for PostgreSQL", "Pinecone"]},
    "evidence_chains": [
        {"conclusion": "PostgreSQL is the managed base", "evidence_strength": "strong",
         "disputed": False, "sources": [BODYLESS, REAL]},
    ],
    "conflicts": [], "knowledge_gaps": [], "confidence": "medium",
    "final_recommendation": {"winner": "pgvector", "recommendation": "Use pgvector.",
                             "ranked_options": [], "trade_offs": []},
    "conflict_check": {"pairs_scanned": 1, "scan_outcomes": {"unscanned": 0}},
}
app_module.load_snapshot = lambda _t: dict(SNAP)
client = TestClient(app_module.app)
data = client.get("/research/t1/annotated", params={"format": "what_why_how"}).json()

citations = data["citations"]
chains = SNAP["evidence_chains"]
print("registry (numbered sources):", citations)
print()
# --- verbatim frontend/app.py:1373-1389 ---
url_to_n = {c["url"]: c["n"] for c in citations}
for cit in citations:
    chain = chains[cit["chain_idx"]] if cit["chain_idx"] < len(chains) else {}
    src_parts = []
    for src in chain.get("sources", []):
        url = str(src.get("url", ""))
        n = url_to_n.get(url, cit["n"])
        title = src.get("title", "")
        src_parts.append(f'[{n}] {title} (score: {src.get("score", "")})')
    print(f'evidence card id="ev-{cit["n"]}" shows:')
    for p in src_parts:
        print("   ", p)
print()
print("body-less URL displayed inside the evidence card:",
      any(BODYLESS["url"] and BODYLESS["title"] in p for p in src_parts))
