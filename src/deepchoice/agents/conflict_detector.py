import numpy as np
from ..utils.llm import call_model
from ..utils.views import print_agent_output
from ..utils.embedding import get_embedding_model


ARBITRATION_PROMPT = """You are an impartial technical arbitrator. Two sources make claims about the same topic but may disagree.

## Topic
{topic}

## Source A (score: {score_a}/10, authority: {authority_a}, evidence: {evidence_a})
Claim: {claim_a}

## Source B (score: {score_b}/10, authority: {authority_b}, evidence: {evidence_b})
Claim: {claim_b}

## Rules
1. If scores differ by >=2.5 points, the higher-scored source is more likely correct
2. If both have code/benchmark evidence, both may be partially right (different contexts)
3. If neither has strong evidence, declare "insufficient_data"
4. Your reasoning MUST cite the score difference or evidence type difference

Return ONLY a JSON object:
{{
  "resolution": "A_correct|B_correct|both_partial|insufficient_data",
  "confidence": "high|medium|low",
  "reasoning": "Specific reason citing score/evidence difference",
  "key_factor": "The single most decisive factor"
}}"""

NEGATION_WORDS = {
    # Explicit negation
    "not", "no", "never", "fail", "worse", "slow", "bad", "broken", "cannot",
    "doesn't", "don't", "isn't", "won't", "without", "lack", "lacks", "missing",
    # Implicit comparison / contrast markers
    "better than", "outperforms", "superior", "inferior", "however",
    "but", "although", "unlike", "versus", "vs", "contrary", "disagree",
    "instead", "rather than", "prefer", "drawback", "downside",
}


def find_contradictions(source_scores: list[dict], threshold: float = 0.6) -> list[dict]:
    model = get_embedding_model()
    high_score_sources = [s for s in source_scores if s["total_score"] >= 5.0]
    if len(high_score_sources) < 2:
        return []

    # Batch-encode all titles at once instead of per-pair in the inner loop
    titles = [s.get("title", "") for s in high_score_sources]
    embeddings = model.encode(titles)  # shape: (n, dim)

    # Pre-compute norms for cosine similarity
    norms = np.linalg.norm(embeddings, axis=1)

    pairs = []
    for i in range(len(high_score_sources)):
        for j in range(i + 1, len(high_score_sources)):
            title_a = titles[i]
            title_b = titles[j]
            if not title_a or not title_b:
                continue

            sim = float(np.dot(embeddings[i], embeddings[j]) / (norms[i] * norms[j]))

            if sim >= threshold:
                neg_a = any(w in title_a.lower() for w in NEGATION_WORDS)
                neg_b = any(w in title_b.lower() for w in NEGATION_WORDS)
                if neg_a != neg_b:
                    pairs.append({
                        "source_a": high_score_sources[i],
                        "source_b": high_score_sources[j],
                        "similarity": round(sim, 3),
                    })

    return pairs


class ConflictDetectorAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        source_scores = research_state.get("source_scores", [])
        print_agent_output(
            f"Detecting conflicts among {len(source_scores)} sources",
            agent="CONFLICT_DETECTOR",
        )

        pairs = find_contradictions(source_scores)
        if not pairs:
            return {
                "conflicts": [],
                "quality_signals": [{"agent": "conflict_detector", "conflicts_found": 0, "resolved_count": 0}],
            }

        def _make_prompt(a: dict, b: dict) -> list[dict]:
            return [{
                "role": "user",
                "content": ARBITRATION_PROMPT.format(
                    topic=research_state["task"]["query"],
                    score_a=a["total_score"],
                    authority_a=a["scores"]["authority"],
                    evidence_a=a["evidence_type"],
                    claim_a=a.get("title", ""),
                    score_b=b["total_score"],
                    authority_b=b["scores"]["authority"],
                    evidence_b=b["evidence_type"],
                    claim_b=b.get("title", ""),
                ),
            }]

        def _build_conflict(pair: dict, result: dict) -> dict:
            return {
                "claim_a": pair["source_a"].get("title", ""),
                "claim_b": pair["source_b"].get("title", ""),
                "source_a": {"url": pair["source_a"]["url"], "score": pair["source_a"]["total_score"]},
                "source_b": {"url": pair["source_b"]["url"], "score": pair["source_b"]["total_score"]},
                "similarity": pair["similarity"],
                "resolution": result.get("resolution", "insufficient_data"),
                "confidence": result.get("confidence", "low"),
                "reasoning": result.get("reasoning", ""),
                "key_factor": result.get("key_factor", ""),
                "arbiter_model": "flash",
            }

        # Stage 1: Flash arbitration for all pairs
        conflicts = []
        low_confidence_pairs: list[dict] = []

        for pair in pairs:
            try:
                result = await call_model(
                    _make_prompt(pair["source_a"], pair["source_b"]),
                    model="deepseek-v4-flash",
                    response_format="json",
                )
                conflict = _build_conflict(pair, result)
                conflicts.append(conflict)
                if conflict["confidence"] == "low":
                    low_confidence_pairs.append(pair)
            except Exception as e:
                print_agent_output(f"Flash arbitration failed: {e}", agent="CONFLICT_DETECTOR")

        # Stage 2: Pro re-arbitration for the most ambiguous low-confidence pair
        if low_confidence_pairs:
            # Pick the pair with the smallest score gap (most ambiguous)
            best = min(low_confidence_pairs, key=lambda p: abs(
                p["source_a"]["total_score"] - p["source_b"]["total_score"]
            ))
            score_gap = abs(best["source_a"]["total_score"] - best["source_b"]["total_score"])
            print_agent_output(
                f"Pro re-arbitration: 1 of {len(low_confidence_pairs)} low-confidence pairs "
                f"(score gap={score_gap:.1f})",
                agent="CONFLICT_DETECTOR",
            )
            try:
                pro_result = await call_model(
                    _make_prompt(best["source_a"], best["source_b"]),
                    model="deepseek-v4-pro",
                    response_format="json",
                    timeout=300.0,
                )
                # Replace the corresponding flash result in conflicts list
                pro_conflict = _build_conflict(best, pro_result)
                pro_conflict["arbiter_model"] = "pro"
                for i, c in enumerate(conflicts):
                    if (c["source_a"]["url"] == pro_conflict["source_a"]["url"] and
                            c["source_b"]["url"] == pro_conflict["source_b"]["url"]):
                        conflicts[i] = pro_conflict
                        break
            except Exception as e:
                print_agent_output(f"Pro arbitration failed, keeping flash result: {e}",
                                  agent="CONFLICT_DETECTOR")

        resolved_count = sum(
            1 for c in conflicts
            if c.get("resolution") not in ("insufficient_data", None)
        )
        return {
            "conflicts": conflicts,
            "quality_signals": [{
                "agent": "conflict_detector",
                "conflicts_found": len(conflicts),
                "resolved_count": resolved_count,
                "unresolved_count": len(conflicts) - resolved_count,
            }],
        }
