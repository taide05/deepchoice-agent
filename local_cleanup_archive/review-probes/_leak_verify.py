"""Verify the three leaks the re-review found, end to end. Read-only."""
import re
import sys

sys.path.insert(0, r"D:\deepchoice-precodex\src")

from deepchoice.formats.citations import inject_citations, number_sources
from deepchoice.formats.evidence_first import render as render_evidence
from deepchoice.formats.what_why_how import render as render_www
from deepchoice.agents.conclusion_synthesizer import (
    _bind_citations,
    _sanitize_citations,
    _summarize_chains,
)
from deepchoice.utils.candidate_identity import has_factual_content

results = []


def check(label, ok, detail=""):
    results.append((label, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")


NAV = {"url": "https://www.postgresql.org/docs/",
       "title": "PostgreSQL — Official Documentation",
       "snippet": "", "has_body": False, "score": 8.0}
REAL = {"url": "https://www.postgresql.org/docs/release-17",
        "title": "PostgreSQL 17 release notes",
        "snippet": "PostgreSQL 17 improves vacuum and logical replication.",
        "has_body": True, "score": 7.5}

print("=== 1. marker survives the pipeline stages (R4) ===")
from deepchoice.agents.evidence_chain import build_evidence_chain

chains = build_evidence_chain([
    {"url": NAV["url"], "title": NAV["title"], "snippet": "", "has_body": False,
     "total_score": 8.0, "scores": {}, "supporting_sources": []},
], [])
check("has_body marker survives evidence_chain",
      chains[0]["sources"][0].get("has_body") is False,
      str(chains[0]["sources"][0]))

print("\n=== 2. evidence_first 'Strongest Evidence' (R1) ===")
state = {"task": {"query": "pgvector", "candidate_techs": ["PostgreSQL"]},
         "evidence_chains": [{"conclusion": "c", "evidence_strength": "strong",
                              "disputed": False, "sources": [NAV]}],
         "conflicts": [], "knowledge_gaps": [], "final_recommendation": {},
         "confidence": "high"}
out = render_evidence(state)
# The link may be listed, but only as a labelled navigation reference, never as
# unlabelled evidence.
section = out.split("### Strongest Evidence")[-1].split("### Supporting")[0]
nav_lines = [ln for ln in section.splitlines() if NAV["url"] in ln]
check("body-less source is never listed as unlabelled evidence",
      all(("navigation link only" in ln) or ("no body collected" in ln)
          or ("导航链接" in ln) for ln in nav_lines),
      str(nav_lines)[:160])
check("a material gap is stated when no fact-bearing source exists",
      "material gap" in out or "资料缺口" in out)

print("\n=== 3. citation registry and evidence card (R2) ===")
mixed = [{"conclusion": "c", "evidence_strength": "strong", "disputed": False,
          "sources": [NAV, REAL]}]
registry = number_sources(mixed)
check("body-less source is not numbered", len(registry) == 1, str(registry))
check("only the real source is in the registry",
      registry and registry[0]["url"] == REAL["url"])
md = render_www({**state, "evidence_chains": mixed})
marked = inject_citations(md, registry)
check("no citation anchor on the body-less title",
      "Official Documentation" not in "".join(
          re.findall(r"([^>\n]*?)<sup><a class=\"cite\"", marked)),
      str(re.findall(r"([^>\n]*?)<sup><a class=\"cite\"", marked))[:200])
check("the real source is still citable",
      REAL["title"] in "".join(re.findall(r"([^>\n]*?)<sup><a class=\"cite\"", marked)))

print("\n=== 4. what_why_how re-attached *Sources:* line (R3) ===")
# The substring hazard: the nav title is a prefix of a longer real title.
result = _sanitize_citations(
    {"recommendation": "Use pgvector [Source: PostgreSQL — Official Documentation]."},
    mixed)
check("body-less title stripped by sanitization",
      "Official Documentation" not in result["recommendation"],
      result["recommendation"])
# Through the real mapping, which never contains a body-less title.
_prompt, real_mapping = _summarize_chains(mixed, ["PostgreSQL"])
bound = _bind_citations({"recommendation": "Use it [[1]]."}, real_mapping)
check("bind emits only a real source title",
      "Official Documentation" not in bound["recommendation"]
      and REAL["title"] in bound["recommendation"],
      bound["recommendation"])
check("no body-less title is reachable as a number",
      NAV["title"] not in real_mapping.values(), str(real_mapping))

print("\n=== 5. prompt still carries no inventable basis ===")
text, mapping = _summarize_chains(mixed, ["PostgreSQL"])
check("body-less source absent from the citation mapping",
      NAV["title"] not in mapping.values(), str(mapping))
check("its link is listed as non-citable", "NOT citable" in text)
check("the real source still carries URL and content",
      REAL["url"] in text and "vacuum" in text)

print("\n=== summary ===")
failed = [r for r in results if not r[1]]
for label, ok, _ in results:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
print(f"  {len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
