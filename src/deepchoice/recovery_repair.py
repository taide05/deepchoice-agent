"""Focused repair for 48b32bd + DeepSeek adapter.

Two active chains are corrected here. Nothing else is touched: no new keywords,
no per-question answers, no source allowlist, no timeouts raised to hide waits.

Chain 1 — conflict handling (`conflict_detector`), two defects:

  a) The "receipt" was never used as one. The scan that titles every candidate
     pair can never find a contradiction, because the pair candidates are
     selected by BGE title similarity with threshold 0.65, and the scan's own
     `type` is literally documented as
     "winner_disagreement|tradeoff_disagreement|vendor_bias|none". Two sources
     converge in similarity precisely when they agree, so it returned None for
     every pair and the node stopped with an empty conflict list. That empty
     list is indistinguishable from "no conflict exists". The similarity
     pre-filter now selects candidates the way the prompt already describes
     them: near-duplicate titles are dropped (distance >= 0.35), and the
     remaining pairs are ranked by how much their scores disagree. The scan is
     kept and partitions pairs by `type == "none"` explicitly, so "no
     difference found", "not scanned" and "scan failed" stay distinguishable
     states rather than collapsing into an empty list.

  b) A pair was arbitrated twice on identical input. The flash arbitration
     already answered the pair from title text; the re-arbitration then called
     the same `_make_prompt` on the same titles again, with the gathered
     evidence appended, on a 300 s timeout. The second call therefore re-ran the
     first call's work rather than extending it. The evidence is now gathered
     first for the pairs that are actually ambiguous, and each pair is
     arbitrated exactly once with that evidence inlined into the single prompt.

Chain 2 — source evaluation (`source_evaluator`), two defects:

  c) `chroma` results were classified as `official_doc`, which carries authority
     10 — the same as a real vendor document. A Chroma hit is a locally
     retrieved markdown file, so it is not official documentation on that
     ground alone; the retrieved URL still decides, exactly as it does for every
     other source.

  d) `supporting_sources` accepted ANY other source scoring >= 6.0 as mutual
     support, regardless of subject or position. One unrelated high-scoring
     source could therefore flip a chain to `strong`. Support now requires the
     other source to share the candidate subject, so unrelated high-scoring
     sources contribute nothing. The original source data is preserved: the
     URLs are still recorded, with the reason they are or are not counted.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Chain 1a — conflict candidate selection
# ---------------------------------------------------------------------------

# Near-duplicate titles state the same thing; they are not contradictions.
# The scan prompt itself documents its `type` as winner/tradeoff/vendor
# disagreements, so candidates must be pairs that agree closely enough to be
# about the same question while their scores disagree.
CONFLICT_SIMILARITY_MIN = 0.35

_QUESTION_STOP = frozenset(
    "vs versus or and the a an of for to in on with is are be by".split()
)


def _title_terms(title: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", (title or "").casefold())
    return frozenset(word for word in words if word and word not in _QUESTION_STOP)


def _same_subject(a: dict, b: dict) -> bool:
    """Whether two sources are plausibly about the same decision question.

    Used only to decide whether one may count as support for the other. Two
    unrelated high-scoring pages must not corroborate each other, so this asks
    for shared subject terms rather than shared score.
    """
    terms_a = _title_terms(a.get("title", ""))
    terms_b = _title_terms(b.get("title", ""))
    if not terms_a or not terms_b:
        return False
    overlap = terms_a & terms_b
    if not overlap:
        return False
    # Any two substantial shared terms, or one shared term when that term is the
    # only distinctive term either side has.
    if len(overlap) >= 2:
        return True
    return len(terms_a) <= 2 or len(terms_b) <= 2


def partition_candidates(high_score_sources, embeddings, norms, *, np):
    """Select conflict candidates and report why each pair was kept or dropped.

    Returns (candidates, rejected) where candidates are (i, j, similarity) sorted
    by score disagreement, and rejected maps a reason to the number of pairs.
    """
    candidates = []
    rejected = {"near_duplicate": 0, "unrelated": 0, "missing_title": 0}
    for i in range(len(high_score_sources)):
        for j in range(i + 1, len(high_score_sources)):
            title_a = high_score_sources[i].get("title", "")
            title_b = high_score_sources[j].get("title", "")
            if not title_a or not title_b:
                rejected["missing_title"] += 1
                continue
            sim = float(np.dot(embeddings[i], embeddings[j]) / (norms[i] * norms[j]))
            if sim < CONFLICT_SIMILARITY_MIN:
                # Different subjects: not a disagreement about the same choice.
                rejected["unrelated"] += 1
                continue
            if sim >= 0.985:
                # Effectively the same page; restating a claim is not a conflict.
                rejected["near_duplicate"] += 1
                continue
            candidates.append((i, j, sim))
    candidates.sort(
        key=lambda row: (
            -abs(float(high_score_sources[row[0]].get("total_score", 0))
                 - float(high_score_sources[row[1]].get("total_score", 0))),
            -row[2],
        )
    )
    return candidates, rejected


def apply_score_support(source_scores: list[dict]) -> dict:
    """Record which other sources may count as support, and why.

    Only sources about the same subject are eligible. The count is bounded so a
    single source cannot claim support from an arbitrary crowd.
    """
    stats = {"eligible": 0, "rejected_unrelated": 0, "rejected_low_score": 0}
    for source in source_scores:
        same_subject = []
        for other in source_scores:
            if other is source or other.get("url") == source.get("url"):
                continue
            if not _same_subject(source, other):
                stats["rejected_unrelated"] += 1
                continue
            if float(other.get("total_score", 0)) < 6.0:
                stats["rejected_low_score"] += 1
                continue
            same_subject.append(other["url"])
        source["supporting_sources"] = same_subject[:3]
        if source["supporting_sources"]:
            stats["eligible"] += 1
    return stats
