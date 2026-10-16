"""Adversarial route enumeration: can a body-less source still be presented as evidence?

Read-only: imports the package under review, renders reports in memory, prints findings.
"""
import asyncio
import json
import re
import sys

from deepchoice.formats.what_why_how import render as render_www
from deepchoice.formats.evidence_first import render as render_ef
from deepchoice.formats.comparison_matrix import render as render_cm
from deepchoice.formats.citations import number_sources, inject_citations
from deepchoice.retrievers.official import OfficialSearch
from deepchoice.utils.candidate_identity import has_factual_content

REAL = r"D:\deepchoice-precodex\outputs\e3b1c837-d2e1-46a1-b77c-c46eefe41dea\research_snapshot.json"


async def live_official_entry():
    """One entry in the exact shape official.py emits for a body-less mapping link."""
    search = OfficialSearch()
    out = await search._do_search("pgvector on RDS", [], 10, [], ["PostgreSQL"])
    return out


def show(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


async def main():
    entries = await live_official_entry()
    print("live official entries:")
    for e in entries:
        print("   ", e, "-> has_factual_content =", has_factual_content(e))
    nav = entries[0]

    # ---- Route 1: numbered [[N]] synthesizer path -------------------------
    show("ROUTE 1: _summarize_chains numbered [[N]] mapping")
    from deepchoice.agents.conclusion_synthesizer import _summarize_chains, _bind_citations, _sanitize_citations
    chain = {"conclusion": "PostgreSQL is the managed-Postgres base", "evidence_strength": "strong",
             "disputed": False, "sources": [nav]}
    text, mapping = _summarize_chains([chain], ["PostgreSQL"])
    print("mapping:", mapping)
    print("numbered lines:", [l for l in text.splitlines() if "[[" in l])
    r = _bind_citations({"recommendation": "Use Postgres [[1]]."}, mapping)
    print("bind [[1]] ->", repr(r["recommendation"]))

    # ---- Route 2: number_sources + inject_citations ----------------------
    show("ROUTE 2: number_sources + inject_citations (reading view / PDF)")
    reg = number_sources([chain])
    print("registry:", reg)
    md = f"Basis: [{nav['title']}]({nav['url']})"
    print("inject:", repr(inject_citations(md, reg)))

    # ---- Route 3: verbatim [Source: title] ------------------------------
    show("ROUTE 3: verbatim [Source: <title>] sanitization")
    out = _sanitize_citations(
        {"recommendation": f"Claim A [Source: {nav['title']}]. Claim B [Source: Real]. "},
        [chain])
    print("recommendation ->", repr(out["recommendation"]))

    # ---- Route 4: what_why_how Why bullets / References / What -----------
    show("ROUTE 4: what_why_how render")
    state = {"task": {"query": "PostgreSQL vs Pinecone", "candidate_techs": ["PostgreSQL", "Pinecone"]},
             "evidence_chains": [chain], "conflicts": [], "knowledge_gaps": [],
             "final_recommendation": {"winner": "PostgreSQL", "winner_rationale": "x",
                                      "recommendation": "y", "ranked_options": [], "trade_offs": []},
             "confidence": "low"}
    rep = render_www(state)
    print(rep)
    print("--> body-less URL present in report?", nav["url"] in rep)
    print("--> numbered badge present in report?", bool(re.search(r"#ev-\d", inject_citations(rep, reg))))

    # ---- Route 5: evidence_first "Strongest Evidence" --------------------
    show("ROUTE 5: evidence_first render")
    rep5 = render_ef(state)
    print(rep5)
    print("--> body-less URL listed under Strongest Evidence?", nav["url"] in rep5)
    print("--> has '[N]' badge?", bool(re.search(r"#ev-\d", inject_citations(rep5, reg))))

    # ---- Route 6: comparison_matrix -------------------------------------
    show("ROUTE 6: comparison_matrix render")
    rep6 = render_cm(state)
    print("--> body-less URL present?", nav["url"] in rep6)
    print("--> title present?", nav["title"] in rep6)

    # ---- Route 7: _cited_sources with a body-less chain source -----------
    show("ROUTE 7: _cited_sources matching a body-less chain source")
    from deepchoice.formats.what_why_how import _cited_sources
    chain_sources = {chain["conclusion"].lower(): [f"[{nav['title']}]({nav['url']})"]}
    got = _cited_sources(f"[Source: {nav['title']}]", chain_sources)
    print("cited ->", got)

    # ---- Route 8: real snapshot -----------------------------------------
    show("ROUTE 8: real snapshot (29 sources)")
    snap = json.load(open(REAL, encoding="utf-8"))
    chains = snap.get("evidence_chains", [])
    bodyless, bodied = [], []
    for c in chains:
        for s in c.get("sources", []):
            (bodied if has_factual_content(s) else bodyless).append(s)
    print(f"chains={len(chains)} sources={len(bodyless) + len(bodied)} bodied={len(bodied)} bodyless={len(bodyless)}")
    for s in bodyless[:5]:
        print("   bodyless:", s.get("title"), "|", repr((s.get("snippet") or "")[:70]))
    reg8 = number_sources(chains)
    print("registry size:", len(reg8), "urls:", [r["url"] for r in reg8])
    snap5 = dict(snap)
    snap5["task"] = {**snap["task"], "report_format": "evidence_first"}
    rep8 = render_ef(snap)
    leaked = [s for s in bodyless if s.get("url") and s["url"] in rep8]
    print(f"evidence_first: bodyless sources appearing in report: {len(leaked)}")
    for s in leaked[:8]:
        print("   LEAK:", s.get("title"), s.get("url"))
    rep8w = render_www(snap)
    leakedw = [s for s in bodyless if s.get("url") and s["url"] in rep8w]
    print(f"what_why_how: bodyless sources appearing in report: {len(leakedw)}")
    for s in leakedw[:8]:
        print("   LEAK:", s.get("title"), s.get("url"))
    rep8c = render_cm(snap)
    leakedc = [s for s in bodyless if s.get("url") and s["url"] in rep8c]
    print(f"comparison_matrix: bodyless sources appearing in report: {len(leakedc)}")


asyncio.run(main())
