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

import re
import unicodedata

RECOMMENDED = "recommended"
CONDITIONAL = "conditional"
INSUFFICIENT = "insufficient_evidence"
INVALID = "invalid"
VALID_MODEL_STATUSES = {RECOMMENDED, CONDITIONAL, INSUFFICIENT}
_SENTINELS = {"", "context_dependent", "none", "null", "unknown", "insufficient_evidence"}
_CITATION_KEY = "citation_sources"

# A conditional model answer is sometimes emitted with a malformed ranked_options
# structure (null/non-list/duplicate/missing name) or with option labels carrying a
# version/tier suffix ("MySQL 8.0" for declared "MySQL"). Today that whole answer
# becomes `invalid`, which loses an actionable branch recommendation. This is a
# narrow recovery: only for a model-declared conditional answer whose recommendation
# text itself contains explicit branch markers and names at least two declared
# candidates. The recovered options are exactly the declared candidate names (never
# invented), and the recovery is flagged so it stays auditable.
_BRANCH_MARKERS = re.compile(
    r"(分支|默认|如果|若|当[^。；;\n]{0,24}时|则选|否则|条件式|"
    r"\bbranch(?:es)?\b|\bdefault\b|\bif\b[^.;\n]{0,40}\bthen\b|"
    r"\bwhen\b[^.;\n]{0,40}\bchoose\b|\bconditional\b)",
    re.IGNORECASE,
)


def _term_tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return [part for part in re.split(r"[^0-9a-z\u4e00-\u9fff+#.]+", normalized)
            if part]


def _contains_sequence(tokens: list[str], sequence: list[str]) -> bool:
    width = len(sequence)
    if not width:
        return False
    return any(tokens[i:i + width] == sequence
               for i in range(len(tokens) - width + 1))


def _declared_mentions(text: str, declared: dict[str, str]) -> list[tuple[int, str]]:
    """Declared candidates named in `text`, ordered by first token position."""
    tokens = _term_tokens(text)
    hits: list[tuple[int, str]] = []
    for key, display in declared.items():
        sequence = _term_tokens(display)
        if not _contains_sequence(tokens, sequence):
            continue
        # First position of the sequence in the token stream.
        position = None
        for index in range(len(tokens) - len(sequence) + 1):
            if tokens[index:index + len(sequence)] == sequence:
                position = index
                break
        hits.append((position if position is not None else 10 ** 6, display))
    hits.sort(key=lambda item: item[0])
    return hits


def _recover_conditional(result: dict, declared_candidates) -> dict | None:
    """Rebuild a conditional answer from its own branch text when options were malformed.

    Only runs for a model-declared conditional answer. Options are the declared
    candidate names that the recommendation/rationale itself names; nothing is
    inferred from fit scores or search counts.
    """
    recommendation = result.get("recommendation")
    rationale = result.get("winner_rationale")
    if not _nonempty(recommendation):
        return None
    if not _BRANCH_MARKERS.search(recommendation):
        return None
    declared = _declared_index(declared_candidates)
    if not declared:
        return None
    mentions = _declared_mentions(
        f"{recommendation} {rationale if isinstance(rationale, str) else ''}", declared)
    names: list[str] = []
    for _position, display in mentions:
        if display not in names:
            names.append(display)
    if len(names) < 2:
        return None
    options = [{
        "name": name,
        "rank": index + 1,
        "constraint_fit": "",
        "constraint_fit_reason": "",
        "rationale": "",
    } for index, name in enumerate(names)]
    result["decision_status"] = CONDITIONAL
    result["winner"] = ""
    result["ranked_options"] = options
    result.pop("decision_validation_error", None)
    result["decision_validation_recovered"] = (
        "conditional answer recovered: branch text names declared candidates "
        "while ranked_options was missing/malformed")
    return result


def _nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _winner(rec: dict) -> str:
    value = rec.get("winner")
    return value.strip() if isinstance(value, str) else ""


def _candidate_winner(rec: dict) -> str:
    winner = _winner(rec)
    return "" if winner.casefold() in _SENTINELS else winner


def _candidate_key(value: str) -> str:
    """Exact candidate identity: case/whitespace-insensitive, symbols preserved.

    NFKC + casefold + whitespace collapse treats spaced/cased forms as the same
    identity while preserving 'C++', 'C#', 'F#' and '.NET' as distinct names.
    No punctuation stripping and no substring matching: 'C' is not 'C++'.
    """
    if not isinstance(value, str):
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _declared_index(declared_candidates) -> dict[str, str] | None:
    if not declared_candidates:
        return None
    index: dict[str, str] = {}
    for item in declared_candidates:
        if not isinstance(item, str) or not item.strip():
            continue
        key = _candidate_key(item)
        if key:
            index.setdefault(key, item.strip())
    return index or None


def _valid_ranked_options(result: dict) -> tuple[bool, list[dict]]:
    """Validate ranked_options before any len/traversal/rendering.

    Missing means empty; null/number/string and entries that are null, non-object,
    empty-named or duplicate (case/whitespace-insensitive) are invalid. This is a
    structure check only and never selects a winner.
    """
    if "ranked_options" not in result:
        return True, []
    raw = result.get("ranked_options")
    if raw is None or not isinstance(raw, list):
        return False, []
    seen: set[str] = set()
    options: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            return False, []
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            return False, []
        key = _candidate_key(name)
        if not key or key in seen:
            return False, []
        seen.add(key)
        options.append(item)
    return True, options


def _invalid(result: dict, reason: str) -> dict:
    result["decision_status"] = INVALID
    result["winner"] = ""
    # Never leave a malformed option structure for a later consumer to traverse.
    result["ranked_options"] = []
    result["decision_validation_error"] = reason
    return result


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


def normalize_decision(result: dict, declared_candidates=None) -> dict:
    """Validate a new model decision without selecting a candidate for it.

    Structural validation happens first, so a malformed ranked_options value
    cannot reach len(), iteration or a renderer. With an explicit candidate list,
    a recommended winner and every conditional option must match a declared
    candidate identity exactly (case/whitespace-insensitive with symbols preserved;
    no substring). With no explicit list, the existing open-selection contract is
    retained.
    """
    result = result if isinstance(result, dict) else {}
    status = result.get("decision_status")
    status = status.strip().lower() if isinstance(status, str) else ""
    winner = _candidate_winner(result)
    recommendation = result.get("recommendation")
    rationale = result.get("winner_rationale")
    gaps = result.get("unresolved_questions")
    declared = _declared_index(declared_candidates)

    structured, options = _valid_ranked_options(result)
    if not structured:
        if status == CONDITIONAL:
            recovered = _recover_conditional(result, declared_candidates)
            if recovered is not None:
                return recovered
        return _invalid(result, "invalid ranked_options structure")
    option_keys = [_candidate_key(str(o.get("name") or "")) for o in options]

    valid = False
    error = "invalid decision_status or missing required decision fields"
    if status == RECOMMENDED:
        valid = bool(winner and _nonempty(recommendation) and _nonempty(rationale))
        if valid and declared is not None and _candidate_key(winner) not in declared:
            valid, error = False, "recommended winner is not a declared candidate"
    elif status == CONDITIONAL:
        valid = (not winner and _nonempty(recommendation) and len(options) >= 2)
        if valid and declared is not None:
            if any(key not in declared for key in option_keys):
                valid, error = False, "conditional option is not a declared candidate"
    elif status == INSUFFICIENT:
        valid = (not winner and isinstance(gaps, list)
                 and any(_nonempty(g) for g in gaps)
                 and (_nonempty(rationale) or _nonempty(recommendation)))

    if not valid:
        # A conditional model answer may still carry its full branch text; recover
        # only its declared options, never a winner. Other statuses stay invalid.
        if status == CONDITIONAL:
            recovered = _recover_conditional(result, declared_candidates)
            if recovered is not None:
                return recovered
        return _invalid(result, error)
    result.pop("decision_validation_error", None)
    result["decision_status"] = status
    result["winner"] = winner if status == RECOMMENDED else ""
    return result


def withdraw_decision(recommendation: dict, reason: str, language: str = "zh",
                      rebind_top_field=None,
                      citation_key: str = _CITATION_KEY) -> dict:
    """Withdraw an unsupported recommendation into an evidence-insufficient hold.

    The replaced recommendation/winner_rationale carry new text, so their old
    citation bindings are removed first. `rebind_top_field(rec, field, text)` is
    the existing resolution entry point: when provided, it re-resolves citations
    in the new text and writes its bindings. Candidate analysis, trade-offs and
    their bindings are untouched.
    """
    rec = recommendation if isinstance(recommendation, dict) else {}
    reason = (reason or "").strip() or "self-review found the recommendation unsupported"
    identity_map = rec.get(citation_key)
    if isinstance(identity_map, dict):
        identity_map.pop("recommendation", None)
        identity_map.pop("winner_rationale", None)
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
    if callable(rebind_top_field):
        for field in ("winner_rationale", "recommendation"):
            rebind_top_field(rec, field, rec[field])
    return rec
