"""Bounded source coordinates for the existing staged fact-selection call.

Original evidence chains remain immutable. A selection is re-derived from them
at binding and citation time; local matches never grant a citation status.
"""
import json
import re
from copy import deepcopy

from .evidence import conclusion_source_allowed, is_navigation_placeholder
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


def _selection_rows(chains):
    """Yield identity-valid rows before menu capacity is applied."""
    from ..citations.verifier import _resolve_title, _source_registry, _split_sentences
    from .evidence_choices import eligible_source_fact_ids, whole_source_text

    registry, _ = _source_registry(chains)
    whole_ids = eligible_source_fact_ids(chains)
    number = 0
    for chain_index, chain in enumerate(chains):
        for source_index, source in enumerate(chain.get("sources", [])[:4]):
            number += 1
            if not isinstance(source, dict) or not conclusion_source_allowed(source):
                continue
            from .conflict_scope import validated_conflict_scope
            conflict_scope = validated_conflict_scope(source) if "conflict_scope" in source else None
            if ((chain.get("disputed") or "conflict_scope" in source) and conflict_scope is None):
                continue
            title = source.get("title")
            resolved, error = _resolve_title(title, registry) if isinstance(title, str) else (None, True)
            if error or resolved is None or not resolved.canonical_url or resolved.position != (chain_index, source_index):
                continue
            scope = selection_sentences(source)
            whole = number in whole_ids
            if scope is None and not whole:
                continue
            sentences = scope or tuple(_split_sentences(whole_source_text(source.get("snippet"))))
            row = {"title": resolved.title, "whole_allowed": whole,
                   "ranges_allowed": scope is not None,
                   "sentences": [{"index": index, "text": text} for index, text in enumerate(sentences)]}
            if conflict_scope:
                row["conflict_ranges"] = conflict_scope["ranges"]
            if source.get("passages"):
                # Existing disjoint excerpts must not look like a single location.
                row["separate_locations"] = True
                locations = [location for location, passage in enumerate(source["passages"], 1)
                             for _ in _split_sentences(passage)]
                for sentence, location in zip(row["sentences"], locations):
                    sentence["location"] = location
            yield number, row


def selection_packet(chains):
    """Preserve the bounded legacy coordinate menu and range admission."""
    lines, offered, size = [], set(), 0
    for number, row in _selection_rows(chains):
        line = f"[[{number}]] " + json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        needed = len(line.encode("utf-8")) + bool(lines)
        if len(offered) >= MAX_PACKET_SOURCES or size + needed > MAX_PACKET_BYTES:
            continue  # Omit the entire source, never a trailing qualifier.
        lines.append(line)
        offered.add(number)
        size += needed
    return "\n".join(lines), offered


SOURCE_VIEW_SELECTION_POLICY = "runtime-source-views-v1:sources=24;bytes=24000;focus=2+maximal;range-admission=legacy-menu"


def selection_view_packet(chains):
    """Advertise runtime-built views; models select IDs, never coordinates.

    Whole bounded sources retain the compatibility binder. Longer continuous
    sources offer short and maximal adjacent-context windows through the SAME range and
    conflict checks. A window is a bounded excerpt, not semantic completeness.
    Source sentences are shown once, with each view's actual included interval.
    Range sources keep the legacy menu admission used by citation and review;
    whole sources can refill capacity because they need no range admission.
    """
    from .evidence_choices import selected_source_text, bind_evidence_choices
    from ..citations.verifier import _split_sentences

    _, range_source_ids = selection_packet(chains)
    sources = [source for chain in chains for source in chain.get("sources", [])[:4]]
    lines, offered, size = [], {}, 0
    for number, original in _selection_rows(chains):
        if len(lines) >= MAX_PACKET_SOURCES:
            break
        source = sources[number - 1]
        count = len(original["sentences"])
        views, refs = [], {}
        if original["whole_allowed"]:
            identifier = f"S{number}"
            views.append({"id": identifier, "included_sentence_range": [0, count]})
            refs[identifier] = {"evidence_id": number}
        elif original["ranges_allowed"] and number in range_source_ids:
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
        validated, bindings = [], {}
        for view in views:
            ref = refs[view["id"]]
            rebound = bind_evidence_choices({"source_facts": [{"id": "F1", **ref}]}, chains, [], [])
            facts = rebound.get("source_facts", [])
            if not facts:
                continue
            fact = facts[0]
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
            bindings[view["id"]] = {"reference": ref, "source": deepcopy(source), "fact": fact}
        views, refs = validated, bindings
        if not views:
            continue
        row = {"title": original["title"], "views": views, "sentences": original["sentences"]}
        if original.get("separate_locations"):
            row["separate_locations"] = True
        if original.get("conflict_ranges"):
            row["conflict_ranges"] = original["conflict_ranges"]
        rendered = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        needed = len(rendered.encode("utf-8")) + bool(lines)
        if size + needed > MAX_PACKET_BYTES:
            continue  # Preserve the whole source row and its qualifications.
        lines.append(rendered)
        offered.update(refs)
        size += needed
    return "\n".join(lines), offered


def bind_selected_views(selected, offered, chains, candidates, requirements):
    """Rebuild advertised selections and assign F identities after binding.

    Invalid/unknown IDs never become guessed sources. Duplicate advertised IDs
    use one slot; an oversized response is rejected, never truncated.
    """
    from .evidence_choices import MAX_SOURCE_FACTS, bind_evidence_choices

    values = selected.get("source_view_ids") if isinstance(selected, dict) else None
    if not isinstance(values, list) or len(values) > MAX_SOURCE_FACTS:
        return []
    sources = [source for chain in chains for source in chain.get("sources", [])[:4]]
    refs, expected, seen = [], {}, set()
    for identifier in values:
        if not isinstance(identifier, str) or identifier not in offered or identifier in seen:
            continue
        seen.add(identifier)
        view = offered[identifier]
        number = view["reference"]["evidence_id"]
        if number > len(sources) or sources[number - 1] != view["source"]:
            continue  # Menu identities freeze the full original source, not only a crop.
        fact_id = f"F{len(refs) + 1}"
        refs.append({"id": fact_id, **view["reference"]})
        expected[fact_id] = view["fact"]
    bound = bind_evidence_choices({"source_facts": refs}, chains, candidates, requirements)
    fields = ("saved_text", "saved_passages", "source_title", "canonical_url")
    facts = [fact for fact in bound.get("source_facts", [])
             if all(fact.get(field) == expected[fact["id"]].get(field) for field in fields)]
    for index, fact in enumerate(facts, 1):
        fact["id"] = f"F{index}"
    return facts
