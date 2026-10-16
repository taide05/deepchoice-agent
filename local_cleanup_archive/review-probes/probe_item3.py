"""Item 3 on the preserved real run: which explanation feeds the candidate
bullets, and whether cited links are body-bearing while navigation links are not."""
import json, re, sys, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"D:\deepchoice-precodex\src")
sys.path.insert(0, r"D:\deepchoice-precodex")

from deepchoice.formats.what_why_how import render
from deepchoice.utils.candidate_identity import has_factual_content

state = json.loads(Path(r"D:\deepchoice-precodex\outputs\8049500c-bd39-44e4-81bb-a1fbbebac780\research_snapshot.json").read_text(encoding="utf-8"))
report = render(state)
what = report.split("\n## Why")[0]

# Body-ness lookup for every chain source URL.
body_by_url = {}
for chain in state.get("evidence_chains") or []:
    for s in chain.get("sources", []):
        body_by_url.setdefault(s.get("url", ""), has_factual_content(s))

print("=== candidate bullets are the ranking's explanation ===")
rec = state.get("final_recommendation") or {}
for opt in rec.get("ranked_options") or []:
    name = opt.get("name")
    head = f"### {name}"
    present = head in what
    rat = " ".join(str(opt.get("rationale") or "").split())
    frag = rat.split("；")[0][:24]
    print(f"  {name!r}: heading={present} rationale_fragment_in_what={bool(frag) and frag in what}")

cands = state["task"]["candidate_techs"]
explained = {str(o.get("name", "")).strip() for o in rec.get("ranked_options") or []}
print("  candidates with no ranked explanation:",
      [c for c in cands if c not in explained])

print("\n=== cited sources section ===")
cited_part = what.split("**Navigation links")[0]
cited_urls = re.findall(r"\]\((https?://[^)]+)\)", cited_part)
for u in dict.fromkeys(cited_urls):
    print(f"  {u} -> has_factual_content={body_by_url.get(u, 'NOT-IN-CHAINS')}")

print("\n=== navigation section ===")
nav_part = what.split("**Navigation links")[-1] if "**Navigation links" in what else ""
nav_urls = re.findall(r"\]\((https?://[^)]+)\)", nav_part)
for u in dict.fromkeys(nav_urls):
    print(f"  {u} -> has_factual_content={body_by_url.get(u, 'NOT-IN-CHAINS')}")

bad = [u for u in dict.fromkeys(cited_urls) if body_by_url.get(u) is False]
print("\n  body-less links wrongly listed as cited:", bad)
navbad = [u for u in dict.fromkeys(nav_urls) if body_by_url.get(u) is True]
print("  body-bearing links listed as navigation-only:", navbad)
print("  cited count:", len(dict.fromkeys(cited_urls)), "| nav count:", len(dict.fromkeys(nav_urls)))

# Does the cited list resolve to sources the ranking itself cites?
blob = " ".join(str(o.get(f) or "") for o in rec.get("ranked_options") or []
                for f in ("rationale", "constraint_fit_reason", "key_strength", "key_weakness"))
blob += str(rec.get("recommendation") or "")
names = set()
for m in re.findall(r"\[Source:\s*([^\]]+)\]", blob):
    for p in m.split(", Source:"):
        names.add(p.strip())
missing = [t for t in names if f"[{t}](" not in cited_part]
print("  cited titles that fail to resolve to a link:", missing)
