from ..utils.views import print_agent_output


def build_evidence_chain(source_scores: list[dict], conflicts: list[dict]) -> list[dict]:
    """Collect the retrieved sources for the later stages.

    This is a **source registry**, not a set of findings. It used to turn each
    retrieval hit into a "conclusion" (its title) with an "evidence strength"
    derived from the metadata score, so a search result was presented as an
    established judgment. A retrieval score ranks how likely a result is to be
    relevant; it proves nothing about whether the source supports a claim. So
    the registry now records no conclusion and no strength, only the retrieval
    score as a priority, and the support a claim needs is established later (by
    the synthesis citing a source's actual content, and by self-review).
    """
    disputed_urls = set()
    for c in conflicts:
        disputed_urls.add(c.get("source_a", {}).get("url", ""))
        disputed_urls.add(c.get("source_b", {}).get("url", ""))

    chains = []
    for s in source_scores:
        if s["total_score"] < 4.0:
            continue

        evidence_sources = [{
            "url": s["url"],
            "title": s.get("title", ""),
            "snippet": s.get("snippet", ""),
            # Carry the body marker through. Without it every consumer falls back
            # to guessing from the snippet text, and a body-less link can be
            # presented as evidence again further down.
            "has_body": s.get("has_body", None),
            # Retrieval priority, not a claim about support.
            "retrieval_score": s["total_score"],
        }]
        # Provenance travels with the source so it can never be silently
        # relabelled as published material downstream.
        for key in ("provenance", "channel", "source_type", "date",
                    "source_owner", "source_kind", "body_identity_verified",
                    "body_url", "body_chars", "body_page_chars", "body_prose_chars",
                    "body_stored_chars", "body_page_truncated",
                    "body_stored_truncated", "body_truncated",
                    "body_content_type", "body_admission", "body_error",
                    "fetch_status"):
            if key in s:
                evidence_sources[0][key] = s[key]
        if evidence_sources[0]["has_body"] is None:
            evidence_sources[0].pop("has_body")

        disputed = s["url"] in disputed_urls
        chains.append({
            # A retrieved document states nothing on its own. The field stays for
            # schema compatibility, but it no longer carries a manufactured claim.
            "conclusion": "",
            "sources": evidence_sources,
            # Support is not established by this node, so it is not asserted.
            "evidence_strength": "unknown",
            "retrieval_score": s["total_score"],
            "disputed": disputed,
        })
    return chains


class EvidenceChainAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        source_scores = research_state.get("source_scores", [])
        conflicts = research_state.get("conflicts", [])
        print_agent_output(
            f"Building evidence chains from {len(source_scores)} scored sources",
            agent="EVIDENCE_CHAIN",
        )
        chains = build_evidence_chain(source_scores, conflicts)
        return {
            "evidence_chains": chains,
            "quality_signals": [{
                "agent": "evidence_chain",
                "total_chains": len(chains),
                # No strength bands: this node ranks retrieval, it does not
                # establish support. Counting "strong" here would report a
                # support verdict the pipeline never reached.
                "disputed": sum(1 for c in chains if c.get("disputed")),
            }],
        }
