"""Dependency-light citation syntax shared by synthesis, verification and rendering."""

import re


def citation_spans(value: str) -> list[tuple[int, int, str]]:
    """Keep punctuation and balanced brackets inside source titles intact."""
    lowered = value.lower()
    spans = []
    cursor = 0
    prefix = "[source:"
    while True:
        start = lowered.find(prefix, cursor)
        if start < 0:
            break
        depth = 0
        end = start
        while end < len(value):
            if value[end] == "[":
                depth += 1
            elif value[end] == "]":
                depth -= 1
                if depth == 0:
                    end += 1
                    break
            end += 1
        if depth != 0:
            break
        spans.append((start, end, value[start + len(prefix):end - 1].strip()))
        cursor = end
    return spans


def marker_titles(marker: str) -> list[str]:
    """Only a top-level explicit ', Source:' or '; Source:' separates titles."""
    titles = []
    depth = 0
    start = 0
    index = 0
    separator = re.compile(r"[,;]\s*Source:\s*", re.IGNORECASE)
    while index < len(marker):
        char = marker[index]
        if char == "[":
            depth += 1
        elif char == "]":
            depth = max(0, depth - 1)
        elif depth == 0 and char in ",;":
            match = separator.match(marker, index)
            if match:
                if marker[start:index].strip():
                    titles.append(marker[start:index].strip())
                index = match.end()
                start = index
                continue
        index += 1
    if marker[start:].strip():
        titles.append(marker[start:].strip())
    return titles


def title_key(title: str) -> str:
    """Case/space equivalence must not erase technology-significant punctuation."""
    return " ".join(title.casefold().split())
