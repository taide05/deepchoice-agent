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
# `[[7]` / `[[2` survive when the model truncates a citation or annotates it
# ("[[7] 同源"). They are not valid markers and must not leak into the report.
MALFORMED_NUMERIC_CITATION = re.compile(r"\[\[(\d+)\](?!\])")
TRUNCATED_NUMERIC_CITATION = re.compile(r"\[\[(\d*)(?=[^0-9\]]|$)")
EMPTY_SOURCE_PARENS = re.compile(r"（\s*）|\(\s*\)")
DANGLING_PUNCT_SPACE = re.compile(r"[ \t]+([。，、；：！？])")
# An unresolved citation is deliberately kept in the text (honest gap, never a
# guessed source), but it is still a presentation defect: the final-200 content
# review found 14/200 reports carrying one. Surface the count in batch health so
# a citation-resolution regression is visible without re-reading the report; the
# marker itself stays in the text.
CITATION_GAP_MARK = re.compile(
    r"〔引用未解析：[^〕]*〕|\[citation-unresolved: [^\]]*\]")


_NESTED_GAP_TITLE = re.compile(
    r"(〔引用未解析：来源标题 “)([^”〔]*)(〔引用未解析：[^〕]*〕)([^”]*)(”)")


def _collapse_nested_gaps(text: str) -> str:
    """Remove a gap marker nested inside another gap's title.

    The round-three validation (F200-151) produced title gaps whose title had
    swallowed a numeric gap, plus bracket residue (`”〕]]`). A gap inside a title
    is not readable and hides the actual reason; keep the title and drop the inner
    marker.
    """
    value = str(text or "")
    for _ in range(3):
        value, changed = _NESTED_GAP_TITLE.subn(
            lambda match: f"{match.group(1)}{match.group(2)}…{match.group(4)}{match.group(5)}",
            value)
        if not changed:
            break
    value = value.replace("〕]]", "〕").replace("〕]", "〕")
    return value


def finalize_report_text(report: str) -> str:
    """Make citation presentation explicit before the report is stored/exported."""
    # The small validation run (F200-165) rendered literal "\n" escape sequences
    # where the model meant paragraph breaks ("建议: ...。\n\n分支 A"). JSON
    # escaping is transport, not report text; unescape the common sequences and
    # collapse runs of blank lines.
    text = re.sub(r"\\r\\n|\\n", "\n", report or "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = RAW_NUMERIC_CITATION.sub(
        lambda match: f"〔引用未解析：编号 {match.group(1)}〕", text)
    text = MALFORMED_NUMERIC_CITATION.sub(
        lambda match: f"〔引用未解析：编号 {match.group(1)}（格式不完整）〕", text)
    text = TRUNCATED_NUMERIC_CITATION.sub(
        lambda match: (f"〔引用未解析：编号 {match.group(1)}（截断）〕"
                       if match.group(1) else "〔引用未解析：截断〕"), text)
    text = EMPTY_SOURCE_PARENS.sub("", text)
    text = DANGLING_PUNCT_SPACE.sub(r"\1", text)
    text = _collapse_nested_gaps(text)
    return text


def report_quality_flags(report: str) -> list[str]:
    """Non-blocking quality flags for batch auditing (empty = clean presentation)."""
    flags: list[str] = []
    raw = RAW_NUMERIC_CITATION.findall(report or "")
    if raw:
        flags.append(f"raw_numeric_citation:{len(raw)}")
    malformed = MALFORMED_NUMERIC_CITATION.findall(report or "")
    if malformed:
        flags.append(f"malformed_numeric_citation:{len(malformed)}")
    truncated = TRUNCATED_NUMERIC_CITATION.findall(report or "")
    if truncated:
        flags.append(f"truncated_numeric_citation:{len(truncated)}")
    if EMPTY_SOURCE_PARENS.search(report or ""):
        flags.append("empty_source_parentheses")
    gaps = CITATION_GAP_MARK.findall(report or "")
    if gaps:
        flags.append(f"citation_gap_markers:{len(gaps)}")
    if re.search(r"^[-*] \[(Medium|GitHub|YouTube|Unknown)\]\(https?://", report or "",
                 re.MULTILINE | re.IGNORECASE):
        flags.append("generic_source_label")
    return flags


def report_contract_flags(rec: dict) -> list[str]:
    """Deterministic contract checks on the synthesis decision object.

    These are report-construction checks, not content-quality judgements. A
    missing ranked rationale or a truncated open-question string means the
    rendered report cannot be treated as a complete unit even if the decision
    status itself is valid.
    """
    rec = rec or {}
    flags: list[str] = []
    ranked = rec.get("ranked_options") or []
    if not ranked:
        flags.append("no_ranked_options")
    for option in ranked:
        if not str((option or {}).get("rationale") or "").strip() and \
                not str((option or {}).get("constraint_fit") or "").strip():
            flags.append("ranked_option_no_rationale")
            break
    for question in rec.get("unresolved_questions") or []:
        text = str(question or "")
        if re.search(r"\[\[[^\]]*$", text) or text.rstrip().endswith("[["):
            flags.append("malformed_unresolved_question")
            break
    if rec.get("decision_validation_error"):
        flags.append("decision_validation_error")
    if rec.get("decision_validation_recovered"):
        flags.append("decision_validation_recovered")
    return flags


def report_ledger_flags(rec: dict, chains: list[dict], report: str) -> list[str]:
    """Check that visible citations and the source ledger are the same set.

    This is a presentation/ledger invariant, not a content-quality score. It is
    intentionally report-level so batch health can catch a regression without
    re-reading the content.
    """
    from .basis import used_sources
    from ..agents.conclusion_synthesizer import _norm_title

    used = used_sources(rec or {}, chains or [])
    used_titles: set[str] = set()
    for source in used:
        used_titles.add(str(source.get("title") or ""))
        used_titles.update(str(alias) for alias in (source.get("aliases") or []))
    markers = [m.strip() for m in re.findall(
        r"\[Source:\s*([^\]\n]+)\]", report or "") if m.strip()]
    ghost = [m for m in markers
             if not any(_norm_title(m) == _norm_title(t) for t in used_titles)]
    missing = [
        str(source.get("title") or "") for source in used
        if not any(_norm_title(alias) == _norm_title(m)
                   for alias in ([source.get("title")] + list(source.get("aliases") or []))
                   for m in markers)
    ]
    flags: list[str] = []
    if ghost:
        flags.append(f"ledger_ghost_markers:{len(ghost)}")
    if missing:
        flags.append(f"ledger_unlisted_sources:{len(missing)}")
    # Round-two validation (F200-041, 2026-11-03): a report can claim that a
    # source's body "was not retrieved" while the cited body is present. Surface it
    # for batch health; the prompt/self-review rules carry the correction.
    body_available = any(
        bool((source or {}).get("has_body"))
        for chain in (chains or []) if isinstance(chain, dict)
        for source in chain.get("sources") or [] if isinstance(source, dict))
    if body_available and re.search(
            r"正文未取回|未取回正文|正文缺失|正文未取到|"
            r"body (?:was )?not (?:retrieved|collected)|no retrieved body",
            report or "", re.IGNORECASE):
        flags.append("availability_claim_with_collected_bodies")
    return flags


def source_concentration_flags(rec: dict, report: str) -> list[str]:
    """Non-blocking publisher-concentration flags for source-independence review.

    Multiple pages from one publisher are separate sources but not independent
    corroboration of each other. This does not invalidate a report (official docs
    are often several pages on one host); it points the reviewer at a place where
    an "independent sources" claim needs checking.
    """
    from collections import Counter
    from urllib.parse import urlsplit

    bindings = (rec or {}).get("citation_sources") or {}
    urls: set[str] = set()
    if isinstance(bindings, dict):
        for items in bindings.values():
            for binding in items or []:
                if isinstance(binding, dict) and binding.get("url"):
                    urls.add(str(binding["url"]))
    hosts = Counter((urlsplit(url).netloc or "").lower() for url in urls)
    flags = [f"source_concentration:{host}:{count}"
             for host, count in hosts.most_common() if count >= 3][:3]
    text = report or ""
    if ("两份独立" in text or "independent sources" in text.lower()) and len(hosts) <= 1:
        flags.append("independence_claim_single_publisher")
    return flags

_INTERNAL_RULE_REF = re.compile(r"\brule\s*\d{1,2}\b", re.IGNORECASE)


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in str(text or ""))


def sanitize_arbitration_text(text) -> str:
    """Strip internal arbitration rule numbers from user-facing dispute text.

    The small validation run (F200-082, 2026-11-02) rendered the arbitrator's
    reasoning verbatim and it echoed the internal rules ("so rule 1 does not
    apply. Both sources provide benchmark evidence (rule 2)"). Rule numbers are
    internal instructions, not report content; the backstop renames them to a
    neutral phrase so a prompt miss cannot leak the arbitration scheme.
    """
    value = str(text or "")
    if not _INTERNAL_RULE_REF.search(value):
        return value
    replacement = "该规则" if _has_cjk(value) else "the scoring rule"
    return _INTERNAL_RULE_REF.sub(replacement, value)

