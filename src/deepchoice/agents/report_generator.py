from ..formats.comparison_matrix import render as render_comparison_matrix
from ..formats.evidence_first import render as render_evidence_first
from ..formats.report_quality import (
    finalize_report_text,
    report_contract_flags,
    report_ledger_flags,
    report_quality_flags,
)
from ..utils.claim_support import decisive_claim_support
from ..formats.what_why_how import render as render_what_why_how
from ..utils.confidence_text import align_confidence_rationale
from ..utils.views import print_agent_output

FORMAT_RENDERERS = {
    "what_why_how": render_what_why_how,
    "evidence_first": render_evidence_first,
    "comparison_matrix": render_comparison_matrix,
}


def _state_with_consistent_confidence(research_state: dict) -> dict:
    """A render input whose confidence prose agrees with the confidence field.

    The final-200 review found reports where the rationale named a different final
    level than the authoritative field, and internal "（自审调整：…）" notes rendered
    into user-facing text. The stored/finalised state is normalised in the
    self-review; this render-time pass covers the draft and replayed/legacy states
    without mutating the caller's dict.
    """
    rec = research_state.get("final_recommendation")
    if not isinstance(rec, dict):
        return research_state
    rationale = rec.get("confidence_rationale")
    if not rationale:
        return research_state
    aligned = align_confidence_rationale(rationale, rec.get("confidence"))
    if aligned == rationale:
        return research_state
    patched = dict(research_state)
    patched["final_recommendation"] = {**rec, "confidence_rationale": aligned}
    return patched


def render_report(research_state: dict) -> tuple[str, str]:
    """Render the report body from the current state, and the format used.

    The one place the report text is produced. Self-review is given the draft
    this returns; after review the same call produces the final body from the
    corrected state, so the two cannot diverge and a correction reaches every
    artefact that renders from the state.
    """
    state = _state_with_consistent_confidence(research_state)
    fmt = state["task"].get("report_format", "what_why_how")
    renderer = FORMAT_RENDERERS.get(fmt, render_what_why_how)
    return finalize_report_text(renderer(state)), fmt


class ReportGeneratorAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        fmt = research_state["task"].get("report_format", "what_why_how")
        print_agent_output(f"Generating report in format: {fmt}", agent="REPORT_GENERATOR")

        # The data-coverage note is derived by the renderer from the recorded
        # partial failures (`formats/coverage.py`), so every entry that renders
        # this state — the draft, the final body, the report endpoint and the
        # exports — computes the same note. It used to be written into this
        # node's local copy only, which never entered the graph state.
        report, fmt = render_report(research_state)

        rec = research_state.get("final_recommendation", {})
        contract_flags = report_contract_flags(rec)
        support = decisive_claim_support(rec)
        return {
            "report": report,
            "quality_signals": [{
                "agent": "report_generator",
                "format": fmt,
                "has_recommendation": bool(rec.get("recommendation")),
                "recommendation_confidence": rec.get("confidence", "N/A"),
                "report_quality_flags": report_quality_flags(report),
                "report_contract_flags": contract_flags,
                "report_contract_ok": not contract_flags,
                "report_ledger_flags": report_ledger_flags(
                    rec, research_state.get("evidence_chains") or [], report),
                "claim_support_flags": support["flags"],
                "decisive_source_counts": support["counts"],
            }],
        }
