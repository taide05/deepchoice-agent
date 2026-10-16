"""The three named generation errors: trace each to its cause."""
import io
import json
import pathlib
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"D:\deepchoice-precodex\src")

RUN = pathlib.Path(r"D:\deepchoice-precodex\outputs"
                   r"\8049500c-bd39-44e4-81bb-a1fbbebac780")
state = json.loads((RUN / "research_snapshot.json").read_text(encoding="utf-8"))
report = (RUN / "report.md").read_text(encoding="utf-8")
chains = state.get("evidence_chains") or []

print("=== 1. the number-scale claim: 5万亿 vs 500亿 ===")
for c in chains:
    for s in c.get("sources", []):
        body = s.get("snippet") or ""
        if "亿行" in body or "万亿" in body or "500" in body:
            print(f"  source: {s.get('title','')[:60]}")
            for token in ("500 亿", "500亿", "5 万亿", "5万亿", "数十亿", "数万亿"):
                if token in body:
                    i = body.find(token)
                    print(f"    body has {token!r}: ...{body[max(0,i-70):i+70]}...")
for token in ("5 万亿", "5万亿", "500 亿", "500亿"):
    if token in report:
        i = report.find(token)
        print(f"  REPORT has {token!r}: ...{report[max(0,i-100):i+80]}...")

print("\n=== 2. the Serverless #1 rationale and what supports it ===")
rec = state.get("final_recommendation") or {}
top = (rec.get("ranked_options") or [{}])[0]
print("  name:", top.get("name"))
for field in ("rationale", "constraint_fit_reason", "key_strength", "key_weakness"):
    print(f"  {field}: {str(top.get(field))[:200]}")
print("\n  Which sources does #1 cite, and do they have bodies?")
import re
cited = set()
for field in ("rationale", "constraint_fit_reason", "key_strength", "key_weakness"):
    for name in re.findall(r"\[Source:\s*([^\]]+)\]", str(top.get(field) or "")):
        for part in name.split(", Source:"):
            cited.add(part.strip())
for name in sorted(cited):
    hit = None
    for c in chains:
        for s in c.get("sources", []):
            if s.get("title") == name:
                hit = s
    print(f"    {name[:64]:66} body={len((hit or {}).get('snippet') or '') if hit else 'NOT IN CHAINS'}")

print("\n=== 3. Athena excluded from chains, yet cited ===")
ath = "https://aws.amazon.com/athena/"
inscore = [s for s in (state.get("source_scores") or [])
           if "athena" in f"{s.get('title','')} {s.get('url','')}".lower()
           and "antihydrogen" not in (s.get("title") or "").lower()]
for s in inscore:
    print(f"  score={s.get('total_score')} type={s.get('source_type')} "
          f"body={len(s.get('snippet') or '')}  {s.get('title','')[:60]}")
inchain = any(s.get("url") == ath or "athena - serverless" in (s.get("title", "") or "").lower()
              for c in chains for s in c.get("sources", []))
print(f"  present in evidence_chains: {inchain}")
print("  evidence_chain floor: total_score >= 4.0 (see build_evidence_chain)")
# Which Athena sources made it in, and at what strength?
for c in chains:
    for s in c.get("sources", []):
        t = (s.get("title") or "")
        if "athena" in t.lower():
            print(f"    chain strength={c.get('evidence_strength')} score={s.get('score')} {t[:70]}")
