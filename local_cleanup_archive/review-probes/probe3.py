"""Visibility probes: is the body-less link still reachable in each report?"""
from __future__ import annotations

import deepchoice
print("### module:", deepchoice.__file__)

from deepchoice.formats.comparison_matrix import render as render_cm
from deepchoice.formats.evidence_first import render as render_ef
from deepchoice.formats.what_why_how import render as render_www

NAV = {"url": "https://www.postgresql.org/docs/",
       "title": "PostgreSQL — Official Documentation",
       "snippet": "", "has_body": False, "score": 6.8}
REAL = {"url": "https://www.postgresql.org/docs/release-17",
        "title": "PostgreSQL 17 release notes",
        "snippet": "vacuum improvements", "has_body": True, "score": 7.5}


def ch(*s):
    return [{"conclusion": "c", "evidence_strength": "moderate", "disputed": False,
             "sources": list(s)}]


def st(chains, cands=("PostgreSQL",)):
    return {"task": {"query": "pgvector on RDS", "candidate_techs": list(cands)},
            "evidence_chains": chains, "conflicts": [], "knowledge_gaps": [],
            "final_recommendation": {}, "confidence": "medium"}


TARGET = f"]({NAV['url']})"
cases = [
    ("evidence_first nav-only", render_ef, st(ch(NAV))),
    ("evidence_first nav+real", render_ef, st(ch(NAV, REAL))),
    ("what_why_how nav-only cand=[PostgreSQL]", render_www, st(ch(NAV))),
    ("what_why_how nav-only cand=[ClickHouse]", render_www, st(ch(NAV), ["ClickHouse"])),
    ("what_why_how nav-only cand=[]", render_www, st(ch(NAV), [])),
    ("comparison_matrix nav+real", render_cm, st(ch(NAV, REAL))),
]
for nm, rend, s in cases:
    body = rend(s)
    print(f"[V] {nm}: body-less URL appears as a link target = {TARGET in body}")

what = render_www(st(ch(NAV))).split("## Why")[0]
print(f"[B] nav listed as the candidate's basis line = "
      f"{('- ' + NAV['title'] + ' — [link](' + NAV['url'] + ')') in what}")
print(f"[B] NO CONTENT line present = {'NO CONTENT RETRIEVED' in what}")
print(f"[B] 'no retrieved material' gap suppressed = "
      f"{'No retrieved material explicitly covered' not in what}")
