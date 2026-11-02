"""Post-synthesis/post-review structural strength guard.

The self-reviewer can revise field text or withdraw a decision, but its
correction contract cannot change a ranking order. Claim-support flags therefore
need a deterministic structural response:

- a `recommended` decision with winner-owned/secondary-only decisive support is
  downgraded to a conditional decision (or an insufficient-evidence hold when
  there are not two options to branch on);
- a conditional decision whose top-ranked option is dominated by its own/
  secondary material keeps its branches but loses the "supported default"
  framing.

The guard never invents evidence or changes candidate facts. It only reduces the
strength of a ranking that the claim-support ledger says is not supported.
"""
from __future__ import annotations

import copy

from .claim_support import claim_support_flags, decisive_claim_support

_ZH_MARKER = "证据强度校准"
_EN_MARKER = "evidence-strength guard"


def _is_zh(lang: str, rec: dict) -> bool:
    if lang == "zh":
        return True
    if lang == "en":
        return False
    text = str((rec or {}).get("recommendation") or "")
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _append_note(text: str, note: str, marker: str) -> str:
    value = str(text or "").strip()
    if marker in value:
        return value
    return f"{value} {note}".strip()


def apply_claim_support_guard(rec: dict, *, lang: str = "") -> tuple[dict, list[str]]:
    """Return (adjusted recommendation, applied guard actions).

    Idempotent: a recommendation already carrying the guard marker is not
    annotated again.
    """
    rec = rec or {}
    flags = claim_support_flags(rec)
    if not flags:
        return rec, []
    adjusted = copy.deepcopy(rec)
    status = str(adjusted.get("decision_status") or "")
    zh = _is_zh(lang, adjusted)
    marker = _ZH_MARKER if zh else _EN_MARKER
    if marker in str(adjusted.get("recommendation") or ""):
        return adjusted, []
    actions: list[str] = []

    recommended_flags = [flag for flag in flags if flag.startswith("recommended_")]
    if status == "recommended" and recommended_flags:
        ranked = adjusted.get("ranked_options") or []
        if len(ranked) >= 2:
            adjusted["decision_status"] = "conditional"
            note = (
                "（证据强度校准：现有材料不足以支持唯一推荐；以下排序仅为条件性、"
                "待验证比较，不构成唯一选型结论。）"
                if zh else
                " (Evidence-strength guard: the material does not support a single "
                "recommendation; the following is a conditional, unverified comparison, "
                "not a unique selection conclusion.)"
            )
            actions.append("recommended_to_conditional")
        else:
            adjusted["decision_status"] = "insufficient_evidence"
            note = (
                "（证据强度校准：现有材料不足以支持唯一推荐，且缺少可分支比较；"
                "以下为待补证据的 hold。）"
                if zh else
                " (Evidence-strength guard: the material does not support a unique "
                "recommendation and lacks a two-branch comparison; this is a hold pending "
                "more evidence.)"
            )
            actions.append("recommended_to_insufficient_evidence")
        adjusted["winner"] = ""
        adjusted["recommendation"] = _append_note(
            adjusted.get("recommendation"), note, marker)
        adjusted["decision_guard_actions"] = actions
        return adjusted, actions

    conditional_flags = [
        flag for flag in flags
        if flag in {"conditional_top_option_owner_dominates",
                    "conditional_top_option_secondary_dominant"}
    ]
    if status == "conditional" and conditional_flags:
        note = (
            "（证据强度校准：默认/排序靠前分支的决定性比较主要依赖其自有材料或二手来源，"
            "缺少独立的非厂商对照；以下排序仅作为待验证假设，不作为已证实的产品优劣结论。）"
            if zh else
            " (Evidence-strength guard: the decisive comparison for the default/top-ranked "
            "branch rests mainly on its own or secondary material, without an independent "
            "non-vendor counter-check; the ordering is an unverified hypothesis, not an "
            "established product comparison.)"
        )
        adjusted["recommendation"] = _append_note(
            adjusted.get("recommendation"), note, marker)
        adjusted["decision_guard_actions"] = [
            "conditional_top_option_strength_caveat"]
        return adjusted, ["conditional_top_option_strength_caveat"]

    # R7b (2026-11-02): a conditional conclusion with no primary (official or
    # independent) support anywhere is an evidence-gap judgement, not an ordering.
    # The owner/secondary caveat above covers the dominance cases; this covers the
    # remaining honest gap so the served text cannot read as a supported ranking.
    if status == "conditional" and "conditional_no_primary" in flags:
        note = (
            "（证据强度校准：该条件结论没有任何一手（官方或独立）来源支撑，属于证据缺口型判断；"
            "以下分支只按现有材料给出，不构成已证实的优劣排序。）"
            if zh else
            " (Evidence-strength guard: this conditional conclusion has no primary "
            "(official or independent) source support; it is an evidence-gap judgement. "
            "The branches below follow the available material only and are not an "
            "established product comparison.)"
        )
        adjusted["recommendation"] = _append_note(
            adjusted.get("recommendation"), note, marker)
        adjusted["decision_guard_actions"] = ["conditional_no_primary_caveat"]
        return adjusted, ["conditional_no_primary_caveat"]

    return rec, []
