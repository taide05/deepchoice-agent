"""One minimal decision contract shared by synthesis, review and renderers.

Statuses:
- recommended: one candidate winner with a decisive basis and applicable premise.
- conditional: no single winner; branches/conditions are in `recommendation`.
- insufficient_evidence: no winner; unresolved_questions state the decisive gap
  and what evidence would change the conclusion.
- invalid: malformed/failed decision output; never silently becomes a hold.

Legacy saved records without `decision_status` are displayed from their existing
winner field only. Missing winner is not inferred from ranked_options.
"""
from __future__ import annotations

RECOMMENDED = "recommended"
CONDITIONAL = "conditional"
INSUFFICIENT = "insufficient_evidence"
INVALID = "invalid"
VALID_MODEL_STATUSES = {RECOMMENDED, CONDITIONAL, INSUFFICIENT}
_SENTINELS = {"", "context_dependent", "none", "null", "unknown", "insufficient_evidence"}


def _nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _winner(rec: dict) -> str:
    value = rec.get("winner")
    return value.strip() if isinstance(value, str) else ""


def _candidate_winner(rec: dict) -> str:
    winner = _winner(rec)
    return "" if winner.casefold() in _SENTINELS else winner


def decision_view(rec: dict) -> dict:
    """Read a saved recommendation without mutating or filling anything."""
    rec = rec or {}
    status = rec.get("decision_status")
    winner = _winner(rec)
    if status in VALID_MODEL_STATUSES:
        return {
            "status": status,
            "winner": _candidate_winner(rec) if status == RECOMMENDED else "",
            "legacy": False,
            "invalid": False,
        }
    if status == INVALID:
        return {"status": INVALID, "winner": "", "legacy": False, "invalid": True}
    # Historical record: preserve only an already-present winner. Never derive a
    # winner from ranked_options or any other field.
    if winner.casefold() == "context_dependent":
        return {"status": CONDITIONAL, "winner": "", "legacy": True, "invalid": False}
    if _candidate_winner(rec):
        return {"status": RECOMMENDED, "winner": _candidate_winner(rec),
                "legacy": True, "invalid": False}
    return {"status": INVALID, "winner": "", "legacy": True, "invalid": True}


def normalize_decision(result: dict) -> dict:
    """Validate a new model decision without selecting a candidate for it."""
    result = result if isinstance(result, dict) else {}
    status = result.get("decision_status")
    status = status.strip().lower() if isinstance(status, str) else ""
    winner = _candidate_winner(result)
    recommendation = result.get("recommendation")
    rationale = result.get("winner_rationale")
    gaps = result.get("unresolved_questions")

    valid = False
    if status == RECOMMENDED:
        valid = bool(winner and _nonempty(recommendation) and _nonempty(rationale))
    elif status == CONDITIONAL:
        valid = (not winner and _nonempty(recommendation)
                 and len(result.get("ranked_options") or []) >= 2)
    elif status == INSUFFICIENT:
        valid = (not winner and isinstance(gaps, list)
                 and any(_nonempty(g) for g in gaps)
                 and (_nonempty(rationale) or _nonempty(recommendation)))

    if not valid:
        result["decision_status"] = INVALID
        result["winner"] = ""
        result.setdefault("decision_validation_error",
                          "invalid decision_status or missing required decision fields")
        return result
    result["decision_status"] = status
    result["winner"] = winner if status == RECOMMENDED else ""
    return result


def withdraw_decision(recommendation: dict, reason: str, language: str = "zh") -> dict:
    """Withdraw an unsupported recommendation into an evidence-insufficient hold."""
    rec = recommendation if isinstance(recommendation, dict) else {}
    reason = (reason or "").strip() or "self-review found the recommendation unsupported"
    rec["decision_status"] = INSUFFICIENT
    rec["winner"] = ""
    rec["winner_rationale"] = (
        f"推荐已撤回：{reason}" if language == "zh" else
        f"Recommendation withdrawn: {reason}")
    rec["recommendation"] = (
        "证据不足以支持唯一推荐；暂缓选型。需先补齐决定性证据再判断。"
        if language == "zh" else
        "Evidence is insufficient for a recommendation; hold the selection until "
        "the decisive evidence is obtained.")
    gaps = rec.get("unresolved_questions")
    if not isinstance(gaps, list):
        gaps = []
    if reason not in gaps:
        gaps.append(reason)
    rec["unresolved_questions"] = gaps
    return rec
