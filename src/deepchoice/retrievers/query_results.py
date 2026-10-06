"""Bounded rank-preserving allocation across query result batches."""


def merge_query_results(batches: list[list[dict]], limit: int) -> list[dict]:
    """Take one unseen URL per non-empty query per round, then fill spare slots.

    Shared URLs consume only one slot. Duplicate/empty batches cannot starve
    later queries; their next unseen result gets the same turn. This distributes
    retrieval opportunities, never asserts relevance or evidence support.
    """
    pending = [iter(batch) for batch in batches]
    results = []
    seen = set()
    while pending and len(results) < limit:
        remaining = []
        for batch in pending:
            for item in batch:
                url = item.get("url")
                if not url or url in seen:
                    continue
                seen.add(url)
                results.append(item)
                remaining.append(batch)
                break
            if len(results) == limit:
                return results
        pending = remaining
    return results
