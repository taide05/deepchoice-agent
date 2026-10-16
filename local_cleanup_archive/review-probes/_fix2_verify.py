"""Verify both fixes against the captured run, plus the citation binding."""
import io
import json
import pathlib
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"D:\deepchoice-precodex\src")

from deepchoice.agents.conclusion_synthesizer import (
    _bind_citations, _CITATION_TEXT_FIELDS, _summarize_chains,
)
from deepchoice.formats.what_why_how import render
from deepchoice.utils.candidate_identity import (
    UNASSIGNED, candidate_for_source, index_sources_by_candidate,
)

RUN = pathlib.Path(r"D:\deepchoice-precodex\outputs"
                   r"\8049500c-bd39-44e4-81bb-a1fbbebac780")
state = json.loads((RUN / "research_snapshot.json").read_text(encoding="utf-8"))
candidates = state["task"]["candidate_techs"]
chains = state.get("evidence_chains") or []

results = []


def check(label, ok, detail=""):
    results.append((label, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")


print("=== A. Athena is no longer reported as having no material ===")
sources, seen = [], set()
for c in chains:
    for s in c.get("sources", []):
        if s.get("url") in seen:
            continue
        seen.add(s.get("url"))
        sources.append(s)
index = index_sources_by_candidate(sources, candidates)
athena = index.get("Amazon Athena over S3") or []
check("Athena candidate has attributed material", bool(athena),
      str([s.get("title", "")[:50] for s in athena]))
check("that material carries a body",
      all(len(s.get("snippet") or "") > 100 for s in athena),
      str([len(s.get("snippet") or "") for s in athena]))

print("\n=== B. a page about another product is not candidate material ===")
selectdb = "https://www.selectdb.com/blog/1398"
check("SelectDB comparison is unassigned",
      any(s.get("url") == selectdb for s in (index.get(UNASSIGNED) or [])))
check("SelectDB comparison is NOT ClickHouse material",
      not any(s.get("url") == selectdb for s in (index.get("ClickHouse") or [])))
elastic = "https://www.elastic.co/cn/amazon-opensearch-service"
check("Elastic pricing page is not OpenSearch Service material",
      not any(s.get("url") == elastic
              for s in (index.get("Amazon OpenSearch Service") or [])))

print("\n=== C. citation binding covers confidence_rationale ===")
check("confidence_rationale is bound",
      "confidence_rationale" in _CITATION_TEXT_FIELDS)
_prompt, mapping = _summarize_chains(chains, candidates)
bound = _bind_citations(
    {"confidence_rationale": "Strong chains are zero [[1]] and again [[2]]."},
    mapping)
check("[[N]] markers are converted, none left raw",
      "[[" not in bound["confidence_rationale"],
      bound["confidence_rationale"][:120])
check("converted markers name real sources",
      "[Source:" in bound["confidence_rationale"],
      bound["confidence_rationale"][:120])
unknown = _bind_citations({"confidence_rationale": "see [[999]]"}, mapping)
check("an out-of-range marker is dropped, not left raw",
      "[[" not in unknown["confidence_rationale"], unknown["confidence_rationale"])

print("\n=== D. the rendered report states the gaps honestly ===")
report = render(state)
for candidate in candidates:
    marker = f"### {candidate}"
    if marker not in report:
        check(f"{candidate} present", False)
        continue
    section = report.split(marker)[1].split("###")[0]
    has_material = "[link](" in section
    has_gap = "未取得明确指向" in section or "No retrieved material" in section
    print(f"  {candidate[:34]:36} material={has_material} gap={has_gap}")

print("\n=== summary ===")
failed = [r for r in results if not r[1]]
for label, ok, _ in results:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
print(f"  {len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
