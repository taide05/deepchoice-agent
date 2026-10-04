from ..utils.evidence import is_navigation_placeholder
from ..utils.evidence_choices import bounded_source_passages
from ..utils.official_catalog import AUDITED_SNIPPET_WINDOW
from ..utils.views import print_agent_output


def build_evidence_chain(source_scores: list[dict], conflicts: list[dict]) -> list[dict]:
    disputed_urls = set()
    for c in conflicts:
        disputed_urls.add(c.get("source_a", {}).get("url", ""))
        disputed_urls.add(c.get("source_b", {}).get("url", ""))

    chains = []
    for s in source_scores:
        passages = bounded_source_passages(s)
        if (passages is None or s["total_score"] < 4.0
                or is_navigation_placeholder(s.get("snippet"))):
            continue

        evidence_sources = [{
            "url": s["url"],
            "title": s.get("title", ""),
            "snippet": s.get("snippet", ""),
            "score": s["total_score"],
        }]
        if passages:
            evidence_sources[0]["passages"] = list(passages)
        if s.get("_seed_excerpt_window") == AUDITED_SNIPPET_WINDOW:
            evidence_sources[0]["_seed_excerpt_window"] = AUDITED_SNIPPET_WINDOW

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
        return {
            "evidence_chains": chains,
            "quality_signals": [{
                "agent": "evidence_chain",
                "total_chains": len(chains),
                "strong": sum(1 for c in chains if c["evidence_strength"] == "strong"),
                "moderate": sum(1 for c in chains if c["evidence_strength"] == "moderate"),
                "weak": sum(1 for c in chains if c["evidence_strength"] == "weak"),
                "disputed": sum(1 for c in chains if c.get("disputed")),
            }],
        }
