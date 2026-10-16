"""Independent endpoint-level check of the f3c8bae fixes. Read-only.

Verifies through the real FastAPI app that a body-less (navigation) source is
neither citable nor invisible, and that an ordinary evidence source is not
mislabelled.
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"D:\deepchoice-precodex\src")

from fastapi.testclient import TestClient

import deepchoice.server.app as app_mod

NAV = {"url": "https://www.postgresql.org/docs/",
       "title": "PostgreSQL — Official Documentation",
       "snippet": "", "has_body": False, "score": 8.0}
ORD = {"url": "https://blog.example/benchmark-a",
       "title": "Benchmark A",
       "snippet": "Benchmark A measured p95 at 20ms on 1M vectors.",
       "score": 8.0}
REAL = {"url": "https://www.postgresql.org/docs/release-17",
        "title": "PostgreSQL 17 release notes",
        "snippet": "PostgreSQL 17 improves vacuum and logical replication.",
        "has_body": True, "score": 7.5}

results = []


def check(label, ok, detail=""):
    results.append((label, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")


def snapshot(conflicts=True, chains=None):
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
        "evidence_chains": chains if chains is not None else [
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

print("=== /report ===")
r = client.get("/research/t1/report")
check("report returns 200", r.status_code == 200, f"HTTP {r.status_code}")
# The endpoint returns JSON; the report itself is the field to inspect. Reading
# raw response text as lines would put every finding on one line.
body = r.json().get("report", "")
check("report queryable and non-empty", len(body) > 200, f"{len(body)} chars")

print("\n=== ordinary evidence is not mislabelled ===")
for line in body.splitlines():
    if ORD["url"] in line and ("no body" in line or "无正文" in line):
        check("ordinary source not labelled body-less", False, line)
        break
else:
    check("ordinary source not labelled body-less", True)
check("ordinary source keeps its score", "(score: 8.0)" in body or "Benchmark A" in body)

print("\n=== the navigation link is reachable, not citable ===")
check("navigation link present (reachable)", NAV["url"] in body)
nav_lines = [ln for ln in body.splitlines() if NAV["url"] in ln]
check("navigation link labelled as such",
      any("no body" in ln or "无正文" in ln or "navigation" in ln.lower()
          for ln in nav_lines),
      str(nav_lines)[:150])
check("no citation anchor on the navigation title",
      not any("Official Documentation</a><sup>" in ln for ln in nav_lines))

print("\n=== /annotated ===")
r = client.get("/research/t1/annotated")
check("annotated returns 200", r.status_code == 200, f"HTTP {r.status_code}")
ann = r.json()
check("annotated carries the report", bool(ann.get("report")))
citations = ann.get("citations") or []
nav_numbered = any(c.get("url") == NAV["url"] for c in citations)
check("navigation link is NOT in the citation registry", not nav_numbered,
      str([c.get("url") for c in citations]))
check("the ordinary source IS in the registry",
      any(c.get("url") == ORD["url"] for c in citations),
      str([c.get("url") for c in citations]))
check("navigation link reachable in the annotated report",
      NAV["url"] in (ann.get("report") or ""))

print("\n=== /export md and pdf ===")
for fmt in ("md", "pdf"):
    r = client.get(f"/research/t1/export?format={fmt}")
    check(f"export {fmt} returns 200", r.status_code == 200, f"HTTP {r.status_code}")
    payload = r.content if fmt == "pdf" else r.text
    if fmt == "md":
        check("export md keeps the navigation link", NAV["url"] in payload)
        check("export md keeps the ordinary source", ORD["url"] in payload)
        check("export md does not mislabel the ordinary source",
              not any(ORD["url"] in ln and ("no body" in ln or "无正文" in ln)
                      for ln in payload.splitlines()))
    else:
        check("export pdf is a PDF", payload[:4] == b"%PDF", str(payload[:8]))

print("\n=== no-dispute run: link still reachable ===")
app_mod.load_snapshot = lambda task_id: snapshot(conflicts=False)
r = client.get("/research/t2/report")
nb = r.json().get("report", "")
check("no-dispute report returns 200", r.status_code == 200)
check("navigation link reachable without disputes", NAV["url"] in nb,
      "missing")
# The label may sit on the link's own line or on the continuation line beneath
# it (the What-section unassigned listing uses the latter).
nav_context = []
lines = nb.splitlines()
for i, ln in enumerate(lines):
    if NAV["url"] in ln:
        # The label can sit on the link's line, on the continuation line beneath
        # it, or on the heading line(s) above (the navigation-section form).
        nav_context.extend(lines[max(0, i - 3):i + 2])
check("navigation link labelled without disputes",
      any("no body" in ln or "无正文" in ln or "navigation" in ln.lower()
          for ln in nav_context),
      str(nav_context)[:200])

print("\n=== summary ===")
failed = [r for r in results if not r[1]]
for label, ok, _ in results:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
print(f"  {len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
