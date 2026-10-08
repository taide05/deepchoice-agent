from ..formats import decision
from ..utils.answer_delivery import is_answer_delivery
from ..formats.comparison_matrix import render as render_comparison_matrix
from ..formats.evidence_first import render as render_evidence_first
from ..formats.what_why_how import render as render_what_why_how
from ..utils.views import print_agent_output

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

        # Distinguish incomplete sources with retained material from unavailable ones.
        partial_failures = research_state.get("partial_failures", [])
        if partial_failures:
            total = len(research_state.get("search_results", []))
            incomplete = [item["source"] for item in research_state.get("search_results", [])
                          if item.get("status") == "partial" and item.get("results")]
            unavailable = [name for name in partial_failures if name not in incomplete]
            available = total - len(unavailable)
            query = research_state["task"].get("query", "")
            is_zh = any('一' <= c <= '鿿' for c in query)
            if is_zh:
                research_state["data_source_note"] = (
                    f"数据覆盖: {available}/{total} 个来源可用。"
                    f"不可用: {', '.join(unavailable) or '无'}。"
                    f"结论基于可用来源，可能遗漏{'未取得材料中的信息' if incomplete else '不可用来源的视角'}。"
                )
            else:
                research_state["data_source_note"] = (
                    f"Data coverage: {available}/{total} sources available. "
                    f"Unavailable: {', '.join(unavailable) or 'none'}. "
                    f"Conclusions are based on the available sources and may miss {'information from pages not acquired' if incomplete else 'perspectives from unavailable ones'}."
                )

            if incomplete:
                research_state["data_source_note"] += (
                    f"部分可用: {', '.join(incomplete)}；补充页面获取失败，已取得材料仍须核验。"
                    if is_zh else
                    f" Partially available: {', '.join(incomplete)}; supplemental pages failed, and retained material still requires verification."
                )

        renderer = FORMAT_RENDERERS.get(fmt, render_what_why_how)
        report = renderer(research_state)

        rec = research_state.get("final_recommendation", {})
        # The public flag describes a displayable conditional choice in the
        # compact path. Legacy prose retains its historical field contract.
        has_recommendation = (any(item.get("kind") == "choice"
                                  for item in decision._displayable_analyses(rec))
                              if is_answer_delivery(rec) else bool(rec.get("recommendation")))
        return {
            "report": report,
            "quality_signals": list(research_state.get("quality_signals", [])) + [{
                "agent": "report_generator",
                "format": fmt,
                "has_recommendation": has_recommendation,
                "recommendation_confidence": rec.get("confidence", "N/A"),
            }],
        }
