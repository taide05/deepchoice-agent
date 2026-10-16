"""Item 5 (independent re-run of the endpoint-level properties) on 66db028.

Checks through the real FastAPI app: a body-less source is not in the citation
registry, carries no citation anchor and is labelled; a fact-bearing source keeps
its score and is not labelled body-less. /report, /annotated, /export md, pdf.
"""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"D:\deepchoice-precodex\src")

from fastapi.testclient import TestClient
import deepchoice.server.app as app_mod

NAV = {"url": "https://www.postgresql.org/docs/",
       "title": "PostgreSQL — Official Documentation",
       "snippet": "", "has_body": False, "score": 8.0}
ORD = {"url": "https://blog.example/benchmark-a", "title": "Benchmark A",
       "snippet": "Benchmark A measured p95 at 20ms on 1M vectors.", "score": 8.0}

results = []


def check(label, ok, detail=""):
    results.append((label, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' -- ' + str(detail)) if detail else ''}")


def snapshot(conflicts=True):
    return {
        "task": {"query": "pgvector on RDS vs Pinecone",
                 "candidate_techs": ["pgvector on Amazon RDS for PostgreSQL", "Pinecone"],
                 "scene_context": "small team", "report_format": "what_why_how",
                 "language": "zh"},
        "sub_questions": ["q1"], "adapted_queries": {},
        "search_results": [{"source": "tavily", "status": "success",
                            "results": [ORD, NAV], "error": None}],
        "source_scores": [
            {**NAV, "source_type": "official_doc", "evidence_type": "citation",
             "scores": {"authority": 10, "timeliness": 0, "consistency": 4,
                        "verifiability": 6}, "total_score": 8.0, "rank": 1},
            {**ORD, "source_type": "tech_blog", "evidence_type": "benchmark",
             "scores": {"authority": 7, "timeliness": 0, "consistency": 4,
                        "verifiability": 8}, "total_score": 8.0, "rank": 2},
        ],
        "evidence_chains": [
            {"conclusion": "Benchmark A", "evidence_strength": "moderate",
             "disputed": False, "sources": [ORD]},
            {"conclusion": "PostgreSQL — Official Documentation",
             "evidence_strength": "moderate", "disputed": False, "sources": [NAV]},
        ],
        "conflicts": [{
            "resolution": "a", "claim_a": "Benchmark A",
            "claim_b": "PostgreSQL — Official Documentation",
            "source_a": {"url": ORD["url"], "score": 8.0, "snippet": ORD["snippet"]},
            "source_b": {"url": NAV["url"], "score": 8.0, "has_body": False},
            "reasoning": "r", "key_factor": "k", "confidence": "low",
        }] if conflicts else [],
        "final_recommendation": {
            "winner": "pgvector on Amazon RDS for PostgreSQL",
            "confidence": "medium",
            "recommendation": "Use pgvector on RDS [Source: Benchmark A].",
            "ranked_options": [{"rank": 1, "name": "pgvector on Amazon RDS for PostgreSQL",
                                "rationale": "Measured at scale [Source: Benchmark A]."}],
            "trade_offs": [{"dimension": "ops", "finding": "Cheaper [Source: Benchmark A]."}],
        },
        "confidence": "medium", "knowledge_gaps": [], "partial_failures": [],
        "quality_signals": [], "current_phase": "report_generator",
        "agent_timing": {"report_generator": 1.0}, "token_usage": [],
    }


client = TestClient(app_mod.app)
app_mod.load_snapshot = lambda task_id: snapshot()

print("=== /report (JSON report field) ===")
r = client.get("/research/t1/report")
check("report returns 200", r.status_code == 200, f"HTTP {r.status_code}")
body = r.json().get("report", "")
check("report non-empty", len(body) > 200, f"{len(body)} chars")
nav_lines = [ln for ln in body.splitlines() if NAV["url"] in ln]
ord_lines = [ln for ln in body.splitlines() if ORD["url"] in ln]
print("  NAV lines:", nav_lines)
print("  ORD lines:", ord_lines)
check("navigation link reachable in /report", NAV["url"] in body)
check("navigation link labelled body-less/navigation",
      any(("no body" in ln or "无正文" in ln or "navigation" in ln.lower()) for ln in nav_lines),
      nav_lines)
check("ordinary source reachable", ORD["url"] in body)
check("ordinary source is NOT labelled body-less",
      not any(("no body" in ln or "无正文" in ln or "navigation" in ln.lower()) for ln in ord_lines),
      ord_lines)
check("ordinary source keeps its score somewhere in the report",
      "(score: 8.0)" in body,
      [ln for ln in body.splitlines() if "score" in ln][:4])

print("\n=== /annotated ===")
r = client.get("/research/t1/annotated")
check("annotated 200", r.status_code == 200, f"HTTP {r.status_code}")
ann = r.json()
cits = ann.get("citations") or []
check("body-less source NOT in the citation registry",
      not any(c.get("url") == NAV["url"] for c in cits), [c.get("url") for c in cits])
check("fact-bearing source IS in the registry",
      any(c.get("url") == ORD["url"] for c in cits), [c.get("url") for c in cits])
check("navigation link reachable in annotated report", NAV["url"] in (ann.get("report") or ""))
check("no citation anchor on the navigation title",
      not any("Official Documentation</a><sup>" in ln for ln in (ann.get("report") or "").splitlines()))

print("\n=== /export?format=md ===")
r = client.get("/research/t1/export?format=md")
check("export md 200", r.status_code == 200, f"HTTP {r.status_code}")
md = r.text
check("export md keeps the navigation link", NAV["url"] in md)
check("export md keeps the ordinary source", ORD["url"] in md)
check("export md does not mislabel the ordinary source",
      not any(ORD["url"] in ln and ("no body" in ln or "无正文" in ln or "navigation" in ln.lower())
              for ln in md.splitlines()),
      [ln for ln in md.splitlines() if ORD["url"] in ln])

print("\n=== /export?format=pdf ===")
r = client.get("/research/t1/export?format=pdf")
check("export pdf 200", r.status_code == 200, f"HTTP {r.status_code}")
check("export pdf is a PDF", r.content[:4] == b"%PDF", r.content[:8])

print("\n=== no-dispute run ===")
app_mod.load_snapshot = lambda task_id: snapshot(conflicts=False)
nb = client.get("/research/t2/report").json().get("report", "")
check("navigation link reachable without disputes", NAV["url"] in nb)
ctx = []
lines = nb.splitlines()
for i, ln in enumerate(lines):
    if NAV["url"] in ln:
        ctx.extend(lines[max(0, i - 3):i + 2])
check("navigation link labelled without disputes",
      any(("no body" in ln or "无正文" in ln or "navigation" in ln.lower()) for ln in ctx), ctx[:5])

print("\n=== summary ===")
failed = [x for x in results if not x[1]]
print(f"  {len(results) - len(failed)}/{len(results)} checks passed")
for label, ok, detail in failed:
    print(f"  FAILED: {label} -- {detail}")
sys.exit(1 if failed else 0)
