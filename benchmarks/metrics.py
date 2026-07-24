"""DeepChoice Benchmark Metrics Calculator.

Seven metrics across three categories:
  Quality:   Top-1 Accuracy, Source Recall, Claim Grounding Rate, Conflict Detection Rate
  Efficiency: E2E Latency (P50/P95)
  Reliability: Task Success Rate, Retry Score Delta

All functions are pure calculations from pipeline output + annotations.
No external API calls in this module.
"""

from __future__ import annotations

import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Quality Metric 1: Top-1 Accuracy
# ---------------------------------------------------------------------------

# Words that should never be returned as technology names
_NON_TECH = frozenset({
    "the", "a", "an", "based", "highest", "scored", "option", "best",
    "scene", "context", "matches", "above", "evidence", "unknown",
    "data", "coverage", "ation", "and", "or", "for", "with", "from",
    "your", "this", "that", "which", "what", "how", "why", "when",
    "start", "pick", "choose", "verdict", "not", "but", "also", "can",
    "may", "will", "should", "would", "could", "has", "have", "been",
    "one", "two", "all", "some", "most", "more", "less",
})


def _clean_tech_name(raw: str) -> str | None:
    """Normalize and validate a technology name candidate."""
    name = raw.strip().lower()
    # Strip leading articles/stop words
    for prefix in ("the ", "a ", "an "):
        if name.startswith(prefix):
            name = name[len(prefix):]
    # Strip trailing stop words
    for stop in (" for ", " with ", " as ", " in ", " to ", " that ", " which "):
        idx = name.find(stop)
        if idx > 0:
            name = name[:idx]
            break
    # Reject if empty or a non-tech word
    if not name or name in _NON_TECH:
        return None
    # Reject single words that are generic
    if name in ("highest-scored", "best", "fastest", "cheapest", "simplest",
                 "option", "choice", "solution", "framework", "tool"):
        return None
    # Reject if first word is a generic adjective
    first_word = name.split()[0] if " " in name else name
    if first_word in ("highest", "highest-scored", "best", "fastest", "cheapest",
                       "simplest", "scored", "top", "leading", "popular",
                       "recommended", "suggested", "preferred"):
        return None
    # Reject arXiv-style IDs (e.g., 2401.18241v1, 2607.19297v1, 18241v1)
    if re.search(r'\d{4,5}v\d', name):
        return None
    # Reject if name is mostly digits/dots (version numbers, IDs)
    if re.search(r'^\d+[.\-]', name):
        return None
    # Reject if too short
    if len(name) < 2:
        return None
    return name


def extract_top_recommendation(report: str, tech_a: str = "", tech_b: str = "") -> str | None:
    """Extract the top-recommended technology name from a report.

    Tries multiple patterns in order:
    1. Explicit "Recommendation: X" or "推荐: X" header
    2. Ranked options list (#1 entry)
    3. "Start with X" / "Starting Point: X"
    4. Count which of tech_a/tech_b appears more often in high-signal context
    Returns the first technology name found, normalized to lowercase.
    """
    if not report:
        return None

    # Pattern 1: Explicit recommendation header
    m = re.search(
        r'(?im)^(?:#{1,3}\s*)?(?:\*\*)?(?:recommendation|推荐)(?:\*\*)?\s*:\s*'
        r'\*{0,2}([A-Za-z0-9+\-_. ]+?)\*{0,2}\s*$',
        report,
    )
    if m:
        result = _clean_tech_name(m.group(1))
        if result:
            return result

    # Pattern 1.5: "**Winner: X**" bold line (new format from fixed synthesizer)
    m = re.search(
        r'(?im)\*\*Winner:\s*\*\s*([A-Za-z0-9+\-_.]+(?:\s[A-Za-z0-9+\-_.]+){0,2})\*\*',
        report,
    )
    if m:
        result = _clean_tech_name(m.group(1))
        if result:
            return result

    # Pattern 2: "## How: Action Path" section with explicit recommendation
    # Matches: "start with the highest-scored option: X" or "verdict: X"
    how_section = re.search(
        r'(?im)^## How:.*?\n(.*?)(?=\n## |\Z)',
        report, re.DOTALL,
    )
    if how_section:
        how_text = how_section.group(1)
        m = re.search(
            r'(?i)(?:start with|verdict|recommend|推荐|pick|choose)\s*:?\s*'
            r'\*{0,2}([A-Za-z0-9+\-_.]+(?:\s[A-Za-z0-9+\-_.]+){0,2})'
            r'(?:\*{0,2}|\.|,)',
            how_text,
        )
        if m:
            candidate = m.group(1).strip().lower()
            # Strip trailing stop words
            for stop in (" for ", " with ", " as ", " in ", " to ", " that "):
                idx = candidate.find(stop)
                if idx > 0:
                    candidate = candidate[:idx]
                    break
            result = _clean_tech_name(candidate)
            if result:
                return result

    # Pattern 3: "#1" or "1." ranked option
    m = re.search(r'(?i)(?:#1\s*|1[.\)]\s*)\*{0,2}([A-Za-z0-9+\-_.]+)', report)
    if m:
        result = _clean_tech_name(m.group(1))
        if result:
            return result

    # Pattern 4: Title "X vs Y" — count high-signal mentions
    if tech_a and tech_b:
        report_lower = report.lower()
        # Count mentions in evidence strength context (strong > moderate > weak)
        a_score = len(re.findall(
            r'evidence strength.*?' + re.escape(tech_a.lower()),
            report_lower, re.DOTALL,
        )) * 2
        a_score += report_lower.count(tech_a.lower())
        b_score = len(re.findall(
            r'evidence strength.*?' + re.escape(tech_b.lower()),
            report_lower, re.DOTALL,
        )) * 2
        b_score += report_lower.count(tech_b.lower())
        if a_score > b_score:
            return tech_a.lower()
        elif b_score > a_score:
            return tech_b.lower()

    # Pattern 5: First technology listed in "Understanding the Candidates"
    m = re.search(
        r'(?i)## What:.*?\n\n- \*\*(.+?)\*\*',
        report, re.DOTALL,
    )
    if m:
        candidate = m.group(1).strip()
        for known in (tech_a, tech_b):
            if known and known.lower() in candidate.lower():
                result = _clean_tech_name(known)
                if result:
                    return result

    return None


def compute_top1_accuracy(
    runs: list[dict[str, Any]],
    annotated_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute Top-1 recommendation accuracy.

    Args:
        runs: List of {case_id, report, state} dicts from pipeline runs.
        annotated_cases: List of annotated cases with expected_winner field.

    Returns:
        Dict with accuracy, total, correct, per_case details.
    """
    case_map = {c["id"]: c for c in annotated_cases}
    correct = 0
    total = 0
    details = []

    for run in runs:
        case_id = run.get("case_id", "")
        case = case_map.get(case_id)
        if not case:
            continue
        expected = case.get("expected_winner", "").lower()
        if expected == "context_dependent":
            # Context-dependent cases are scored separately (see notes)
            continue

        report = run.get("report", "")
        predicted = extract_top_recommendation(
            report,
            tech_a=case.get("tech_a", ""),
            tech_b=case.get("tech_b", ""),
        )
        is_correct = predicted and expected in predicted
        if is_correct:
            correct += 1
        total += 1
        details.append({
            "case_id": case_id,
            "expected": expected,
            "predicted": predicted,
            "correct": is_correct,
        })

    accuracy = correct / total if total > 0 else 0.0
    return {
        "metric": "top1_accuracy",
        "value": round(accuracy, 3),
        "total": total,
        "correct": correct,
        "per_case": details,
    }


# ---------------------------------------------------------------------------
# Quality Metric 2: Source Recall
# ---------------------------------------------------------------------------

def _url_matches_pattern(url: str, pattern: str) -> bool:
    """Check if a URL contains the given domain/keyword pattern."""
    return pattern.lower() in url.lower()


def compute_source_recall(
    runs: list[dict[str, Any]],
    annotated_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute source recall: what fraction of must_find_sources were retrieved.

    Args:
        runs: List of {case_id, search_results} from pipeline runs.
        annotated_cases: List of annotated cases with must_find_sources field.

    Returns:
        Dict with recall, precision, per_case details.
    """
    case_map = {c["id"]: c for c in annotated_cases}
    total_must_find = 0
    total_found = 0
    total_retrieved = 0
    details = []

    for run in runs:
        case_id = run.get("case_id", "")
        case = case_map.get(case_id)
        if not case:
            continue

        must_find = case.get("must_find_sources", [])
        if not must_find:
            continue

        # Collect all retrieved URLs from all search results
        # search_results may be at run-level or nested inside state
        retrieved_urls: list[str] = []
        search_results = run.get("search_results", [])
        if not search_results:
            state = run.get("state")
            if isinstance(state, dict):
                search_results = state.get("search_results", [])
        for sr in search_results:
            for result in sr.get("results", []):
                url = result.get("url", "")
                if url:
                    retrieved_urls.append(url)

        total_retrieved += len(retrieved_urls)

        # Check each must_find pattern against retrieved URLs
        found = 0
        matched_patterns = []
        missed_patterns = []
        for mf in must_find:
            pattern = mf["pattern"]
            if any(_url_matches_pattern(url, pattern) for url in retrieved_urls):
                found += 1
                matched_patterns.append(pattern)
            else:
                missed_patterns.append(pattern)

        total_must_find += len(must_find)
        total_found += found
        details.append({
            "case_id": case_id,
            "must_find_count": len(must_find),
            "found": found,
            "retrieved_total": len(retrieved_urls),
            "matched": matched_patterns,
            "missed": missed_patterns,
        })

    recall = total_found / total_must_find if total_must_find > 0 else 0.0
    return {
        "metric": "source_recall",
        "value": round(recall, 3),
        "total_must_find": total_must_find,
        "total_found": total_found,
        "per_case": details,
    }


# ---------------------------------------------------------------------------
# Quality Metric 3: Claim Grounding Rate
# ---------------------------------------------------------------------------

def compute_claim_grounding_rate(report: str) -> dict[str, Any]:
    """Estimate what fraction of factual claims in a report are source-cited.

    Counts markdown links [text](url) as grounded claims, and standalone
    sentences with factual language as ungrounded claims. This is an
    approximation - manual spot-checking is needed for precision.

    Args:
        report: The rendered markdown report text.

    Returns:
        Dict with grounding_rate, grounded_count, ungrounded_count.
    """
    if not report:
        return {"metric": "claim_grounding_rate", "value": 0.0,
                "grounded": 0, "ungrounded": 0, "note": "empty report"}

    # Count source-cited claims: markdown links [text](url)
    grounded = len(re.findall(r'\[([^\]]+)\]\(https?://[^\)]+\)', report))

    # Count likely factual sentences (heuristic: sentences with comparison/
    # evaluation language that aren't part of a link)
    # Remove markdown links first, then count sentences with factual indicators
    text_no_links = re.sub(r'\[([^\]]+)\]\(https?://[^\)]+\)', '', report)
    factual_indicators = re.findall(
        r'(?i)(?:is|are|has|have|provides|offers|supports|better|faster|stronger|weaker|'
        r'more|less|higher|lower|faster|slower)\s',
        text_no_links,
    )
    ungrounded = max(0, len(factual_indicators) - grounded)
    # Cap ungrounded at a reasonable ratio to avoid inflated numbers from
    # non-factual uses of these words
    ungrounded = min(ungrounded, len(factual_indicators))

    total_claims = grounded + ungrounded
    rate = grounded / total_claims if total_claims > 0 else 0.0
    return {
        "metric": "claim_grounding_rate",
        "value": round(rate, 3),
        "grounded": grounded,
        "ungrounded": ungrounded,
    }


# ---------------------------------------------------------------------------
# Quality Metric 4: Conflict Detection Rate
# ---------------------------------------------------------------------------

def compute_conflict_detection_rate(
    runs: list[dict[str, Any]],
    annotated_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute how many known contradictions the conflict detector found.

    Matches detected conflicts to annotated known_contradictions by topic
    keyword overlap.

    Args:
        runs: List of {case_id, conflicts} from pipeline runs.
        annotated_cases: Cases with known_contradictions field.

    Returns:
        Dict with detection_rate, detected, total_known, per_case.
    """
    case_map = {c["id"]: c for c in annotated_cases}
    total_known = 0
    total_detected = 0
    details = []

    for run in runs:
        case_id = run.get("case_id", "")
        case = case_map.get(case_id)
        if not case:
            continue

        known = case.get("known_contradictions", [])
        if not known:
            continue

        detected_conflicts = run.get("conflicts", [])
        # Build a set of keywords from all detected conflicts
        detected_text = " ".join(
            str(c) for c in detected_conflicts
        ).lower()

        detected_count = 0
        matched_topics = []
        missed_topics = []
        for kc in known:
            topic = kc["topic"].lower()
            # Check if the topic keywords appear in detected conflicts
            topic_words = set(re.findall(r'\w+', topic))
            detected_words = set(re.findall(r'\w+', detected_text))
            overlap = topic_words & detected_words
            # Require at least 2 keyword matches to count as detected
            if len(overlap) >= 2:
                detected_count += 1
                matched_topics.append(kc["topic"])
            else:
                missed_topics.append(kc["topic"])

        total_known += len(known)
        total_detected += detected_count
        details.append({
            "case_id": case_id,
            "known_count": len(known),
            "detected": detected_count,
            "matched": matched_topics,
            "missed": missed_topics,
        })

    rate = total_detected / total_known if total_known > 0 else 0.0
    return {
        "metric": "conflict_detection_rate",
        "value": round(rate, 3),
        "total_known": total_known,
        "total_detected": total_detected,
        "per_case": details,
    }


# ---------------------------------------------------------------------------
# Efficiency Metric 5: E2E Latency
# ---------------------------------------------------------------------------

def compute_latency_stats(latencies_s: list[float]) -> dict[str, Any]:
    """Compute P50, P95, mean, min, max from a list of latencies in seconds.

    Args:
        latencies_s: List of end-to-end latencies in seconds.

    Returns:
        Dict with p50, p95, mean, min, max, count.
    """
    if not latencies_s:
        return {"metric": "e2e_latency", "p50": 0, "p95": 0, "mean": 0,
                "min": 0, "max": 0, "count": 0}

    sorted_l = sorted(latencies_s)
    n = len(sorted_l)

    def percentile(p: float) -> float:
        k = (p / 100) * (n - 1)
        f = int(k)
        c = k - f
        if f + 1 < n:
            return sorted_l[f] + c * (sorted_l[f + 1] - sorted_l[f])
        return sorted_l[f]

    return {
        "metric": "e2e_latency",
        "p50": round(percentile(50), 1),
        "p95": round(percentile(95), 1),
        "mean": round(statistics.mean(sorted_l), 1),
        "min": round(sorted_l[0], 1),
        "max": round(sorted_l[-1], 1),
        "count": n,
    }


# ---------------------------------------------------------------------------
# Reliability Metric 6: Task Success Rate
# ---------------------------------------------------------------------------

def compute_success_rate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the fraction of pipeline runs that produced a valid report.

    A run is successful if:
    - No exception/timeout
    - Report is non-empty
    - state is not None

    Args:
        runs: List of {case_id, report, state, error, elapsed_s} from pipeline runs.

    Returns:
        Dict with success_rate, total, success, failure, failure_modes.
    """
    total = len(runs)
    success = 0
    failures = []

    for run in runs:
        has_error = run.get("error") is not None
        has_state = run.get("state") is not None
        report = run.get("report", "")
        has_report = bool(report and len(report.strip()) > 100)

        if not has_error and has_state and has_report:
            success += 1
        else:
            mode = "timeout" if "timeout" in str(run.get("error", "")) else \
                   "exception" if run.get("error") else \
                   "empty_report" if not has_report else \
                   "no_state"
            failures.append({
                "case_id": run.get("case_id", "unknown"),
                "mode": mode,
                "error": str(run.get("error", ""))[:200],
            })

    rate = success / total if total > 0 else 0.0
    return {
        "metric": "task_success_rate",
        "value": round(rate, 3),
        "total": total,
        "success": success,
        "failure": total - success,
        "failure_modes": failures,
    }


# ---------------------------------------------------------------------------
# Reliability Metric 7: Retry Score Delta
# ---------------------------------------------------------------------------

def compute_retry_effectiveness(
    before_after_pairs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute the quality improvement from retry.

    Compares LLM-as-Judge scores before and after retry for the same query.

    Args:
        before_after_pairs: List of {case_id, score_before, score_after,
                            retry_triggered, retry_type}.

    Returns:
        Dict with mean_delta, improved_count, degraded_count, per_pair.
    """
    if not before_after_pairs:
        return {"metric": "retry_score_delta", "mean_delta": 0.0,
                "improved": 0, "degraded": 0, "unchanged": 0, "pairs": []}

    deltas = []
    improved = 0
    degraded = 0
    unchanged = 0
    pair_details = []

    for pair in before_after_pairs:
        before = pair.get("score_before", 0)
        after = pair.get("score_after", 0)
        delta = round(after - before, 2)
        deltas.append(delta)

        if delta > 0.1:
            improved += 1
        elif delta < -0.1:
            degraded += 1
        else:
            unchanged += 1

        pair_details.append({
            "case_id": pair.get("case_id", ""),
            "score_before": before,
            "score_after": after,
            "delta": delta,
            "retry_type": pair.get("retry_type", ""),
            "retry_triggered": pair.get("retry_triggered", False),
        })

    mean_delta = round(statistics.mean(deltas), 2) if deltas else 0.0
    return {
        "metric": "retry_score_delta",
        "mean_delta": mean_delta,
        "improved": improved,
        "degraded": degraded,
        "unchanged": unchanged,
        "pairs": pair_details,
    }


# ---------------------------------------------------------------------------
# Aggregate Report
# ---------------------------------------------------------------------------

def compute_all_metrics(
    runs: list[dict[str, Any]],
    annotated_cases: list[dict[str, Any]],
    latencies_s: list[float],
    before_after_pairs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compute all 7 metrics and return an aggregate report.

    Args:
        runs: Pipeline run results.
        annotated_cases: Annotated test cases.
        latencies_s: Per-run e2e latency in seconds.
        before_after_pairs: Optional retry score pairs.

    Returns:
        Full benchmark report dict.
    """
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {},
        "quality": {},
        "efficiency": {},
        "reliability": {},
    }

    # Quality metrics
    report["quality"]["top1_accuracy"] = compute_top1_accuracy(runs, annotated_cases)
    report["quality"]["source_recall"] = compute_source_recall(runs, annotated_cases)
    # Claim grounding: average across all reports
    cg_values = []
    for run in runs:
        cg = compute_claim_grounding_rate(run.get("report", ""))
        cg_values.append(cg["value"])
    report["quality"]["claim_grounding_rate"] = {
        "metric": "claim_grounding_rate",
        "value": round(statistics.mean(cg_values), 3) if cg_values else 0.0,
        "per_report": cg_values,
    }
    report["quality"]["conflict_detection"] = compute_conflict_detection_rate(
        runs, annotated_cases
    )

    # Efficiency
    report["efficiency"]["latency"] = compute_latency_stats(latencies_s)

    # Reliability
    report["reliability"]["success_rate"] = compute_success_rate(runs)
    report["reliability"]["retry_effectiveness"] = compute_retry_effectiveness(
        before_after_pairs or []
    )

    # Summary rollup
    q = report["quality"]
    report["summary"] = {
        "top1_accuracy": q["top1_accuracy"]["value"],
        "source_recall": q["source_recall"]["value"],
        "claim_grounding_rate": q["claim_grounding_rate"]["value"],
        "conflict_detection_rate": q["conflict_detection"]["value"],
        "latency_p50_s": report["efficiency"]["latency"]["p50"],
        "latency_p95_s": report["efficiency"]["latency"]["p95"],
        "success_rate": report["reliability"]["success_rate"]["value"],
        "retry_mean_delta": report["reliability"]["retry_effectiveness"]["mean_delta"],
    }

    return report


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_benchmark(report: dict[str, Any], runs_dir: Path, label: str = "") -> Path:
    """Save a benchmark report to a timestamped JSON file.

    Args:
        report: Full benchmark report from compute_all_metrics().
        runs_dir: Directory to save to (e.g., benchmarks/runs/).
        label: Optional label to insert in filename (e.g., "-batch01").

    Returns:
        Path to the saved file.
    """
    runs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = runs_dir / f"benchmark{label}-{ts}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_benchmarks(runs_dir: Path) -> list[dict[str, Any]]:
    """Load all benchmark reports from the runs directory, sorted by time.

    Args:
        runs_dir: Directory containing benchmark JSON files.

    Returns:
        List of benchmark reports, oldest first.
    """
    reports = []
    for f in sorted(runs_dir.glob("benchmark-*.json")):
        try:
            reports.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return reports


def merge_batches(runs_dir: Path, annotated_cases_path: Path | None = None) -> dict[str, Any]:
    """Merge batch benchmark results into a single aggregate report.

    Scans for benchmark-batch*.json files, combines all runs, and
    recomputes metrics across all cases.

    Args:
        runs_dir: Directory containing batch benchmark JSON files.
        annotated_cases_path: Path to annotated cases JSON (for metrics).

    Returns:
        Full benchmark report across all batches.
    """
    import json as json_mod

    batch_files = sorted(runs_dir.glob("benchmark-batch*-*.json"))
    if not batch_files:
        return {"status": "no_batches", "message": "No batch files found."}

    # Load annotated cases if path provided
    annotated_cases = []
    if annotated_cases_path and annotated_cases_path.exists():
        annotated_cases = json_mod.loads(annotated_cases_path.read_text(encoding="utf-8"))

    # Merge runs from all batches
    all_runs: list[dict[str, Any]] = []
    all_latencies: list[float] = []
    all_retry_pairs: list[dict[str, Any]] = []
    batch_summaries: list[dict[str, Any]] = []

    for bf in batch_files:
        batch_data = json_mod.loads(bf.read_text(encoding="utf-8"))
        batch_summaries.append({
            "file": bf.name,
            "timestamp": batch_data.get("timestamp", ""),
            "cases_ran": batch_data.get("reliability", {}).get("success_rate", {}).get("total", 0),
        })
        # The batch files don't store raw runs, only computed metrics.
        # We need to reconstruct from existing batch data.

    # Since raw runs aren't stored in batch files (only metrics), read from
    # full benchmark files or state snapshots if available.
    full_files = sorted(runs_dir.glob("benchmark-????????-??????.json"))
    full_files = [f for f in full_files if "batch" not in f.name]

    if full_files:
        # Use the latest full-file report as the source for merging
        latest = json_mod.loads(full_files[-1].read_text(encoding="utf-8"))
        return {
            "status": "merged_from_full",
            "timestamp": latest.get("timestamp", ""),
            "summary": latest.get("summary", {}),
            "batches_merged": len(batch_files),
            "batch_list": batch_summaries,
        }

    return {
        "status": "merged",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "batches_merged": len(batch_files),
        "batch_list": batch_summaries,
        "note": "Raw runs not stored in batch files. Re-run with full pipeline for aggregate metrics.",
    }


def trend_report(runs_dir: Path) -> dict[str, Any]:
    """Generate a trend comparison of the two most recent benchmarks.

    Args:
        runs_dir: Directory containing benchmark JSON files.

    Returns:
        Dict with previous, current, and deltas for each metric.
    """
    reports = load_benchmarks(runs_dir)
    if len(reports) < 2:
        return {"status": "insufficient_data", "count": len(reports)}

    prev = reports[-2]["summary"]
    curr = reports[-1]["summary"]
    deltas = {}
    for key in curr:
        if key in prev and isinstance(curr[key], (int, float)) and isinstance(prev[key], (int, float)):
            deltas[key] = round(curr[key] - prev[key], 3)

    return {
        "status": "ok",
        "previous_timestamp": reports[-2]["timestamp"],
        "current_timestamp": reports[-1]["timestamp"],
        "previous": prev,
        "current": curr,
        "deltas": deltas,
    }
