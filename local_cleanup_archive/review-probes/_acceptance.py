"""Acceptance check: do the decisive citations exist and support the claims?"""
import io
import json
import pathlib
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

RUN = pathlib.Path(r"D:\deepchoice-precodex\outputs"
                   r"\8049500c-bd39-44e4-81bb-a1fbbebac780")
report = (RUN / "report.md").read_text(encoding="utf-8")
state = json.loads((RUN / "research_snapshot.json").read_text(encoding="utf-8"))

chains = state.get("evidence_chains") or []
real_titles = set()
bodyless_titles = set()
for c in chains:
    for s in c.get("sources", []):
        t = s.get("title", "")
        if not t:
            continue
        has_body = s.get("has_body", None)
        snippet = s.get("snippet", "") or ""
        nav = (has_body is False) or (not snippet.strip()) or \
            snippet.startswith("NO CONTENT RETRIEVED")
        (bodyless_titles if nav else real_titles).add(t)

cited = re.findall(r"\[Source:\s*([^\]]+)\]", report)
titles = [t.strip() for part in cited for t in part.split(", Source:")]
print(f"total [Source:] citations: {len(titles)} | distinct: {len(set(titles))}")

print("\n=== citations that name a source with NO BODY (would be a leak) ===")
leak = sorted({t for t in titles if t in bodyless_titles})
print("  ", leak if leak else "NONE")

print("\n=== citations naming a title not in ANY evidence chain ===")
unknown = sorted({t for t in titles if t not in real_titles and t not in bodyless_titles})
print("  ", unknown if unknown else "NONE")

print(f"\n=== citation coverage: {len({t for t in titles if t in real_titles})} distinct "
      f"body-bearing sources cited of {len(real_titles)} available ===")

print("\n=== the specific decisive claims and whether their cited source has content ===")
claims = [
    ("UltraWarm $0.024/GB-月", "$0.024"),
    ("OpenSearch Serverless 免集群管理", "Serverless"),
    ("Athena 按扫描量计费", "Athena"),
]
for label, needle in claims:
    # Find the sentence carrying the claim and its citation.
    for line in report.splitlines():
        if needle in line and "[Source:" in line:
            found = re.findall(r"\[Source:\s*([^\]]+)\]", line)
            basis = []
            for name in found:
                for c in chains:
                    for s in c.get("sources", []):
                        if s.get("title", "") == name.strip():
                            snip = (s.get("snippet") or "")[:180]
                            basis.append((name.strip(), snip))
            print(f"\n  claim: {label}")
            for name, snip in basis[:2]:
                print(f"    source: {name}")
                print(f"    content: {snip}")
            break

print("\n=== does the report avoid presenting a nav link as a basis? ===")
nav_lines = [ln for ln in report.splitlines()
             if ("no body" in ln.lower() or "无正文" in ln or "导航链接" in ln)]
print(f"  lines labelled as navigation/body-less: {len(nav_lines)}")
for ln in nav_lines[:4]:
    print(f"    {ln[:150]}")

print("\n=== candidate sections ===")
for candidate in state["task"]["candidate_techs"]:
    marker = f"### {candidate}"
    if marker in report:
        section = report.split(marker)[1].split("###")[0]
        has_gap = "未取得明确指向" in section or "No retrieved material" in section
        has_material = "[link](" in section
        print(f"  {candidate[:42]:44} material={has_material} gap={has_gap}")
    else:
        print(f"  {candidate[:42]:44} MISSING")

print("\n=== run outcome ===")
print("  report bytes:", len(report.encode("utf-8")))
print("  conflicts:", len(state.get("conflicts") or []))
print("  chains:", len(chains), "| strong:",
      sum(1 for c in chains if c.get("evidence_strength") == "strong"))
counts = json.loads((RUN / "run_limits_counts.json").read_text(encoding="utf-8"))
print(f"  llm {counts['llm_requests']}/40 | tavily {counts['tavily_posts']}/24 "
      f"| run {counts['run_elapsed_s']}s/900 | stop_reason={counts['stop_reason']}")
