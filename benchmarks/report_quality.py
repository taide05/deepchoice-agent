"""Deterministic report quality checklist — replaces unreliable LLM-as-Judge.

Five binary checks, no LLM calls. Computable in <1s per report, 100% reproducible.

Quality grades:
  A = 5/5  — production-ready report
  B = 4/5  — solid, minor gaps
  C = 3/5  — usable but missing key elements
  D = ≤2/5 — incomplete or unreliable
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------

# Keywords indicating limitation/downside acknowledgement
LIMITATION_KEYWORDS = [
    "limitation", "limitations", "局限", "不足", "缺点",
    "trade-off", "tradeoff", "trade off", "权衡",
    "depends on", "取决于", "视情况",
    "not suitable", "不适合", "not ideal",
    "downside", "drawback", "caveat", "caveats",
    "however", "但是", "然而", "though",
    "on the other hand", "另一方面",
    " acknowledged ", "承认",
]

# Keywords indicating evaluation dimensions
DIMENSION_KEYWORDS = {
    "performance": ["performance", "性能", "latency", "延迟", "throughput", "吞吐", "speed", "速度", "benchmark"],
    "ecosystem": ["ecosystem", "生态", "community", "社区", "plugin", "插件", "extension", "扩展", "integration", "集成"],
    "ease_of_use": ["easy", "simple", "简洁", "易用", "learning curve", "学习曲线", "上手", "入门", "documentation", "文档"],
    "scalability": ["scale", "scal", "扩展性", "伸缩", "concurrent", "并发", "distributed", "分布式"],
    "reliability": ["reliab", "stability", "稳定", "mature", "成熟", "production", "生产", "battle-tested"],
    "cost": ["cost", "成本", "price", "价格", "free", "免费", "open source", "开源", "license", "许可"],
    "security": ["security", "安全", "vulnerability", "漏洞", "auth", "认证", "compliance", "合规"],
    "maintainability": ["maintain", "维护", "code quality", "代码质量", "technical debt", "技术债务", "readability"],
}


def check_winner_extractable(report: str, tech_a: str = "", tech_b: str = "") -> dict[str, Any]:
    """Check if a clear winner recommendation can be extracted from the report."""
    from benchmarks.metrics import extract_top_recommendation

    winner = extract_top_recommendation(report, tech_a, tech_b)
    return {
        "pass": winner is not None,
        "value": winner,
        "detail": f"Winner: {winner}" if winner else "No winner extractable",
    }


def check_source_citations(report: str) -> dict[str, Any]:
    """Check if report has enough source citations (markdown links)."""
    citations = re.findall(r'\[([^\]]+)\]\(https?://[^\)]+\)', report)
    count = len(citations)
    passed = count >= 3
    return {
        "pass": passed,
        "value": count,
        "detail": f"{count} source citations (need >= 3)" if not passed else f"{count} source citations",
    }


def check_both_sides_discussed(report: str, tech_a: str = "", tech_b: str = "") -> dict[str, Any]:
    """Check if both technologies are discussed in the report."""
    report_lower = report.lower()
    a_found = tech_a.lower() in report_lower if tech_a else True
    b_found = tech_b.lower() in report_lower if tech_b else True

    missing = []
    if tech_a and not a_found:
        missing.append(tech_a)
    if tech_b and not b_found:
        missing.append(tech_b)

    passed = a_found and b_found
    return {
        "pass": passed,
        "value": {"tech_a_found": a_found, "tech_b_found": b_found},
        "detail": "Both discussed" if passed else f"Missing: {missing}",
    }


def check_limitation_acknowledged(report: str) -> dict[str, Any]:
    """Check if report acknowledges limitations, trade-offs, or uncertainty."""
    report_lower = report.lower()
    found_keywords = [kw for kw in LIMITATION_KEYWORDS if kw in report_lower]
    passed = len(found_keywords) >= 1
    return {
        "pass": passed,
        "value": len(found_keywords),
        "detail": f"Found: {found_keywords[:5]}" if passed else "No limitation language found",
    }


def check_dimension_coverage(report: str) -> dict[str, Any]:
    """Check if report covers at least 3 evaluation dimensions."""
    report_lower = report.lower()
    covered = []
    for dim, keywords in DIMENSION_KEYWORDS.items():
        if any(kw in report_lower for kw in keywords):
            covered.append(dim)

    passed = len(covered) >= 3
    return {
        "pass": passed,
        "value": len(covered),
        "detail": f"Covered {len(covered)}/8 dimensions: {covered}" if not passed
                  else f"Covered {len(covered)}/8 dimensions: {covered}",
    }


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------

QUALITY_CHECKS = [
    ("winner_extractable", "Winner extractable", check_winner_extractable),
    ("source_citations", "Source citations (>= 3)", check_source_citations),
    ("both_sides", "Both sides discussed", check_both_sides_discussed),
    ("limitation", "Limitation acknowledged", check_limitation_acknowledged),
    ("dimensions", "Dimension coverage (>= 3)", check_dimension_coverage),
]


def grade(pass_count: int) -> str:
    if pass_count >= 5:
        return "A"
    if pass_count == 4:
        return "B"
    if pass_count == 3:
        return "C"
    return "D"


def evaluate_report(report: str, tech_a: str = "", tech_b: str = "") -> dict[str, Any]:
    """Run all 5 quality checks on a single report.

    Returns a dict with individual check results, pass count, and grade.
    """
    if not report or len(report.strip()) < 100:
        return {
            "pass_count": 0,
            "grade": "D",
            "checks": {},
            "note": "Report too short or empty",
        }

    results = {}
    pass_count = 0

    for check_id, _label, check_fn in QUALITY_CHECKS:
        if check_id in ("winner_extractable", "both_sides"):
            result = check_fn(report, tech_a, tech_b)
        else:
            result = check_fn(report)
        results[check_id] = result
        if result["pass"]:
            pass_count += 1

    return {
        "pass_count": pass_count,
        "grade": grade(pass_count),
        "checks": results,
    }


def evaluate_batch(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate all reports in a batch run and return aggregate stats."""
    grades = []
    pass_counts = []
    check_pass_rates = {cid: {"passed": 0, "total": 0} for cid, _, _ in QUALITY_CHECKS}

    for run in runs:
        report = run.get("report", "")
        query = run.get("query", "")

        # Extract tech_a/tech_b from query pattern "X vs Y for ..."
        tech_a = ""
        tech_b = ""
        vs_match = re.search(r'(.+?)\s+vs\s+(.+?)(?:\s+for\s+|$)', query)
        if vs_match:
            tech_a = vs_match.group(1).strip()
            tech_b = vs_match.group(2).strip()

        quality = evaluate_report(report, tech_a, tech_b)
        run["report_quality"] = quality
        grades.append(quality["grade"])
        pass_counts.append(quality["pass_count"])

        for cid, result in quality.get("checks", {}).items():
            if result.get("pass"):
                check_pass_rates[cid]["passed"] += 1
            check_pass_rates[cid]["total"] += 1

    # Aggregate
    grade_dist = {"A": 0, "B": 0, "C": 0, "D": 0}
    for g in grades:
        grade_dist[g] = grade_dist.get(g, 0) + 1

    n = len(runs) if runs else 1
    return {
        "metric": "report_quality",
        "grade_distribution": grade_dist,
        "grade_a_pct": round(grade_dist["A"] / n * 100, 1),
        "grade_b_pct": round(grade_dist["B"] / n * 100, 1),
        "grade_c_pct": round(grade_dist["C"] / n * 100, 1),
        "grade_d_pct": round(grade_dist["D"] / n * 100, 1),
        "mean_pass_count": round(sum(pass_counts) / n, 2) if pass_counts else 0,
        "check_pass_rates": {
            cid: round(r["passed"] / r["total"] * 100, 1) if r["total"] else 0
            for cid, r in check_pass_rates.items()
        },
    }
