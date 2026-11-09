"""Keep the confidence label and its rationale text from contradicting each other.

The final-200 content review (2026-11-02) exposed two presentation defects in the
stored reports:

1. 5/200 reports named a different final level in ``confidence_rationale`` than
   the authoritative ``confidence`` field (e.g. label ``low``, prose
   "最终置信级别：medium"). The field is what the report header and every consumer
   show; the prose claim must agree with it.
2. 173/200 reports carried the internal self-review note
   "（自审调整：…）" in user-facing rationale text. The review treated it as an
   internal process note leaking into the report; the adjusted level is already
   reported in the structured ``confidence`` field, so the note is removed from
   user-facing prose.

Deterministic only: this module rewrites explicit "final level" claims to the
authoritative level and strips the known process note. It never invents a level,
never changes the substance of the reasoning, and never touches a side claim such
as "不高于 medium" (a ceiling is not a final-level claim).
"""
from __future__ import annotations

import re

_LEVELS = ("low", "medium", "high")
_ZH_LEVEL = {"low": "低置信", "medium": "中置信", "high": "高置信"}

# Only explicit final-level claims are rewritten. "不高于 medium" is a ceiling,
# not a final level, and must stay as written.
_CLAIM = re.compile(
    r"(最终置信(?:级别|度)?\s*[：:]\s*"
    r"|最终置信度为\s*"
    r"|评审层最终置信度为?\s*"
    r"|置信度(?:定为|为)\s*"
    r"|最终定级为\s*"
    r"|定级为\s*"
    r"|故定为\s*"
    r"|综合定为\s*"
    r"|结论定为\s*"
    r"|最终取为\s*"
    r"|判为\s*)"
    r"(low|medium|high|低置信度?|中置信度?|高置信度?)",
    re.IGNORECASE)

_SELF_REVIEW_NOTE_ZH = re.compile(r"[ \t]*（自审调整：[^）]*）")
_SELF_REVIEW_NOTE_EN = re.compile(r"[ \t]*\(Self-review adjustment:[^)]*\)",
                                  re.IGNORECASE)

# G1 review (F200-186): the rationale said "结论本身证据充分（high）" while the
# authoritative label was medium — not a "final level" clause, so the first regex
# missed it. A parenthetical level attached to confidence/evidence wording is also
# a level claim; a bare "（high）" without that context (e.g. a quoted source's
# priority) is left alone.
_PAREN_LEVEL = re.compile(
    r"((?:置信|评级|定级|证据|充分|结论)[^。；;!?！？\n]{0,24})"
    r"[（(](low|medium|high)[）)]",
    re.IGNORECASE)


def normalize_confidence(value) -> str | None:
    """Map a confidence value to low/medium/high, or None if it is not one."""
    if isinstance(value, bool) or not isinstance(value, str):
        return None
    level = value.strip().lower()
    if level in _LEVELS:
        return level
    return {"低": "low", "中": "medium", "高": "high",
            "低置信": "low", "中置信": "medium", "高置信": "high"}.get(level)


def _replacement_word(matched: str, level: str) -> str:
    return _ZH_LEVEL[level] if "置信" in matched else level


def align_confidence_rationale(text, confidence) -> str:
    """Make explicit final-level claims in ``text`` agree with ``confidence``.

    Also removes the known internal self-review note (the level it describes is
    already carried by the structured field). Returns the input unchanged when
    either side is missing/not a level.
    """
    level = normalize_confidence(confidence)
    if level is None or not text:
        return text if isinstance(text, str) else str(text or "")
    cleaned = _SELF_REVIEW_NOTE_EN.sub("", _SELF_REVIEW_NOTE_ZH.sub("", str(text)))

    def _sub(match: re.Match) -> str:
        return match.group(1) + _replacement_word(match.group(2), level)

    def _paren_sub(match: re.Match) -> str:
        return f"{match.group(1)}（{level}）"

    cleaned = _PAREN_LEVEL.sub(_paren_sub, cleaned)
    return _CLAIM.sub(_sub, cleaned).rstrip()
