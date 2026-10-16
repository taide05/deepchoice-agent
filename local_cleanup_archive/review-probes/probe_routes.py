"""Adversarial probes for commit 1b4a4cb (precodex review workspace).

Read-only wrt D:\\deepchoice-precodex. Run with PYTHONPATH=<tree>\\src.
Prints structured PASS/FAIL/OPEN lines. No network, no LLM calls.
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
    _bind_citations,
    _is_real_title,
    _norm_title,
    _sanitize_citations,
    _summarize_chains,
)
from deepchoice.agents.evidence_chain import build_evidence_chain
from deepchoice.agents.source_evaluator import SourceEvaluatorAgent
from deepchoice.formats.citations import inject_citations, number_sources
from deepchoice.formats.comparison_matrix import render as render_cm
from deepchoice.formats.evidence_first import render as render_ef
from deepchoice.formats.what_why_how import render as render_www
from deepchoice.utils.candidate_identity import has_factual_content

OUT: list[str] = []


def line(tag: str, text: str) -> None:
    OUT.append(f"[{tag}] {text}")


NAV = {"url": "https://www.postgresql.org/docs/",
       "title": "PostgreSQL — Official Documentation",
       "snippet": "", "has_body": False, "score": 6.75}
NAV_SNIPPET = {"url": "https://www.postgresql.org/docs/",
               "title": "PostgreSQL — Official Documentation",
               "snippet": "Official documentation site for PostgreSQL",
               "has_body": False, "score": 6.75}
REAL = {"url": "https://www.postgresql.org/docs/release-17",
        "title": "PostgreSQL 17 release notes",
        "snippet": "PostgreSQL 17 improves vacuum and logical replication.",
        "has_body": True, "score": 7.5}
REAL2 = {"url": "https://example.com/bench",
         "title": "pgvector HNSW benchmark",
         "snippet": "sub-20ms on 1M vectors.", "has_body": True, "score": 7.0}


def chains_with(*sources):
    return [{"conclusion": "c", "evidence_strength": "moderate",
             "disputed": False, "sources": list(sources)}]


def state(chains, **kw):
    base = {"task": {"query": "pgvector on RDS", "candidate_techs": ["PostgreSQL"]},
            "evidence_chains": chains, "conflicts": [], "knowledge_gaps": [],
            "final_recommendation": {}, "confidence": "medium"}
    base.update(kw)
    return base


# ---------------------------------------------------------------- item 1: R1
print("\n================ ITEM 1: route closure ================")
report_ef = render_ef(state(chains_with(NAV, REAL)))
sec = report_ef.split("### Strongest Evidence")[-1].split("### Supporting")[0]
line("R1", f"evidence_first strongest-evidence nav line present: "
           f"{f'[{NAV[chr(39)+chr(39)]}' if False else ('[' + NAV['title'] + '](' + NAV['url'] + ')') in sec}")
line("R1", f"nav URL anywhere in evidence_first report: {NAV['url'] in report_ef}")
line("R1", f"real source still listed: {REAL['url'] in sec}")

# ---------------------------------------------------------------- R2 (registry + frontend loop)
registry = number_sources(chains_with(NAV, REAL))
line("R2", f"number_sources urls = {[r['url'] for r in registry]}")
url_to_n = {c["url"]: c["n"] for c in registry}
kept = []
for src in chains_with(NAV, REAL)[0]["sources"]:
    u = str(src.get("url", ""))
    if u not in url_to_n:          # exact HEAD frontend/app.py:1386-1388
        continue
    kept.append((url_to_n[u], u))
line("R2", f"frontend evidence-card url_to_n loop keeps = {kept}")
line("R2", f"nav url numbered by frontend: {NAV['url'] in url_to_n}")

# ---------------------------------------------------------------- R3
text, mapping = _summarize_chains(chains_with(NAV, REAL), ["PostgreSQL"])
line("R3", f"synthesis mapping = {mapping}")
line("R3", f"nav title in mapping: {NAV['title'] in mapping.values()}")
nav_title = NAV["title"]
san = _sanitize_citations({"recommendation": f"Use it [Source: {nav_title}]."},
                          chains_with(NAV, REAL))
line("R3", f"_sanitize_citations kept nav citation: {nav_title in san['recommendation']}")
line("R3", f"_is_real_title exact on real title: {_is_real_title(_norm_title(REAL['title']), {_norm_title(REAL['title'])})}")

# ---------------------------------------------------------------- R5
st_un = {"task": {"query": "pgvector on RDS", "candidate_techs": ["ClickHouse"]},
         "evidence_chains": chains_with(NAV), "conflicts": [], "knowledge_gaps": [],
         "final_recommendation": {}, "confidence": "low"}
out_un = render_www(st_un)
line("R5", f"unassigned nav gap note present: "
           f"{'No body collected (navigation link only)' in out_un}")
line("R5", f"unassigned nav link still visible: {NAV['url'] in out_un}")

# ---------------------------------------------------------------- item 2: marker survives
print("\n================ ITEM 2: marker survival ================")


async def drive_evaluator():
    agent = SourceEvaluatorAgent()
    return await agent.run({"search_results": [
        {"source": "official", "results": [dict(NAV)]},
        {"source": "tavily", "results": [dict(REAL)]},
    ]})


ev = asyncio.run(drive_evaluator())
by_url = {s["url"]: s for s in ev["source_scores"]}
line("EVAL", f"source_scores nav has_body = {by_url[NAV['url']].get('has_body')!r} "
             f"total_score={by_url[NAV['url']]['total_score']}")
line("EVAL", f"source_scores real has_body = {by_url[REAL['url']].get('has_body')!r}")

ev2 = asyncio.run(drive_evaluator())
# feed the real evaluator output into the real chain builder
chains = build_evidence_chain(ev2["source_scores"], [])
nav_chain = [c for c in chains if c["sources"][0]["url"] == NAV["url"]]
line("CHAIN", f"chain for nav: strength={nav_chain[0]['evidence_strength']} "
              f"has_body={nav_chain[0]['sources'][0].get('has_body')!r}")
line("CHAIN", f"chain count={len(chains)}")
rep_chain = chains
line("CHAIN", f"nav chain strength is 'moderate' -> reaches report as evidence-strength material: "
              f"{nav_chain[0]['evidence_strength'] == 'moderate'}")

# non-empty snippet + has_body False
line("DISCRIM", f"NAV_SNIPPET has_factual_content = {has_factual_content(NAV_SNIPPET)}")
line("DISCRIM", f"NAV_SNIPPET numbered by number_sources: "
                f"{bool(number_sources(chains_with(NAV_SNIPPET)))}")
t2, m2 = _summarize_chains(chains_with(NAV_SNIPPET), ["PostgreSQL"])
line("DISCRIM", f"NAV_SNIPPET in synthesis mapping: {NAV_SNIPPET['title'] in m2.values()}")
s2 = _sanitize_citations({"recommendation": f"x [Source: {NAV_SNIPPET['title']}]."},
                         chains_with(NAV_SNIPPET))
line("DISCRIM", f"NAV_SNIPPET citation survives sanitiser: {NAV_SNIPPET['title'] in s2['recommendation']}")
line("DISCRIM", f"NAV_SNIPPET in what_why_how chain_sources-derived Sources line: "
                f"{'*Sources: [' + NAV_SNIPPET['title'] + ']' in render_www(state(chains_with(NAV_SNIPPET)))}")
line("DISCRIM", f"NAV_SNIPPET listed under Strongest Evidence: "
                f"{'[' + NAV_SNIPPET['title'] + '](' + NAV_SNIPPET['url'] + ')' in render_ef(state(chains_with(NAV_SNIPPET))).split('### Strongest Evidence')[-1].split('### Supporting')[0]}")

# ---------------------------------------------------------------- item 3: exact-title identity
print("\n================ ITEM 3: exact-title citation identity ================")
fuller = {"url": "https://www.postgresql.org/docs/full", "has_body": True,
          "title": "PostgreSQL — Official Documentation and Release Notes",
          "snippet": "body", "score": 7.0}
line("EXACT", f"nav title IS a normalised substring of the fuller real title: "
              f"{_norm_title(NAV['title']) in _norm_title(fuller['title'])} "
              f"(len={len(_norm_title(NAV['title']))})")
line("EXACT", f"_is_real_title(nav_norm, {{fuller_norm}}) = "
              f"{_is_real_title(_norm_title(NAV['title']), {_norm_title(fuller['title'])})}  "
              f"(False on HEAD, True on 24e4b75)")
frag = "PostgreSQL 17 release notes"
line("EXACT", f"fragment-only citation {frag!r} vs real {fuller['title']!r}: "
              f"_is_real_title={_is_real_title(_norm_title(frag), {_norm_title(REAL['title'])})}")
line("EXACT", f"fragment vs real {REAL['title']!r}: "
              f"_is_real_title={_is_real_title(_norm_title(frag), {_norm_title(REAL['title'])})}")
frag_report = _sanitize_citations(
    {"recommendation": f"Use it [Source: PostgreSQL 17 release notes]."},
    chains_with(REAL))
line("EXACT", f"fragment citation accepted into report on HEAD: "
              f"{'[Source:' in frag_report['recommendation']}")
# normalisation tolerance preserved
line("EXACT", f"case/punct variant still accepted: "
              f"{_is_real_title(_norm_title('postgresql 17 RELEASE-notes!'), {_norm_title(REAL['title'])})}")
line("EXACT", f"bound title round-trips exactly: "
              f"{_bind_citations({'recommendation': 'x [[1]]'}, {1: REAL['title']})['recommendation']}")

# ---------------------------------------------------------------- item 1 cont: conflict route
print("\n================ ITEM 1 cont: conflict 'source' route ================")

import deepchoice.agents.conflict_detector as cd


class _StubModel:
    def encode(self, titles):
        # identical directions -> cosine 1.0, so every pair clears the 0.65 gate
        return np.ones((len(titles), 4), dtype=float)


async def _fake_scan(a, b, query, usage=None):
    return {"has_difference": True, "type": "winner_disagreement",
            "explanation": "stub: differs"}


async def drive_conflicts():
    saved_scan = cd._scan_pair_contradiction
    saved_model = cd.get_embedding_model
    cd._scan_pair_contradiction = _fake_scan
    cd.get_embedding_model = lambda: _StubModel()
    try:
        scores = [
            {"url": NAV["url"], "title": NAV["title"], "snippet": "",
             "has_body": False, "total_score": 6.75, "scores": {"authority": 10},
             "supporting_sources": [], "evidence_type": "citation"},
            {"url": REAL2["url"], "title": REAL2["title"],
             "snippet": REAL2["snippet"], "has_body": True, "total_score": 6.0,
             "scores": {"authority": 7}, "supporting_sources": [],
             "evidence_type": "benchmark"},
        ]
        agent = cd.ConflictDetectorAgent(gather_evidence=False)
        return await agent.run({"source_scores": scores,
                                "task": {"query": "pgvector on RDS"}})
    finally:
        cd._scan_pair_contradiction = saved_scan
        cd.get_embedding_model = saved_model


conf_out = asyncio.run(drive_conflicts())
conflicts = conf_out["conflicts"]
line("CONFLICT", f"conflicts produced = {len(conflicts)}")
if conflicts:
    c0 = conflicts[0]
    line("CONFLICT", f"source_a = {json.dumps(c0['source_a'])}")
    line("CONFLICT", f"has_body present on source_a: {'has_body' in c0['source_a']}")
    line("CONFLICT", f"claim_a = {c0['claim_a']!r}  resolution={c0['resolution']}")
    st_c = state(chains_with(NAV, REAL2), conflicts=conflicts)
    for name, rend in (("evidence_first", render_ef), ("what_why_how", render_www),
                       ("comparison_matrix", render_cm)):
        body = rend(st_c)
        mine = [ln for ln in body.splitlines() if NAV["url"] in ln]
        line("CONFLICT", f"{name}: body-less URL rendered on lines -> {mine}")
    # numbered?
    reg_c = number_sources(st_c["evidence_chains"])
    line("CONFLICT", f"registry for conflict state = {[r['url'] for r in reg_c]}")
    marked = inject_citations(render_www(st_c), reg_c)
    line("CONFLICT", f"what_why_how: nav URL receives a citation anchor: "
                     f"{bool(re.search(re.escape(NAV['url']) + r'[^\n]*class=.cite.', marked))}")
else:
    line("CONFLICT", "no conflict row produced - route not exercised")

# ---------------------------------------------------------------- item 1 cont: visibility
print("\n================ ITEM 1 cont: link visibility ================")
for name, rend, st in (
    ("evidence_first (nav-only chain)", render_ef, state(chains_with(NAV))),
    ("evidence_first (nav+real)", render_ef, state(chains_with(NAV, REAL))),
    ("what_why_how (nav-only, candidate matches)", render_www, state(chains_with(NAV))),
    ("what_why_how (no candidate_techs)",
     render_www, {"task": {"query": "q", "candidate_techs": []},
                  "evidence_chains": chains_with(NAV), "conflicts": [],
                  "knowledge_gaps": [], "final_recommendation": {}, "confidence": "low"}),
    ("comparison_matrix (nav+real)", render_cm, state(chains_with(NAV, REAL))),
):
    body = rend(st)
    line("VISIBLE", f"{name}: nav URL present in report = {NAV['url'] in body}")

print("\n================ candidate-basis route ================")
st_basis = state(chains_with(NAV))
out_basis = render_www(st_basis)
what = out_basis.split("## Why")[0]
line("BASIS", f"nav listed as the candidate's basis (under '### PostgreSQL'): "
              f"{NAV['url'] in what}")
line("BASIS", f"explicit NO CONTENT line follows: {'NO CONTENT RETRIEVED' in what}")
line("BASIS", f"candidate stated as having no material: "
              f"{'No retrieved material explicitly covered' in what}")

print("\n".join(OUT))
