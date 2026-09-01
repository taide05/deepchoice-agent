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

    # Pattern 1: Find "Recommendation:" section, then locate tech_a or tech_b nearby.
    # All report formats: "**Recommendation:** <context>, <TechName> is/choose/adopt..."
    m = re.search(
        r'(?im)(?:\*\*)?(?:recommendation|推荐)(?:\*\*)?\s*:\s*',
        report,
    )
    if m:
        after = report[m.end():m.end() + 250].lower()
        # Search for tech_a or tech_b as whole words in the recommendation text
        for tech in (tech_a, tech_b):
            if tech and re.search(r'\b' + re.escape(tech.lower()) + r'\b', after):
                result = _clean_tech_name(tech)
                if result:
                    return result

    # Pattern 1.5: "**Winner: X**" bold line (new format from fixed synthesizer).
    # Parenthesized suffixes like "Firebase Cloud Messaging (FCM)" are allowed;
    # the tech-name char class includes "/" so "Swagger/OpenAPI" matches
    # (repo-path winners were already sanitized by _validate_winner).
    m = re.search(
        r'(?im)\*\*Winner:\s*([A-Za-z0-9+\-_.\/]+(?:\s[A-Za-z0-9+\-_.\/]+){0,2})(?:\s*\([^)]*\))?\*\*',
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
            r'(?i)(?:start with|verdict|recommendation|recommended\b|recommend\b|推荐|pick|choose)\s*:?\s*'
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
        acceptable = [w.lower() for w in case.get("acceptable_winners", [])]
        if expected == "context_dependent":
            # Context-dependent cases are scored separately (see notes)
            continue

        report = run.get("report", "")
        predicted = extract_top_recommendation(
            report,
            tech_a=case.get("tech_a", ""),
            tech_b=case.get("tech_b", ""),
        )
        if acceptable:
            # Open-scenario case: any acceptable winner counts
            is_correct = bool(predicted) and any(w in predicted for w in acceptable)
            expected_label = "/".join(acceptable)
        else:
            is_correct = predicted and expected in predicted
            expected_label = expected
        if is_correct:
            correct += 1
        total += 1
        details.append({
            "case_id": case_id,
            "expected": expected_label,
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


def compute_source_recall_by_source(
    runs: list[dict[str, Any]],
    annotated_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute source recall split by retriever source type.

    Groups must_find_sources by their 'type' field (official_doc, github_repo,
    academic, community, package_registry) and computes per-type recall.
    """
    case_map = {c["id"]: c for c in annotated_cases}
    per_source: dict[str, dict] = {}

    for run in runs:
        case_id = run.get("case_id", "")
        case = case_map.get(case_id)
        if not case:
            continue

        must_find = case.get("must_find_sources", [])
        if not must_find:
            continue

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

        for mf in must_find:
            src_type = mf.get("type", "unknown")
            if src_type not in per_source:
                per_source[src_type] = {"total": 0, "found": 0}
            per_source[src_type]["total"] += 1
            pattern = mf["pattern"]
            if any(_url_matches_pattern(url, pattern) for url in retrieved_urls):
                per_source[src_type]["found"] += 1

    result = {"metric": "source_recall_by_source"}
    for src_type, counts in sorted(per_source.items()):
        recall = counts["found"] / counts["total"] if counts["total"] > 0 else 0.0
        result[src_type] = {
            "recall": round(recall, 3),
            "found": counts["found"],
            "total": counts["total"],
        }
    return result


def compute_source_health(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-source availability of retrieval stages (status success/failed).

    Detects quietly-degraded benchmark runs: if a retriever source failed in
    the majority of runs, source_recall is not comparable to a healthy run and
    must be flagged instead of silently scored.
    """
    per_source: dict[str, dict[str, Any]] = {}
    for run in runs:
        for sr in run.get("search_results", []):
            src = sr.get("source", "unknown")
            if src not in per_source:
                per_source[src] = {"total": 0, "failed": 0, "success": 0}
            per_source[src]["total"] += 1
            if sr.get("status") == "failed":
                per_source[src]["failed"] += 1
            else:
                per_source[src]["success"] += 1

    degraded_sources: list[str] = []
    for src, st in sorted(per_source.items()):
        rate = st["failed"] / st["total"] if st["total"] else 0.0
        st["failed_rate"] = round(rate, 3)
        if rate >= 0.5 and st["total"] >= 5:
            degraded_sources.append(src)
        # Partial losses are still visible in the per-source rate table.

    return {
        "metric": "source_health",
        "sources": per_source,
        "degraded_sources": degraded_sources,
        "degraded": bool(degraded_sources),
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
# Quality Metric 3b: Claim Citation Rate (precise [Source: title] coverage)
# ---------------------------------------------------------------------------

def _extract_source_titles(claim: str) -> list[str]:
    """Extract all [Source: title] citation titles from a claim, handling
    multiple sources per bracket (comma/semicolon-separated) and nested
    brackets in titles (e.g. [Source: ... [2026] ...])."""
    parts = re.split(r'Source:\s*', claim, flags=re.IGNORECASE)[1:]
    titles = []
    for part in parts:
        t = re.split(r'[,;\[\]]', part)[0].strip()
        if t:
            titles.append(t)
    return titles


def _normalize_title(s: str) -> str:
    """Lowercase + alphanumerics only — 'FastAPI Docs' and 'FastAPI - Docs'
    both normalize to 'fastapidocs'."""
    return "".join(c for c in s.lower() if c.isalnum())


def _split_sentences(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r'(?<=[.!?])\s+', text)
    merged: list[str] = []
    for p in parts:
        # Do not split inside abbreviations ("vs.", "etc.", "e.g.", "i.e.")
        # — they appear inside [Source: X vs. Y] titles and must stay whole.
        if merged and re.search(r'\b(vs|etc|e\.g|i\.e)\.$', merged[-1], re.IGNORECASE):
            merged[-1] += ' ' + p
        else:
            merged.append(p)
    return [s.strip() for s in merged if s.strip()]


def _extract_claims(fr: dict) -> list[str]:
    """Flatten the factual-claim fields of a final_recommendation into a
    claim list, matching the fields the synthesizer is told to cite."""
    claims = []
    claims.extend(_split_sentences(fr.get("recommendation", "")))
    if fr.get("winner_rationale"):
        claims.append(fr["winner_rationale"])
    for opt in fr.get("ranked_options", []):
        for field in ("rationale", "key_strength", "key_weakness"):
            if opt.get(field):
                claims.append(opt[field])
    for to in fr.get("trade_offs", []):
        for field in ("finding", "impact"):
            if to.get(field):
                claims.append(to[field])
    claims.extend(_split_sentences(fr.get("evidence_summary", "")))
    if fr.get("scene_fit_note"):
        claims.append(fr["scene_fit_note"])
    return claims


def _collect_true_titles(run: dict) -> set[str]:
    """All normalized source titles — preferentially the evidence-chain titles
    the synthesizer was shown (same set the citation sanitizer uses), falling
    back to search results when evidence_titles is absent."""
    titles = set()
    for t in run.get("evidence_titles", []) or []:
        if t:
            titles.add(_normalize_title(t))
    if titles:
        return titles
    for sr in run.get("search_results", []):
        for result in sr.get("results", []):
            t = result.get("title", "")
            if t:
                titles.add(_normalize_title(t))
    return titles


def _is_real_title(norm: str, real_titles: set[str]) -> bool:
    """True if a normalized citation title is an exact or shortened (substring)
    form of a real source title — LLMs often cite a prefix of the true title
    (e.g. "What is LangGraph?" for "... 2026 Stateful Graph Guide")."""
    return any(norm in rt for rt in real_titles)


def compute_claim_citation_rate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Precise claim citation rate: fraction of factual claims carrying a
    [Source: title] whose title actually exists in the retrieved sources.

    Fabricated citations (title not in any retrieved source) are counted
    separately — they must be 0 for the rate to be credible.
    """
    total_claims = 0
    cited_claims = 0
    fabricated_citations = 0

    for run in runs:
        fr = run.get("final_recommendation") or {}
        true_titles = _collect_true_titles(run)
        for claim in _extract_claims(fr):
            total_claims += 1
            titles = _extract_source_titles(claim)
            real = [t for t in titles if _is_real_title(_normalize_title(t), true_titles)]
            fabricated_citations += len(titles) - len(real)
            if real:
                cited_claims += 1

    rate = cited_claims / total_claims if total_claims > 0 else 0.0
    return {
        "metric": "claim_citation_rate",
        "value": round(rate, 3),
        "total_claims": total_claims,
        "cited_claims": cited_claims,
        "fabricated_citations": fabricated_citations,
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
    total_resolved = 0
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

        detected_count = 0
        resolved_count = 0
        matched_topics = []
        missed_topics = []
        for kc in known:
            topic = kc["topic"].lower()
            topic_words = set(re.findall(r'\w+', topic))
            matched_conflicts = []
            for c in detected_conflicts:
                c_words = set(re.findall(r'\w+', str(c).lower()))
                # Require at least 2 keyword matches to count as detected
                if len(topic_words & c_words) >= 2:
                    matched_conflicts.append(c)
            if matched_conflicts:
                detected_count += 1
                matched_topics.append(kc["topic"])
                if any(isinstance(c, dict) and c.get("resolution") in RESOLVED_RESOLUTIONS
                       for c in matched_conflicts):
                    resolved_count += 1
            else:
                missed_topics.append(kc["topic"])

        total_known += len(known)
        total_detected += detected_count
        total_resolved += resolved_count
        details.append({
            "case_id": case_id,
            "known_count": len(known),
            "detected": detected_count,
            "resolved": resolved_count,
            "matched": matched_topics,
            "missed": missed_topics,
        })

    rate = total_detected / total_known if total_known > 0 else 0.0
    resolved_rate = total_resolved / total_known if total_known > 0 else 0.0
    return {
        "metric": "conflict_detection_rate",
        "value": round(rate, 3),
        "total_known": total_known,
        "total_detected": total_detected,
        "total_resolved": total_resolved,
        "resolved_rate": round(resolved_rate, 3),
        "per_case": details,
        "method": "keyword",
    }


RESOLVED_RESOLUTIONS = frozenset({"A_correct", "B_correct", "both_partial"})


async def compute_conflict_detection_rate_llm(
    runs: list[dict[str, Any]],
    annotated_cases: list[dict[str, Any]],
    judge_fn,
) -> dict[str, Any]:
    """LLM-enhanced conflict detection rate.

    Only counts conflicts with resolution A_correct/B_correct
    (excludes both_partial and insufficient_data as noise).
    Two-stage: keyword pre-match (fast), then LLM judge re-examines
    missed topics (accurate).

    Args:
        runs: Pipeline run results.
        annotated_cases: Annotated test cases.
        judge_fn: async callable(detected_conflicts, topic) -> bool.

    Returns:
        Dict with detection_rate, detected, total_known, per_case, method.
    """
    case_map = {c["id"]: c for c in annotated_cases}
    total_known = 0
    total_detected = 0
    kw_matched = 0
    llm_matched = 0
    details = []

    for run in runs:
        case_id = run.get("case_id", "")
        case = case_map.get(case_id)
        if not case:
            continue

        known = case.get("known_contradictions", [])
        if not known:
            continue

        # Only consider resolved (A_correct/B_correct) conflicts
        all_conflicts = run.get("conflicts", [])
        resolved_conflicts = [
            c for c in all_conflicts
            if c.get("resolution") in RESOLVED_RESOLUTIONS
        ]
        detected_text = " ".join(str(c) for c in resolved_conflicts).lower()

        detected_count = 0
        matched_topics = []
        still_missed = []
        llm_candidates = []

        for kc in known:
            topic = kc["topic"].lower()
            topic_words = set(re.findall(r'\w+', topic))
            detected_words = set(re.findall(r'\w+', detected_text))
            overlap = topic_words & detected_words

            if len(overlap) >= 2:
                detected_count += 1
                kw_matched += 1
                matched_topics.append({"topic": kc["topic"], "method": "keyword"})
            elif resolved_conflicts:
                llm_candidates.append(kc)
            else:
                still_missed.append(kc)

        # Stage 2: LLM re-evaluates keyword-missed topics
        for kc in llm_candidates:
            try:
                ok = await judge_fn(resolved_conflicts, kc["topic"])
                if ok:
                    detected_count += 1
                    llm_matched += 1
                    matched_topics.append({"topic": kc["topic"], "method": "llm"})
                else:
                    still_missed.append(kc)
            except Exception:
                still_missed.append(kc)

        total_known += len(known)
        total_detected += detected_count
        details.append({
            "case_id": case_id,
            "known_count": len(known),
            "detected": detected_count,
            "matched": matched_topics,
            "missed": [k["topic"] for k in still_missed],
        })

    rate = total_detected / total_known if total_known > 0 else 0.0
    return {
        "metric": "conflict_detection_rate",
        "value": round(rate, 3),
        "total_known": total_known,
        "total_detected": total_detected,
        "keyword_matched": kw_matched,
        "llm_matched": llm_matched,
        "per_case": details,
        "method": "keyword+llm",
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
        report = run.get("report", "")
        has_report = bool(report and len(report.strip()) > 100)

        if not has_error and has_report:
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

    Compares deterministic report-quality scores before and after retry for
    the same query. Requires pre-retry snapshots; when the eval pipeline does
    not collect them the result is flagged not_measured (never fabricated).

    Args:
        before_after_pairs: List of {case_id, score_before, score_after,
                            retry_triggered, retry_type}.

    Returns:
        Dict with mean_delta, improved_count, degraded_count, per_pair.
    """
    if not before_after_pairs:
        return {"metric": "retry_score_delta", "not_measured": True,
                "mean_delta": None,
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

_CITATION_TEXT_FIELDS = ("recommendation", "winner_rationale",
                         "evidence_summary", "scene_fit_note")
_CITATION_OPT_FIELDS = ("rationale", "key_strength", "key_weakness")
_CITATION_TRADEOFF_FIELDS = ("finding", "impact")


def compute_citation_breakdown(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-field inline [Source: title] citation counts across the final
    recommendation (post-sanitize). Identifies which fields qwen under-cites.

    Returns {"metric", "per_case": [{case_id, fields: {field: {citations, chars}}}]}
    """
    def _citations(text: str) -> int:
        return len(re.findall(r"\[Source:", text or ""))

    per_case: list[dict[str, Any]] = []
    for run in runs:
        fr = run.get("final_recommendation") or {}
        fields: dict[str, dict[str, Any]] = {}
        for f in _CITATION_TEXT_FIELDS:
            v = fr.get(f) or ""
            fields[f] = {"citations": _citations(v), "chars": len(v)}
        for i, opt in enumerate(fr.get("ranked_options") or []):
            for f in _CITATION_OPT_FIELDS:
                v = opt.get(f) or ""
                fields[f"ranked_options[{i}].{f}"] = {
                    "citations": _citations(v), "chars": len(v)}
        for i, to in enumerate(fr.get("trade_offs") or []):
            for f in _CITATION_TRADEOFF_FIELDS:
                v = to.get(f) or ""
                fields[f"trade_offs[{i}].{f}"] = {
                    "citations": _citations(v), "chars": len(v)}
        per_case.append({"case_id": run.get("case_id", ""), "fields": fields})
    return {"metric": "citation_breakdown", "per_case": per_case}


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
    report["quality"]["source_health"] = compute_source_health(runs)
    report["quality"]["citation_breakdown"] = compute_citation_breakdown(runs)
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
        "sources_degraded": q["source_health"]["degraded"],
        "degraded_sources": q["source_health"]["degraded_sources"],
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
