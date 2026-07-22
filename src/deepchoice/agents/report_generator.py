from ..utils.views import print_agent_output
from ..formats.what_why_how import render as render_what_why_how
from ..formats.evidence_first import render as render_evidence_first
from ..formats.comparison_matrix import render as render_comparison_matrix

FORMAT_RENDERERS = {
    "what_why_how": render_what_why_how,
    "evidence_first": render_evidence_first,
    "comparison_matrix": render_comparison_matrix,
}


class ReportGeneratorAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        fmt = research_state["task"].get("report_format", "what_why_how")
        print_agent_output(f"Generating report in format: {fmt}", agent="REPORT_GENERATOR")

        # Surface partial failures so the report can note which sources were unavailable
        partial_failures = research_state.get("partial_failures", [])
        if partial_failures:
            total = len(research_state.get("search_results", [])) + len(partial_failures)
            available = total - len(partial_failures)
            research_state["data_source_note"] = (
                f"Data coverage: {available}/{total} sources available. "
                f"Unavailable: {', '.join(partial_failures)}. "
                f"Conclusions are based on the available sources and may miss perspectives from unavailable ones."
            )

        renderer = FORMAT_RENDERERS.get(fmt, render_what_why_how)
        report = renderer(research_state)

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
