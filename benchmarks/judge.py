"""LLM judge for the conflict-detection metric.

`compute_conflict_detection_rate_llm` (metrics.py) stays pure (no I/O) and takes
the judge as an injected callable. This module owns the concrete LLM judge so the
two benchmark scripts (run_baseline, merge_checkpoints) import it from one shared
place instead of coupling to each other.
"""

from deepchoice.utils.llm import call_model

CONFLICT_JUDGE_PROMPT = """You are evaluating a conflict detection system for a tech comparison research tool.

Detected conflicts (from the pipeline):
{conflicts_text}

Known contradiction topic: "{topic}"

Does ANY of the detected conflicts involve the same subject matter as this topic?
Answer "yes" if the detected conflict and the known topic are about the same technology,
performance characteristic, design trade-off, or usage scenario — even if they use different wording.
Only answer "no" if the detected conflicts are clearly about completely different subjects.
Answer ONLY "yes" or "no"."""


async def _judge_conflict_match(detected_conflicts: list[dict], topic: str) -> bool:
    """Ask flash model if any detected conflict relates to the topic."""
    if not detected_conflicts:
        return False
    # Summarize conflicts: claim_a vs claim_b + resolution + reasoning
    parts = []
    for c in detected_conflicts[:5]:  # Cap at 5 to keep prompt small
        parts.append(
            f"- {c.get('claim_a', '')[:80]} vs {c.get('claim_b', '')[:80]}\n"
            f"  difference={c.get('difference_explanation', '')[:160]}\n"
            f"  resolution={c.get('resolution', '')} reasoning={c.get('reasoning', '')[:120]}"
        )
    conflicts_text = "\n".join(parts)
    try:
        result = await call_model(
            [{"role": "user", "content": CONFLICT_JUDGE_PROMPT.format(
                conflicts_text=conflicts_text, topic=topic)}],
            model="deepseek-flash", tag="conflict_judge",
            response_format="text",
        )
        return "yes" in str(result).strip().lower()
    except Exception as exc:
        print(f"[WARN] conflict judge failed for topic {topic!r}: {exc}")
        return False
