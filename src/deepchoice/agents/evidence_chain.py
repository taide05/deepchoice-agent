from ..utils.views import print_agent_output


def build_evidence_chain(source_scores: list[dict], conflicts: list[dict]) -> list[dict]:
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
            "score": s["total_score"],
        }]

        if s["total_score"] >= 8.0 and len(s.get("supporting_sources", [])) >= 1:
            strength = "strong"
        elif s["total_score"] >= 6.0:
            strength = "moderate"
        else:
            strength = "weak"

        disputed = s["url"] in disputed_urls
        chains.append({
            "conclusion": s.get("title", "Key finding"),
            "sources": evidence_sources,
            "evidence_strength": strength,
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
        return {"evidence_chains": chains}
