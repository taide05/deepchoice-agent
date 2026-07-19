import time
import asyncio
from pathlib import Path
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from ..state import ResearchState
from ..utils.views import print_agent_output
from .query_analyzer import QueryAnalyzerAgent
from .multi_retriever import MultiRetrieverAgent
from .source_evaluator import SourceEvaluatorAgent
from .conflict_detector import ConflictDetectorAgent
from .evidence_chain import EvidenceChainAgent
from .report_generator import ReportGeneratorAgent
from .self_reviewer import SelfReviewerAgent

OUTPUT_DIR = Path("./outputs")


async def _get_sqlite_saver():
    try:
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    except ImportError:
        return None
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    db_path = str(OUTPUT_DIR / "checkpoints.db")
    conn = await aiosqlite.connect(db_path)
    return AsyncSqliteSaver(conn)


class ChiefEditorAgent:
    def __init__(self, task: dict, websocket=None, stream_output=None, headers=None,
                 checkpointer=None, thread_id=None):
        self.task = task
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers or {}
        self.task_id = str(int(time.time()))
        self.thread_id = thread_id or self.task_id
        self.checkpointer = checkpointer if checkpointer is not None else MemorySaver()

    def _initialize_agents(self) -> dict:
        return {
            "query_analyzer": QueryAnalyzerAgent(self.websocket, self.stream_output, self.headers),
            "multi_retriever": MultiRetrieverAgent(self.websocket, self.stream_output, self.headers),
            "source_evaluator": SourceEvaluatorAgent(self.websocket, self.stream_output, self.headers),
            "conflict_detector": ConflictDetectorAgent(self.websocket, self.stream_output, self.headers),
            "evidence_chain": EvidenceChainAgent(self.websocket, self.stream_output, self.headers),
            "report_generator": ReportGeneratorAgent(self.websocket, self.stream_output, self.headers),
            "self_reviewer": SelfReviewerAgent(self.websocket, self.stream_output, self.headers),
        }

    def _create_workflow(self, agents, start_from="query_analyzer"):
        workflow = StateGraph(ResearchState)

        workflow.add_node("query_analyzer", agents["query_analyzer"].run)
        workflow.add_node("multi_retriever", agents["multi_retriever"].run)
        workflow.add_node("source_evaluator", agents["source_evaluator"].run)
        workflow.add_node("conflict_detector", agents["conflict_detector"].run)
        workflow.add_node("evidence_chain", agents["evidence_chain"].run)
        workflow.add_node("report_generator", agents["report_generator"].run)
        workflow.add_node("self_reviewer", agents["self_reviewer"].run)

        workflow.set_entry_point(start_from)
        if start_from == "query_analyzer":
            workflow.add_edge("query_analyzer", "multi_retriever")
        workflow.add_edge("multi_retriever", "source_evaluator")
        workflow.add_edge("source_evaluator", "conflict_detector")
        workflow.add_edge("conflict_detector", "evidence_chain")
        workflow.add_edge("evidence_chain", "report_generator")
        workflow.add_edge("report_generator", "self_reviewer")
        workflow.add_conditional_edges(
            "self_reviewer",
            self._route_after_review,
            {
                "end": END,
                "retry_small": "conflict_detector",
                "retry_full": "query_analyzer",
            },
        )

        return workflow

    def _route_after_review(self, state: ResearchState) -> str:
        confidence = state.get("confidence", "medium")
        retry_count = state.get("retry_count", 0)
        gaps = state.get("knowledge_gaps", [])

        if confidence in ("high", "medium"):
            return "end"
        if retry_count >= 1:
            return "end"

        if len(gaps) <= 2:
            return "retry_small"
        return "retry_full"

    def init_research_team(self, start_from="query_analyzer"):
        agents = self._initialize_agents()
        workflow = self._create_workflow(agents, start_from=start_from)
        return workflow.compile(checkpointer=self.checkpointer)

    def _make_config(self):
        return {"configurable": {"thread_id": self.thread_id}}

    async def run_research_task(self, task: dict | None = None):
        task = task or self.task
        has_sub_questions = bool(task.get("sub_questions"))
        start_from = "multi_retriever" if has_sub_questions else "query_analyzer"

        print_agent_output(f"Starting research from: {start_from}", agent="ORCHESTRATOR")
        chain = self.init_research_team(start_from=start_from)
        config = self._make_config()
        initial_state = {"task": task}
        if has_sub_questions:
            initial_state["sub_questions"] = task["sub_questions"]
        result = await chain.ainvoke(initial_state, config=config)
        return result

    async def astream_research_task(self, task: dict | None = None):
        task = task or self.task
        has_sub_questions = bool(task.get("sub_questions"))
        start_from = "multi_retriever" if has_sub_questions else "query_analyzer"

        print_agent_output(f"Starting research stream from: {start_from}", agent="ORCHESTRATOR")
        chain = self.init_research_team(start_from=start_from)
        config = self._make_config()
        initial_state = {"task": task}
        if has_sub_questions:
            initial_state["sub_questions"] = task["sub_questions"]

        async for event in chain.astream(initial_state, config=config, stream_mode="updates"):
            yield event

    async def get_state(self):
        chain = self.init_research_team()
        config = self._make_config()
        return await chain.aget_state(config)

    async def get_state_history(self):
        chain = self.init_research_team()
        config = self._make_config()
        result = []
        async for state in chain.aget_state_history(config):
            result.append(state)
        return result
