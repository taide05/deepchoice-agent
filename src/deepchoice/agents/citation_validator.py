"""Deterministic citation verification workflow node."""

from __future__ import annotations

from ..citations import verify_citations
from ..utils.views import print_agent_output


class CitationValidatorAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        recommendation = research_state.get("final_recommendation", {})
        evidence_chains = research_state.get("evidence_chains", [])
        print_agent_output(
            "Verifying critical-claim citations deterministically",
            agent="CITATION_VALIDATOR",
        )
        verification, projected_chains = await verify_citations(
            recommendation if isinstance(recommendation, dict) else {},
            evidence_chains if isinstance(evidence_chains, list) else [],
        )
        counts = verification.status_counts
        return {
            "citation_verification": verification.model_dump(mode="json"),
            "evidence_chains": projected_chains,
            "quality_signals": [{
                "agent": "citation_validator",
                "verified": counts.verified,
                "unsupported": counts.unsupported,
                "unreachable": counts.unreachable,
                "unknown": counts.unknown,
            }],
        }


__all__ = ["CitationValidatorAgent"]
