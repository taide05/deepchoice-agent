"""Analyze token usage and report structure from benchmark runs."""
import json, re, os, statistics

RUNS_DIR = os.path.join(os.path.dirname(__file__), "runs")

all_runs = []
for i in range(1, 21):
    fname = os.path.join(RUNS_DIR, f"runs-batch{i:02d}.json")
    try:
        batch = json.load(open(fname, "r", encoding="utf-8"))
        all_runs.extend(batch)
    except Exception:
        pass

print(f"Total runs: {len(all_runs)}")

# Analyze reports
report_lens = []
link_counts = []
boilerplate_counts = []
src_url_counts = []
boilerplate_patterns = [
    r"Data coverage:",
    r"Confidence is \w+ because",
    r"\*\*Recommendation:\*\*",
    r"Evidence strength is",
]

for run in all_runs:
    report = run.get("report", "")
    report_lens.append(len(report))
    links = re.findall(r"\[([^\]]+)\]\(https?://[^\)]+\)", report)
    link_counts.append(len(links))
    src_count = sum(len(sr.get("results", [])) for sr in run.get("search_results", []))
    src_url_counts.append(src_count)
    bp_count = sum(len(re.findall(bp, report)) for bp in boilerplate_patterns)
    boilerplate_counts.append(bp_count)

avg_len = statistics.mean(report_lens)
avg_links = statistics.mean(link_counts)
avg_src = statistics.mean(src_url_counts)
avg_bp = statistics.mean(boilerplate_counts)

print(f"Avg report: {avg_len:.0f} chars, {avg_links:.1f} links, {avg_src:.1f} source URLs, {avg_bp:.1f} boilerplate hits")
print()

# Source-cited vs LLM-generated estimation
cited_chars_per_link = 150
cited_ratio = (avg_links * cited_chars_per_link) / avg_len * 100
print(f"Estimated source-cited content: {avg_links * cited_chars_per_link:.0f} chars ({cited_ratio:.0f}%)")
print(f"Estimated LLM-generated analysis: {avg_len - avg_links * cited_chars_per_link:.0f} chars ({100-cited_ratio:.0f}%)")
print()

# Sample: read a full report and show structure
sample = all_runs[0]
report = sample["report"]
links = re.findall(r"\[([^\]]+)\]\(https?://[^\)]+\)", report)

# Count sections
sections = re.findall(r"(?im)^#{1,3}\s+(.+)", report)
print(f"=== Sample report: {sample['case_id']} ===")
print(f"  Sections: {len(sections)} ({[s[:30] for s in sections[:8]]}...)")
print(f"  Total links: {len(links)}")
print()

# What sections are not source-backed?
# Count links per section by finding sections and then links within them
section_positions = [(m.group(1), m.start()) for m in re.finditer(r"(?im)^#{1,3}\s+(.+)", report)]
section_positions.append(("END", len(report)))
for i, (title, pos) in enumerate(section_positions[:-1]):
    next_pos = section_positions[i + 1][1]
    section_text = report[pos:next_pos]
    section_links = len(re.findall(r"\[([^\]]+)\]\(https?://[^\)]+\)", section_text))
    section_chars = len(section_text)
    print(f"  [{section_links} links, {section_chars} chars] {title[:60]}")

print()
print("=== Token flow per 9-agent pipeline ===")
print("1. query_analyzer      (flash):  ~200 out,  ~500 in  — cheap, 5 dims")
print("2. query_adapter       (flash):  ~500 out, ~1000 in  — cheap, 6x adaptation")
print("3. multi_retriever              :  no LLM              — 6 API calls")
print("4. source_evaluator             :  no LLM              — rule engine")
print("5. conflict_detector   (flash):  ~1000 out, ~2000 in  — N pairs x LLM scan, expensive")
print("6. evidence_chain               :  no LLM              — rule engine")
print("7. conclusion_synth    (PRO):    ~4000 out, ~6000 in  — THE BIG ONE, 15x cost")
print("8. report_generator             :  no LLM              — pure rendering")
print("9. self_reviewer       (flash):  ~500 out,  ~3000 in  — 6-item check")
print()

# Per-case estimates
per_case = {"in": 500 + 1000 + 2000 + 6000 + 3000, "out": 200 + 500 + 1000 + 4000 + 500}
print(f"Estimated per-case: {per_case['in']} in, {per_case['out']} out")
print(f"Estimated 200-case: {per_case['in'] * 200 / 1e6:.1f}M in, {per_case['out'] * 200 / 1e6:.1f}M out")
print(f"Of which conclusion_synth (PRO): {(4000 * 200 + 6000 * 200) / 1e6:.1f}M tokens alone")
print()

# PRO vs flash cost for conclusion_synthesizer
pro_in_cost = 0.55   # $/1M input (DeepSeek pro)
pro_out_cost = 1.10  # $/1M output
flash_in_cost = 0.14  # $/1M input
flash_out_cost = 0.28  # $/1M output

pro_cost_200 = (6000 * 200 / 1e6) * pro_in_cost + (4000 * 200 / 1e6) * pro_out_cost
flash_cost_200 = (6000 * 200 / 1e6) * flash_in_cost + (4000 * 200 / 1e6) * flash_out_cost
print(f"PRO conclusion_synthesizer cost for 200 cases: ${pro_cost_200:.2f}")
print(f"Flash conclusion_synthesizer cost for 200 cases: ${flash_cost_200:.2f}")
print(f"Savings if switched: ${pro_cost_200 - flash_cost_200:.2f}")

# The big question: does PRO actually produce better answers?
# Compare: PRO era (current) vs flash era (old)
print()
print("=== PRO vs Flash quality comparison ===")
print("Old E (before flash->pro upgrade, commit 6631bbc): Top-1 ~56.8%")
print("Current E: Top-1 74.9% (pre-fix) / 75.9% (post-fix)")
print("Winner extractable rate: 100% (was <90% with flash)")
print()
print("CONCLUSION: PRO model is justified for conclusion_synthesizer.")
print("The real waste is in conflict_detector's LLM scans (1000 out/case)")
print("and self_reviewer (500 out/case) which scale linearly with case count.")
print()
print("Also: none of the prompts share prefix → cache never hits.")
print("If we could standardize system prompts, cache hit rate would improve.")
