"""Runtime-owned coordinates of model-flagged conflict, never truth verdicts.

One continuous saved excerpt shares the existing fact-selection sentence view.
Unknown or ambiguous coordinates do not authorize partial source reuse.
"""
import hashlib
import json
from copy import deepcopy

POLICY = "sentence-conflict-v1"
_DEFAULT_SCOPE = object()


def conflict_coordinates(source):
    from .fact_selection import _OMISSION, _source_coordinates
    from ..citations.verifier import canonicalize_source_url

    view = _source_coordinates(source)
    if view is None:
        return None
    text, sentences, _ = view
    url = canonicalize_source_url(source.get("url"))
    if (not url or _OMISSION.search(text)
            or any(sentence[-1] not in ".!?。！？；;" for sentence in sentences)
            or (text[0].isascii() and text[0].islower())):
        return None
    identity = {"policy": POLICY, "url": url, "text": text,
                "structure": "single_passage" if "passages" in source else "snippet"}
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    return view, digest


def _valid_ranges(view, ranges, maximum):
    from ..citations.source_windows import SourceDocument, locate_source_window

    if not isinstance(ranges, list) or not 1 <= len(ranges) <= maximum:
        return False
    text, sentences, spans = view
    previous_end = 0
    document = SourceDocument((text,), False)
    for pair in ranges:
        if (not isinstance(pair, list) or len(pair) != 2
                or any(type(index) is not int for index in pair)):
            return False
        start, end = pair
        if not previous_end <= start < end <= len(sentences):
            return False
        passage = text[spans[start][0]:spans[end - 1][1]]
        if locate_source_window(passage, document) is None:
            return False
        previous_end = end
    return True


def make_conflict_scope(source, ranges):
    coordinates = conflict_coordinates(source)
    if coordinates is None or not _valid_ranges(coordinates[0], ranges, 3):
        return None
    return {"policy": POLICY, "identity_sha256": coordinates[1], "ranges": deepcopy(ranges)}


def validated_conflict_scope(source, scope=_DEFAULT_SCOPE):
    scope = source.get("conflict_scope") if scope is _DEFAULT_SCOPE else scope
    coordinates = conflict_coordinates(source)
    if (coordinates is None or not isinstance(scope, dict)
            or set(scope) != {"policy", "identity_sha256", "ranges"}
            or scope.get("policy") != POLICY
            or scope.get("identity_sha256") != coordinates[1]
            or not _valid_ranges(coordinates[0], scope.get("ranges"), 40)):
        return None
    return scope


def source_conflict_scope(source, conflicts):
    """Union all known conflict bindings for this URL; any unknown blocks it."""
    from ..citations.verifier import canonicalize_source_url

    url = canonicalize_source_url(source.get("url"))
    ranges = []
    for conflict in conflicts:
        for side in ("source_a", "source_b"):
            record = conflict.get(side, {})
            if canonicalize_source_url(record.get("url")) != url:
                continue
            if conflict.get("scan_status") != "confirmed":
                return None
            scope = validated_conflict_scope(source, record.get("conflict_scope"))
            if scope is None:
                return None
            ranges.extend(deepcopy(scope["ranges"]))
    if not ranges:
        return None
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    coordinates = conflict_coordinates(source)
    scope = {"policy": POLICY, "identity_sha256": coordinates[1], "ranges": merged}
    return scope if validated_conflict_scope(source, scope) else None


def conflict_fact_allowed(source, ranges):
    """A fact's focus plus retained adjacent context must avoid every conflict."""
    scope = validated_conflict_scope(source)
    coordinates = conflict_coordinates(source)
    if scope is None or coordinates is None or not _valid_ranges(coordinates[0], ranges, 3):
        return False
    sentence_count = len(coordinates[0][1])
    for start, end in ranges:
        left, right = max(0, start - 1), min(sentence_count, end + 1)
        if any(left < stop and right > first for first, stop in scope["ranges"]):
            return False
    return True
