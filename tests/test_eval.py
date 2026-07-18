"""LLM-as-Judge evaluation runner for DeepChoice."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

EVAL_PROMPT = """You are an impartial evaluator. Score this research report on 5 dimensions (1-5 each).

## Report
{report}

## Original Query
{query}

## Scoring Rubric
1. Factual Consistency (1-5): Are claims consistent with the cited sources? Deduct for hallucinated facts.
2. Evidence Sufficiency (1-5): Does each major claim have at least one source? Deduct for unsourced claims.
3. Reasoning Logic (1-5): Is the reasoning chain coherent? Deduct for logical gaps.
4. Honesty (1-5): Are gaps and uncertainties clearly stated? Deduct for overconfidence.
5. Completeness (1-5): Are all sub-questions answered? Deduct for missing dimensions.

Return ONLY a JSON object:
{{
  "factual_consistency": N,
  "evidence_sufficiency": N,
  "reasoning_logic": N,
  "honesty": N,
  "completeness": N,
  "total": N.N,
  "notes": "Brief justification"
}}"""


async def evaluate_report(query: str, report: str) -> dict:
    from deepchoice.utils.llm import call_model
    prompt = [{"role": "user", "content": EVAL_PROMPT.format(query=query, report=report)}]
    result = await call_model(prompt, model="deepseek-v4-flash", response_format="json")
    return result


async def run_regression_suite(known_cases_path: str, report_getter) -> dict:
    """Run evaluation on known cases. report_getter is async fn(query) -> report str."""
    cases = json.loads(Path(known_cases_path).read_text(encoding="utf-8"))
    results = []

    for case in cases[:30]:
        report = await report_getter(case["query"])
        scores = await evaluate_report(case["query"], report)
        results.append({"case_id": case["id"], "scores": scores, "query": case["query"]})

    avg_total = sum(r["scores"]["total"] for r in results) / len(results) if results else 0
    return {
        "cases_evaluated": len(results),
        "average_total_score": round(avg_total, 2),
        "pass_threshold_3_5": avg_total >= 3.5,
        "results": results,
    }
