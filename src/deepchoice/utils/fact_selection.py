"""Bounded source coordinates for the existing staged fact-selection call.

Original evidence chains remain immutable. A selection is re-derived from them
at binding and citation time; local matches never grant a citation status.
"""
import json
import re
from copy import deepcopy

from .evidence import candidate_product_mentions, is_navigation_placeholder
from .source_scope import MAX_SCOPE_CHARS, MAX_SCOPE_SENTENCES, MAX_SENTENCE_CHARS

MAX_PACKET_BYTES = 24000
MAX_PACKET_SOURCES = 24
_OMISSION = re.compile(r"\[\s*(?:\.{3,}|…+)\s*\]|\.{3,}|…")

def _source_coordinates(source):
    """Keep original character spans, including Chinese sentence boundaries."""
    from ..citations.verifier import _split_sentences

    if not isinstance(source, dict):
        return None
    if "passages" in source:
        from .evidence_choices import bounded_source_passages
        passages = bounded_source_passages(source)
        if not passages or len(passages) != 1:
            return None
    raw = source.get("snippet")
    if not isinstance(raw, str) or is_navigation_placeholder(raw):
        return None
    text = " ".join(raw.split())
    if not text or len(text) > MAX_SCOPE_CHARS:
        return None
    sentences = tuple(_split_sentences(text))
    if (not sentences or len(sentences) > MAX_SCOPE_SENTENCES
            or any(not row or len(row) > MAX_SENTENCE_CHARS for row in sentences)):
        return None
    spans, cursor = [], 0
    for sentence in sentences:
        start = text.find(sentence, cursor)
        if start < 0 or text[cursor:start].strip():
            return None
        cursor = start + len(sentence)
        spans.append((start, cursor))
    if text[cursor:].strip():
        return None
    return text, sentences, spans


def selection_sentences(source):
    scope = _source_coordinates(source)
    return scope[1] if scope is not None else None


def selected_passages(source, ranges):
    """Copy focus ranges with bounded adjacent context from the original source."""
    from ..citations.source_windows import SourceDocument, locate_source_windows
    from ..citations.verifier import _split_sentences, _support_status
    from .evidence_choices import bounded_source_passages

    scope = _source_coordinates(source)
    if scope is None or not isinstance(ranges, list) or not 1 <= len(ranges) <= 3:
        return None
    text, sentences, spans = scope
    focuses, previous_end = [], 0
    document = SourceDocument((text,), incomplete=False)
    for pair in ranges:
        if (not isinstance(pair, list) or len(pair) != 2
                or any(type(index) is not int for index in pair)):
            return None
        start, end = pair
        if not previous_end <= start < end <= len(sentences):
            return None
        focus = text[spans[start][0]:spans[end - 1][1]]
        if (_OMISSION.search(focus) or focus[-1] not in ".!?。！？；;"
                or locate_source_windows((focus,), document) is None):
            return None
        focuses.append((start, end))
        previous_end = end
    # Keep one intact sentence on either side without guessing which words
    # introduce an exception. Explicit omission markers separate locations.
    # Store the focus coordinates unchanged, so every rebind is idempotent.
    expanded = []
    for start, end in focuses:
        # An omission-bearing neighbour may also carry the missing premise.
        # Refuse this focus instead of silently skipping that qualification.
        if ((start and _OMISSION.search(sentences[start - 1]))
                or (end < len(sentences) and _OMISSION.search(sentences[end]))):
            return None
        left, right = max(0, start - 1), min(len(sentences), end + 1)
        context = text[spans[left][0]:spans[right - 1][1]]
        if (context[-1] not in ".!?。！？；;"
                or (left == 0 and context[0].isascii() and context[0].islower())):
            return None
        if expanded and left <= expanded[-1][1]:
            expanded[-1] = (expanded[-1][0], max(expanded[-1][1], right))
        else:
            expanded.append((left, right))
    passages = [text[spans[start][0]:spans[end - 1][1]] for start, end in expanded]
    bounded = bounded_source_passages({"snippet": " ".join(passages), "passages": passages})
    if not bounded:
        return None
    windows = locate_source_windows(bounded, document)
    if windows is None:
        return None
    for passage, window in zip(bounded, windows):
        if any(_support_status(sentence, window.text)[0].value != "verified"
               for sentence in _split_sentences(passage)):
            return None
    return bounded


def _selection_rows(bindings):
    """Yield identity-valid rows before menu capacity is applied."""
    from ..citations.verifier import _split_sentences
    from .evidence_choices import bind_source_fact

    for number, binding in bindings.items():
        source, resolved = binding
        fact = bind_source_fact({"id": "F1", "evidence_id": number}, binding)
        scope = selection_sentences(source)
        if scope is None and fact is None:
            continue
        sentences = tuple(_split_sentences(fact["saved_text"])) if fact is not None else scope
        row = {"title": resolved.title, "whole_allowed": fact is not None,
               "ranges_allowed": scope is not None,
               "sentences": [{"index": index, "text": text} for index, text in enumerate(sentences)]}
        if "conflict_scope" in source:
            row["conflict_ranges"] = source["conflict_scope"]["ranges"]
        if source.get("passages"):
            row["separate_locations"] = True
            locations = [location for location, passage in enumerate(source["passages"], 1)
                         for _ in _split_sentences(passage)]
            for sentence, location in zip(row["sentences"], locations):
                sentence["location"] = location
        yield number, row


SOURCE_VIEW_SELECTION_POLICY = "runtime-source-views-v2:sources=24;bytes=24000;focus=2+maximal;shared-admission=max-packet-bytes;literal-candidate-first-fit;request-order"


def _view_rows(bindings):
    """Build both menu projections from the same source checks, without recursion."""
    from .evidence_choices import selected_source_text, bind_source_fact
    from ..citations.verifier import _split_sentences

    for number, original in _selection_rows(bindings):
        source = bindings[number][0]
        count = len(original["sentences"])
        views, refs = [], {}
        if original["whole_allowed"]:
            identifier = f"S{number}"
            views.append({"id": identifier, "included_sentence_range": [0, count]})
            refs[identifier] = {"evidence_id": number}
        elif original["ranges_allowed"]:
            focuses = []
            # Keep small mechanisms selectable without forcing unrelated numeric
            # material into the same fact. Also retain maximal windows for a
            # premise needing a larger context; neither view proves semantics.
            for maximal in (False, True):
                start = 0
                while start < count:
                    best = None
                    ends = (range(count, start, -1) if maximal
                            else range(min(start + 2, count), count + 1))
                    # Repeated short sentences can be ambiguous although their
                    # longer enclosing focus is uniquely locatable.
                    for end in ends:
                        text, passages = selected_source_text(source, {"source_ranges": [[start, end]]})
                        if text and passages is not None:
                            best = end
                            break
                    if best is None:
                        start += 1
                        continue
                    if (start, best) not in focuses:
                        focuses.append((start, best))
                    start = best
            for start, end in focuses:
                identifier = f"S{number}W{len(views) + 1}"
                views.append({"id": identifier,
                              "included_sentence_range": [max(0, start - 1), min(count, end + 1)]})
                refs[identifier] = {"evidence_id": number, "source_ranges": [[start, end]]}
        if not views:
            continue
        validated, view_bindings = [], {}
        for view in views:
            ref = refs[view["id"]]
            fact = bind_source_fact({"id": "F1", **ref}, bindings[number])
            if fact is None:
                continue
            if original["whole_allowed"]:
                original["sentences"] = [{"index": index, "text": text}
                                         for index, text in enumerate(_split_sentences(fact["saved_text"]))]
                if original.get("separate_locations"):
                    locations = [location for location, passage in enumerate(fact.get("saved_passages", []), 1)
                                 for _ in _split_sentences(passage)]
                    for sentence, location in zip(original["sentences"], locations):
                        sentence["location"] = location
                view["included_sentence_range"] = [0, len(original["sentences"])]
            left, right = view["included_sentence_range"]
            shown = tuple(row["text"] for row in original["sentences"][left:right])
            if shown != tuple(_split_sentences(fact["saved_text"])):
                continue  # Never advertise text differing from its bound view.
            validated.append(view)
            view_bindings[view["id"]] = {"reference": ref, "source": deepcopy(source), "fact": fact}
        views, refs = validated, view_bindings
        if not views:
            continue
        row = {"title": original["title"], "views": views, "sentences": original["sentences"]}
        if original.get("separate_locations"):
            row["separate_locations"] = True
        if original.get("conflict_ranges"):
            row["conflict_ranges"] = original["conflict_ranges"]
        rendered = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        numeric = f"[[{number}]] " + json.dumps(original, ensure_ascii=False, separators=(",", ":"))
        yield number, rendered, numeric, refs, max(len(rendered.encode("utf-8")), len(numeric.encode("utf-8")))


def _admitted_rows(chains, candidates=(), *, bindings=None):
    """One capacity decision for view display, numeric compatibility and ranges.

    Try the first fitting row per literal candidate in request order; this is
    best-effort coverage, not optimal packing. Ambiguous/unclassified titles
    compete only for remaining capacity. A title
    mention allocates an opportunity, never support. Emit in original order.
    """
    from .evidence_choices import source_fact_bindings

    bindings = source_fact_bindings(chains) if bindings is None else bindings
    rows = dict(_selection_rows(bindings))
    built, selected, size = {}, set(), 0

    def admit(number):
        nonlocal size
        if number in selected:
            return True
        if len(selected) >= MAX_PACKET_SOURCES:
            return False
        # The numeric row is a lower bound on the shared max projection cost.
        # It contains every source sentence: skipping an impossible whole row
        # avoids building its views, without truncation or a second allocator.
        numeric = f"[[{number}]] " + json.dumps(rows[number], ensure_ascii=False, separators=(",", ":"))
        if size + len(numeric.encode("utf-8")) + bool(selected) > MAX_PACKET_BYTES:
            return False
        if number not in built:
            built[number] = next(_view_rows({number: bindings[number]}), None)
        row = built[number]
        if row is None or size + row[4] + bool(selected) > MAX_PACKET_BYTES:
            return False
        size += row[4] + bool(selected)
        selected.add(number)
        return True

    groups = {}
    for number, row in rows.items():
        mentions = candidate_product_mentions(row["title"], candidates)
        if len(mentions) == 1:
            groups.setdefault(next(iter(mentions)), []).append(number)
    # Candidate order is request order, deduplicating multiple actions for one product.
    reserved = set()
    for candidate in candidates if isinstance(candidates, (list, tuple)) else []:
        for identity in sorted(candidate_product_mentions(candidate, [candidate])):
            if identity in reserved:
                continue
            reserved.add(identity)
            for number in groups.get(identity, []):
                if admit(number):
                    break
    for number in rows:
        admit(number)
    return [built[number] for number in rows if number in selected]


def admitted_source_ids(chains, candidates=(), *, bindings=None):
    return {row[0] for row in _admitted_rows(chains, candidates, bindings=bindings)}


def selection_packet(chains, candidates=()):
    """Numeric coordinate compatibility projection of the current shared menu."""
    rows = _admitted_rows(chains, candidates)
    return "\n".join(row[2] for row in rows), {row[0] for row in rows}


def selection_view_packet(chains, candidates=()):
    """Advertise only runtime-built, capacity-admitted view IDs and exact text."""
    rows = _admitted_rows(chains, candidates)
    return "\n".join(row[1] for row in rows), {key: view for row in rows for key, view in row[3].items()}


def bind_selected_views(selected, offered, chains, candidates, requirements):
    """Rebuild advertised selections and assign F identities after binding.

    Invalid/unknown IDs never become guessed sources. Duplicate advertised IDs
    use one slot; an oversized response is rejected, never truncated.
    """
    from .evidence_choices import MAX_SOURCE_FACTS

    values = selected.get("source_view_ids") if isinstance(selected, dict) else None
    if not isinstance(values, list) or not values or len(values) > MAX_SOURCE_FACTS:
        return []
    _, current = selection_view_packet(chains, candidates)
    facts, seen = [], set()
    for identifier in values:
        if not isinstance(identifier, str) or identifier not in offered or identifier in seen:
            continue
        seen.add(identifier)
        view = offered[identifier]
        if identifier not in current or current[identifier] != view:
            continue  # Recompute admission and freeze full sources, not only crops.
        fact = deepcopy(current[identifier]["fact"])
        fact["id"] = f"F{len(facts) + 1}"
        facts.append(fact)
    return facts
