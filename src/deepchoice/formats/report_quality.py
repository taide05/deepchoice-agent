"""Report-quality post-processing and deterministic lint.

The synthesis citation pass resolves registered citations, but rendered reports
have shown two presentation defects that survive it: raw ``[[N]]`` numeric
markers left in body text (F200-040/050/053/071/077/120/178) and empty source
placeholders such as ``（）`` (F200-153). They are not factual errors, but they
make a report look like a broken citation and undermine verifiability.

Finalisation is deterministic and non-destructive: a raw numeric marker becomes
an explicit unresolved-citation gap (never a guessed source), and empty source
parentheses are removed. The report still shows what could not be resolved.
"""
from __future__ import annotations

import re

RAW_NUMERIC_CITATION = re.compile(r"\[\[(\d+)\]\]")
EMPTY_SOURCE_PARENS = re.compile(r"（\s*）|\(\s*\)")
DANGLING_PUNCT_SPACE = re.compile(r"[ \t]+([。，、；：！？])")


def finalize_report_text(report: str) -> str:
    """Make citation presentation explicit before the report is stored/exported."""
    text = RAW_NUMERIC_CITATION.sub(
        lambda match: f"〔引用未解析：编号 {match.group(1)}〕", report or "")
    text = EMPTY_SOURCE_PARENS.sub("", text)
    text = DANGLING_PUNCT_SPACE.sub(r"\1", text)
    return text


def report_quality_flags(report: str) -> list[str]:
    """Non-blocking quality flags for batch auditing (empty = clean presentation)."""
    flags: list[str] = []
    raw = RAW_NUMERIC_CITATION.findall(report or "")
    if raw:
        flags.append(f"raw_numeric_citation:{len(raw)}")
    if EMPTY_SOURCE_PARENS.search(report or ""):
        flags.append("empty_source_parentheses")
    if re.search(r"^[-*] \[(Medium|GitHub|YouTube|Unknown)\]\(https?://", report or "",
                 re.MULTILINE | re.IGNORECASE):
        flags.append("generic_source_label")
    return flags
