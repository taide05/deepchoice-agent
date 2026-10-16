"""Build the actual self_reviewer payload from the preserved run and inspect it."""
import json, re, sys
from pathlib import Path

sys.path.insert(0, r"D:\deepchoice-precodex\src")
sys.path.insert(0, r"D:\deepchoice-precodex")

SNAP = Path(r"D:\deepchoice-precodex\outputs\8049500c-bd39-44e4-81bb-a1fbbebac780\research_snapshot.json")
state = json.loads(SNAP.read_text(encoding="utf-8"))

from deepchoice.agents.self_reviewer import SelfReviewerAgent, _citation_coverage

# Reproduce the node's payload construction verbatim (lines 64-137).
upstream_signals = state.get("quality_signals", [])
signals_text = "\n".join(
    f"- {s.get('agent', 'unknown')}: { {k: v for k, v in s.items() if k != 'agent'} }"
    for s in upstream_signals) if upstream_signals else "No upstream quality signals available."

chains_summary = []
for c in state.get("evidence_chains", []):
    strength = c.get("evidence_strength", "unknown")
    conclusion = c.get("conclusion", "")[:200]
    sources = c.get("sources", [])
    source_titles = [s.get("title", "?")[:80] for s in sources[:2]]
    chains_summary.append(f"[{strength}] {conclusion} (sources: {', '.join(source_titles)})")
chains_text = "\n".join(chains_summary) if chains_summary else "No evidence chains."

cite_stats = _citation_coverage(state.get("final_recommendation", {}))

claims_summary = []
for opt in (state.get("final_recommendation") or {}).get("ranked_options") or []:
    if not isinstance(opt, dict):
        continue
    claims_summary.append(f"#{opt.get('rank', '?')} {opt.get('name', '')} (constraint_fit={opt.get('constraint_fit', '?')})")
    for field in ("rationale", "constraint_fit_reason", "key_strength", "key_weakness"):
        value = opt.get(field)
        if value:
            claims_summary.append(f"    {field}: {value}")
for to in (state.get("final_recommendation") or {}).get("trade_offs") or []:
    if isinstance(to, dict) and to.get("finding"):
        claims_summary.append(f"trade-off [{to.get('dimension', '')}]: {to.get('finding')}")
claims_text = "\n".join(claims_summary) if claims_summary else "No ranked options were produced."

report = state.get("report", "") or ""

def has(needle, hay):
    return needle in hay

print("=== ranked_options field inventory ===")
for opt in (state.get("final_recommendation") or {}).get("ranked_options") or []:
    print("  name=%r keys=%s" % (opt.get("name"), sorted(opt.keys())))

print("\n=== claims_text length:", len(claims_text))
print("claims_text contains '5 万亿':", has("5 万亿", claims_text))
print("claims_text contains 'Serverless':", has("Serverless", claims_text))
print("claims_text contains 'Athena':", has("Athena", claims_text))
print("claims_text contains '500 亿':", has("500 亿", claims_text))

# What source TEXT (not title) does the payload actually contain?
src_bodies = []
for c in state.get("evidence_chains") or []:
    for s in c.get("sources", []):
        sn = s.get("snippet") or ""
        if sn:
            src_bodies.append((s.get("title", "?"), sn))
print("\n=== evidence-chain sources in snapshot:", len(src_bodies), "with non-empty snippet")
infoq = [(t, sn) for t, sn in src_bodies if "InfoQ" in t]
for t, sn in infoq:
    print("  InfoQ snippet has '500 亿行':", has("500 亿行", sn), "| snippet[:200]=%r" % sn[:200])

full_payload = report + "\n" + chains_text + "\n" + signals_text + "\n" + claims_text
print("\n=== FULL REVIEWER PAYLOAD (report + chains + signals + claims) ===")
print("total payload chars:", len(full_payload))
print("contains '500 亿':", has("500 亿", full_payload))
print("contains '5 万亿':", has("5 万亿", full_payload))
print("contains 'Serverless':", has("Serverless", full_payload))
print("contains 'Athena':", has("Athena", full_payload))
# Is any chain source's snippet text present in the payload at all?
present = sum(1 for t, sn in src_bodies if sn[:60] and sn[:60] in full_payload)
print("chain snippets (first 60 chars) found in payload: %d / %d" % (present, len(src_bodies)))
# Does the payload carry any URL?
print("payload URLs:", len(re.findall(r"https?://", full_payload)))
print("\n=== report section headings ===")
for line in report.splitlines():
    if line.startswith("#"):
        print("  ", line)
