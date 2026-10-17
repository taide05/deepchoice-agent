from ..formats.comparison_matrix import render as render_comparison_matrix
from ..formats.evidence_first import render as render_evidence_first
from ..formats.what_why_how import render as render_what_why_how
from ..utils.views import print_agent_output

FORMAT_RENDERERS = {
    "what_why_how": render_what_why_how,
    "evidence_first": render_evidence_first,
    "comparison_matrix": render_comparison_matrix,
}


def render_report(research_state: dict) -> tuple[str, str]:
    """Render the report body from the current state, and the format used.

    The one place the report text is produced. Self-review is given the draft
    this returns; after review the same call produces the final body from the
    corrected state, so the two cannot diverge and a correction reaches every
    artefact that renders from the state.
    """
    fmt = research_state["task"].get("report_format", "what_why_how")
    renderer = FORMAT_RENDERERS.get(fmt, render_what_why_how)
    return renderer(research_state), fmt


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
        return {
            "report": report,
            "quality_signals": [{
                "agent": "report_generator",
                "format": fmt,
                "has_recommendation": bool(rec.get("recommendation")),
                "recommendation_confidence": rec.get("confidence", "N/A"),
            }],
        }
