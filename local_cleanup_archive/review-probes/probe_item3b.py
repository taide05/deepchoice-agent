"""Precise: does every cited link resolve to a body-BEARING chain source (title+url
of one source dict), and is any cited link only ever body-less?"""
import json, re, sys, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"D:\deepchoice-precodex\src")
sys.path.insert(0, r"D:\deepchoice-precodex")

from deepchoice.formats.what_why_how import render, _has_body, _cited_source_links
from deepchoice.utils.candidate_identity import has_factual_content, split_navigation_label

state = json.loads(Path(r"D:\deepchoice-precodex\outputs\8049500c-bd39-44e4-81bb-a1fbbebac780\research_snapshot.json").read_text(encoding="utf-8"))
rec = state.get("final_recommendation") or {}
chains = state.get("evidence_chains") or []

# Every occurrence of each url across chains, with both body predicates.
from collections import defaultdict
occ = defaultdict(list)
for ch in chains:
    for s in ch.get("sources", []):
        occ[s.get("url", "")].append(
            {"title": s.get("title", "")[:50],
             "_has_body": _has_body(s),
             "has_factual_content": has_factual_content(s),
             "snippet_len": len(s.get("snippet") or ""),
             "has_body_key": "has_body" in s})

pairs = _cited_source_links(rec, chains)
print("=== _cited_source_links returned %d (title,url) pairs ===" % len(pairs))
for t, u in pairs:
    o = occ.get(u, [])
    any_body = any(x["has_factual_content"] for x in o)
    print(f"  {t[:45]!r}\n     {u}\n     occurrences={o}\n     resolves to a body-bearing occurrence={any_body}")

print("\n=== nav candidates (chain sources the renderer treats as body-less) ===")
n = 0
for ch in chains:
    for s in ch.get("sources", []):
        if not _has_body(s):
            n += 1
            print("  body-less:", s.get("url"), "| snippet=%r" % (s.get("snippet") or "")[:80])
print("  total body-less chain sources:", n)
