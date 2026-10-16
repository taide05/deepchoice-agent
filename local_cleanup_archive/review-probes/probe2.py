"""Adversarial probes for commit 1b4a4cb. Read-only wrt D:\\deepchoice-precodex.

Run with PYTHONPATH=<tree>\\src. No network. Prints [TAG] lines.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys

import numpy as np

import deepchoice
print(f"### module under test: {deepchoice.__file__}")

from deepchoice.agents.conclusion_synthesizer import (
    _bind_citations, _is_real_title, _norm_title, _sanitize_citations, _summarize_chains,
)
from deepchoice.agents.evidence_chain import build_evidence_chain
from deepchoice.agents.source_evaluator import SourceEvaluatorAgent
from deepchoice.formats.citations import inject_citations, number_sources
from deepchoice.formats.comparison_matrix import render as render_cm
from deepchoice.formats.evidence_first import render as render_ef
from deepchoice.formats.what_why_how import render as render_www
from deepchoice.utils.candidate_identity import has_factual_content

NAV = {"url": "https://www.postgresql.org/docs/",
       "title": "PostgreSQL — Official Documentation",
       "snippet": "", "has_body": False, "score": 6.8}
NAV_SNIPPET = {"url": "https://www.postgresql.org/docs/",
               "title": "PostgreSQL — Official Documentation",
               "snippet": "Official documentation site for PostgreSQL",
               "has_body": False, "score": 6.8}
REAL = {"url": "https://www.postgresql.org/docs/release-17",
        "title": "PostgreSQL 17 release notes",
        "snippet": "PostgreSQL 17 improves vacuum and logical replication.",
        "has_body": True, "score": 7.5}
REAL2 = {"url": "https://example.com/bench", "title": "pgvector HNSW benchmark",
         "snippet": "sub-20ms on 1M vectors.", "has_body": True, "score": 7.0}

L = lambda t, s: print(f"[{t}] {s}")


def chains_with(*sources):
    return [{"conclusion": "c", "evidence_strength": "moderate",
             "disputed": False, "sources": list(sources)}]


def state(chains, **kw):
    base = {"task": {"query": "pgvector on RDS", "candidate_techs": ["PostgreSQL"]},
            "evidence_chains": chains, "conflicts": [], "knowledge_gaps": [],
            "final_recommendation": {}, "confidence": "medium"}
    base.update(kw)
    return base


link = lambda s: f"[{s['title']}]({s['url']})"

print("\n===== R1 evidence_first =====")
sec = render_ef(state(chains_with(NAV, REAL))).split("### Strongest Evidence")[-1].split("### Supporting")[0]
L("R1", f"nav linked line in Strongest Evidence: {link(NAV) in sec}")
L("R1", f"real linked line in Strongest Evidence: {link(REAL) in sec}")
sec_only = render_ef(state(chains_with(NAV))).split("### Strongest Evidence")[-1].split("### Supporting")[0]
L("R1", f"nav-only chain states the gap: {'material gap' in sec_only}")
L("R1", f"nav-only chain still shows the link: {link(NAV) in sec_only}")

print("\n===== R2 registry + frontend loop (frontend/app.py:1386-1388) =====")
registry = number_sources(chains_with(NAV, REAL))
L("R2", f"registry urls = {[r['url'] for r in registry]}")
url_to_n = {c["url"]: c["n"] for c in registry}
kept = []
for src in chains_with(NAV, REAL)[0]["sources"]:
    u = str(src.get("url", ""))
    if u not in url_to_n:
        continue
    kept.append(f"[{url_to_n[u]}] {u}")
L("R2", f"frontend card lines kept = {kept}")
L("R2", f"nav numbered = {NAV['url'] in url_to_n}")

print("\n===== R3 synthesis + sanitizer + renderer re-attach =====")
text, mapping = _summarize_chains(chains_with(NAV, REAL), ["PostgreSQL"])
L("R3", f"mapping = {mapping}")
L("R3", f"nav title in mapping: {NAV['title'] in mapping.values()}")
L("R3", f"nav listed as NOT citable in prompt: {'NOT citable' in text}")
san = _sanitize_citations({"recommendation": f"Use it [Source: {NAV['title']}]."},
                          chains_with(NAV, REAL))
L("R3", f"nav citation survives sanitiser: {NAV['title'] in san['recommendation']}")
st_nav = {**state(chains_with(NAV)), "final_recommendation": {
    "recommendation": "x", "ranked_options": [
        {"name": "PostgreSQL", "rank": 1, "rationale": f"Use it [Source: {NAV['title']}]."}]}}
L("R3", f"renderer re-attaches nav as '*Sources:' line: "
        f"{'*Sources: ' + link(NAV) in render_www(st_nav)}")

print("\n===== R4 marker survival =====")


async def _eval():
    return await SourceEvaluatorAgent().run({"search_results": [
        {"source": "official", "results": [dict(NAV)]},
        {"source": "tavily", "results": [dict(REAL)]}]})


ev = asyncio.run(_eval())
by_url = {s["url"]: s for s in ev["source_scores"]}
L("R4", f"evaluator nav has_body={by_url[NAV['url']].get('has_body')!r} score={by_url[NAV['url']]['total_score']}")
L("R4", f"evaluator real has_body={by_url[REAL['url']].get('has_body')!r}")
ch = build_evidence_chain(ev["source_scores"], [])
navc = [c for c in ch if c["sources"][0]["url"] == NAV["url"]][0]
L("R4", f"chain nav has_body={navc['sources'][0].get('has_body')!r} strength={navc['evidence_strength']}")
L("R4", f"report-stage has_factual_content on chain source: {has_factual_content(navc['sources'][0])}")
L("R4", f"chain source without marker still falls back to snippet shape: "
        f"{has_factual_content({'title': 't', 'snippet': ''})}")

print("\n===== R5 unassigned gap note =====")
out_un = render_www({"task": {"query": "pgvector on RDS", "candidate_techs": ["ClickHouse"]},
                     "evidence_chains": chains_with(NAV), "conflicts": [],
                     "knowledge_gaps": [], "final_recommendation": {}, "confidence": "low"})
L("R5", f"gap note present: {'No body collected (navigation link only)' in out_un}")
L("R5", f"link still visible (as [link](url)): {('[link](' + NAV['url'] + ')') in out_un}")

print("\n===== discriminating direction: has_body=False with NON-EMPTY snippet =====")
L("D", f"has_factual_content = {has_factual_content(NAV_SNIPPET)}")
L("D", f"numbered by number_sources: {bool(number_sources(chains_with(NAV_SNIPPET)))}")
_t, m2 = _summarize_chains(chains_with(NAV_SNIPPET), ["PostgreSQL"])
L("D", f"in synthesis mapping: {NAV_SNIPPET['title'] in m2.values()}")
s2 = _sanitize_citations({"recommendation": f"x [Source: {NAV_SNIPPET['title']}]."},
                         chains_with(NAV_SNIPPET))
L("D", f"citation survives sanitiser: {NAV_SNIPPET['title'] in s2['recommendation']}")
L("D", f"listed as Strongest Evidence: "
        f"{link(NAV_SNIPPET) in render_ef(state(chains_with(NAV_SNIPPET))).split('### Strongest Evidence')[-1].split('### Supporting')[0]}")
L("D", f"chain-source marker in report chain: "
        f"{build_evidence_chain([{'url': NAV_SNIPPET['url'], 'title': NAV_SNIPPET['title'], 'snippet': NAV_SNIPPET['snippet'], 'has_body': False, 'total_score': 6.8, 'scores': {}, 'supporting_sources': []}], [])[0]['sources'][0].get('has_body')!r}")

print("\n===== exact-title identity =====")
fuller = "PostgreSQL — Official Documentation and Release Notes"
nav_norm, fuller_norm = _norm_title(NAV["title"]), _norm_title(fuller)
L("E", f"nav_norm ({len(nav_norm)}) is substring of fuller_norm: {nav_norm in fuller_norm}")
L("E", f"_is_real_title(nav_norm, {{fuller_norm}}) = {_is_real_title(nav_norm, {fuller_norm})}")
_fuller_src = {"url": "https://www.postgresql.org/docs/full", "title": fuller,
               "snippet": "body", "has_body": True, "score": 7.0}
_nav_cit = {"recommendation": "x [Source: " + NAV["title"] + "]."}
_kept = _sanitize_citations(dict(_nav_cit), chains_with(_fuller_src))["recommendation"]
L("E", f"sanitizer keeps nav citation when a fuller real title exists: "
       f"{NAV['title'] in _kept}")
# genuine fragment-only citation of a longer real title
long_real = {"url": "https://www.postgresql.org/docs/r17", "has_body": True,
             "title": "PostgreSQL 17 release notes and vacuum improvements",
             "snippet": "body", "score": 7.5}
frag = "PostgreSQL 17 release notes"
L("E", f"fragment {frag!r} norm ({len(_norm_title(frag))}) is substring of long real norm: "
        f"{_norm_title(frag) in _norm_title(long_real['title'])}")
L("E", f"_is_real_title(fragment, {{long_real}}) = {_is_real_title(_norm_title(frag), {_norm_title(long_real['title'])})}")
frag_san = _sanitize_citations({"recommendation": f"Use it [Source: {frag}]."}, chains_with(long_real))
L("E", f"fragment citation kept in report: {'[Source:' in frag_san['recommendation']}")
_exact_kept = _sanitize_citations(
    {"recommendation": "x [Source: " + long_real["title"] + "]."},
    chains_with(long_real))["recommendation"]
L("E", f"exact title kept in report: {'[Source:' in _exact_kept}")
L("E", f"case/punct variant kept: "
        f"{'[Source:' in _sanitize_citations({'recommendation': 'x [Source: postgresql 17 RELEASE-notes!].'}, chains_with(REAL))['recommendation']}")
L("E", f"bound title from mapping round-trips: "
        f"{_bind_citations({'recommendation': 'x [[1]]'}, {1: REAL['title']})['recommendation']!r}")

print("\n===== remaining route: conflict source_a/source_b =====")
import deepchoice.agents.conflict_detector as cd


class _StubModel:
    def encode(self, titles):
        return np.ones((len(titles), 4), dtype=float)


async def _stub_call_model(prompt, **kw):
    return {"resolution": "A_correct", "confidence": "medium",
            "reasoning": "stub", "key_factor": "stub"}


async def drive_conflicts(ev3):
    keep = (cd._scan_pair_contradiction, cd.get_embedding_model, cd.call_model)
    async def fake_scan(a, b, query, usage=None):
        return {"has_difference": True, "type": "winner_disagreement", "explanation": "stub"}
    cd._scan_pair_contradiction = fake_scan
    cd.get_embedding_model = lambda: _StubModel()
    cd.call_model = _stub_call_model
    try:
        agent = cd.ConflictDetectorAgent(gather_evidence=False)
        return await agent.run({"source_scores": ev3["source_scores"],
                                "task": {"query": "pgvector on RDS"}})
    finally:
        cd._scan_pair_contradiction, cd.get_embedding_model, cd.call_model = keep


from deepchoice.agents.source_evaluator import SourceEvaluatorAgent as _SE
ev3 = asyncio.run(_SE().run({"search_results": [
    {"source": "official", "results": [dict(NAV)]},
    {"source": "tavily", "results": [dict(REAL2)]}]}))
conf_out = asyncio.run(drive_conflicts(ev3))
L("C", f"evaluator scores injected: "
       f"{[(s['title'][:28], s['total_score'], s.get('has_body')) for s in ev3['source_scores']]}")
conflicts = conf_out["conflicts"]
L("C", f"conflicts produced = {len(conflicts)}")
if conflicts:
    c0 = conflicts[0]
    L("C", f"source_a = {json.dumps(c0['source_a'], ensure_ascii=False)}")
    L("C", f"source_a carries has_body: {'has_body' in c0['source_a']}")
    st_c = state(chains_with(NAV, REAL2), conflicts=conflicts)
    for nm, rend in (("evidence_first", render_ef), ("what_why_how", render_www),
                     ("comparison_matrix", render_cm)):
        hits = [ln.strip() for ln in rend(st_c).splitlines() if NAV["url"] in ln]
        L("C", f"{nm} lines carrying the body-less URL: {hits}")
    reg_c = number_sources(st_c["evidence_chains"])
    L("C", f"registry excludes it: {NAV['url'] not in {r['url'] for r in reg_c}}")
    marked = inject_citations(render_www(st_c), reg_c)
    L("C", f"no citation anchor lands on it: "
           f"{not re.search(re.escape(NAV['url']) + r'[^\n]*class=\"cite\"', marked)}")
    # deterministic variant (score gap >= 2.5) - no LLM at all
    scores = [dict(s) for s in ev3["source_scores"]]
    nav_s = [s for s in scores if s["url"] == NAV["url"]][0]
    real_s = [s for s in scores if s["url"] == REAL2["url"]][0]
    nav_s["total_score"], real_s["total_score"] = 9.0, 6.0
    keep = (cd._scan_pair_contradiction, cd.get_embedding_model)
    async def fake_scan2(a, b, query, usage=None):
        return {"has_difference": True, "type": "x", "explanation": "y"}
    cd._scan_pair_contradiction = fake_scan2
    cd.get_embedding_model = lambda: _StubModel()
    try:
        det = asyncio.run(cd.ConflictDetectorAgent(gather_evidence=False).run(
            {"source_scores": scores, "task": {"query": "q"}}))
    finally:
        cd._scan_pair_contradiction, cd.get_embedding_model = keep
    L("C", f"deterministic-rule conflicts = {len(det['conflicts'])}; "
           f"source_a url = {det['conflicts'][0]['source_a']['url'] if det['conflicts'] else None}")

print("\n===== link visibility (exact linked line) =====")
cases = [
    ("evidence_first nav-only", render_ef, state(chains_with(NAV))),
    ("evidence_first nav+real", render_ef, state(chains_with(NAV, REAL))),
    ("what_why_how nav-only candidate=PostgreSQL", render_www, state(chains_with(NAV))),
    ("what_why_how nav-only candidate=ClickHouse", render_www,
     {"task": {"query": "q", "candidate_techs": ["ClickHouse"]}, "evidence_chains": chains_with(NAV),
      "conflicts": [], "knowledge_gaps": [], "final_recommendation": {}, "confidence": "low"}),
    ("what_why_how nav-only no candidates", render_www,
     {"task": {"query": "q", "candidate_techs": []}, "evidence_chains": chains_with(NAV),
      "conflicts": [], "knowledge_gaps": [], "final_recommendation": {}, "confidence": "low"}),
    ("comparison_matrix nav+real", render_cm, state(chains_with(NAV, REAL))),
]
for nm, rend, st in cases:
    body = rend(st)
    L("V", f"{nm}: exact nav link in report = {link(NAV) in body}")

print("\n===== candidate-basis route =====")
what = render_www(state(chains_with(NAV))).split("## Why")[0]
L("B", f"nav listed under '### PostgreSQL' as basis: {link(NAV) in what}")
L("B", f"explicit NO CONTENT line: {'NO CONTENT RETRIEVED' in what}")
L("B", f"'no retrieved material' gap message shown: {'No retrieved material explicitly covered' in what}")
L("B", f"score shown next to it: {'(score: 6.8)' in what}")
print("\nDONE")
