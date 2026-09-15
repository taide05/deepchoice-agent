import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from ..budget.errors import BudgetExceededError
from ..contracts.manifest import (
    RunManifest,
    build_run_manifest,
    ensure_run_manifest_compatible,
)
from ..state import ResearchState
from ..observability import RuntimeTraceRecorder, TraceStatus
from ..runtime.context import (
    bind_node_attempt,
    classify_cancelled_trace_status,
    get_run_context,
)
from ..utils.views import print_agent_output
from .conclusion_synthesizer import ConclusionSynthesizerAgent
from .conflict_detector import ConflictDetectorAgent
from .evidence_chain import EvidenceChainAgent
from .multi_retriever import MultiRetrieverAgent
from .query_adapter import QueryAdapterAgent
from .query_analyzer import QueryAnalyzerAgent
from .report_generator import ReportGeneratorAgent
from .self_reviewer import SelfReviewerAgent
from .source_evaluator import SourceEvaluatorAgent

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
                 checkpointer=None, thread_id=None, run_manifest: RunManifest | None = None,
                 checkpoint_ns: str = "",
                 checkpoint_id: str | None = None,
                 execution_guard: Callable[[], Awaitable[None]] | None = None):
        if checkpoint_ns:
            raise ValueError("The root research graph must use an empty checkpoint namespace.")
        self.task = task
        self.run_manifest = run_manifest or build_run_manifest(task)
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers or {}
        self.task_id = thread_id or str(uuid.uuid4())
        self.thread_id = thread_id or self.task_id
        self.checkpoint_ns = checkpoint_ns
        self.checkpoint_id = checkpoint_id
        self.checkpointer = checkpointer if checkpointer is not None else MemorySaver()
        self.execution_guard = execution_guard
        self.live_phase = None

    def _initialize_agents(self) -> dict:
        return {
            "query_analyzer": QueryAnalyzerAgent(self.websocket, self.stream_output, self.headers),
            "query_adapter": QueryAdapterAgent(self.websocket, self.stream_output, self.headers),
            "multi_retriever": MultiRetrieverAgent(self.websocket, self.stream_output, self.headers),
            "source_evaluator": SourceEvaluatorAgent(self.websocket, self.stream_output, self.headers),
            "conflict_detector": ConflictDetectorAgent(
                self.websocket, self.stream_output, self.headers,
                gather_evidence=self.run_manifest.gather_evidence,
            ),
            "evidence_chain": EvidenceChainAgent(self.websocket, self.stream_output, self.headers),
            "conclusion_synthesizer": ConclusionSynthesizerAgent(
                self.websocket,
                self.stream_output,
                self.headers,
                run_manifest=self.run_manifest,
            ),
            "report_generator": ReportGeneratorAgent(self.websocket, self.stream_output, self.headers),
            "self_reviewer": SelfReviewerAgent(self.websocket, self.stream_output, self.headers),
        }

    def _timed_node(self, name: str, fn):
        """Wrap an agent node with per-node timing, recording to state['agent_timing']."""
        async def _wrapper(state: dict) -> dict:
            self.live_phase = name
            if self.execution_guard is not None:
                await self.execution_guard()
            context = get_run_context()
            trace = (
                context.trace
                if context is not None
                and isinstance(context.trace, RuntimeTraceRecorder)
                else None
            )
            attempt = (
                await trace.start_node_attempt(name) if trace is not None else None
            )
            t0 = time.monotonic()
            try:
                with bind_node_attempt(
                    attempt.node_attempt_id if attempt is not None else None
                ):
                    result = await fn(state)
                    if self.execution_guard is not None:
                        await self.execution_guard()
                    if context is not None:
                        await context.budget.raise_if_exhausted(
                            partial_state={**state, **result}
                        )
            except asyncio.CancelledError:
                if trace is not None:
                    await trace.finish_node_attempt(
                        attempt,
                        status=classify_cancelled_trace_status(context),
                        summary={"elapsed_ms": round((time.monotonic() - t0) * 1000)},
                    )
                raise
            except TimeoutError:
                if trace is not None:
                    await trace.finish_node_attempt(
                        attempt,
                        status=TraceStatus.TIMED_OUT,
                        summary={"elapsed_ms": round((time.monotonic() - t0) * 1000)},
                    )
                raise
            except BudgetExceededError as exc:
                exc.attach_partial_state(state)
                if trace is not None:
                    await trace.finish_node_attempt(
                        attempt,
                        status=TraceStatus.FAILED,
                        summary={
                            "elapsed_ms": round((time.monotonic() - t0) * 1000),
                            "error_type": type(exc).__name__,
                            "failure_category": "budget_exceeded",
                        },
                    )
                raise
            except Exception as exc:
                if trace is not None:
                    await trace.finish_node_attempt(
                        attempt,
                        status=TraceStatus.FAILED,
                        summary={
                            "elapsed_ms": round((time.monotonic() - t0) * 1000),
                            "error_type": type(exc).__name__,
                        },
                    )
                raise
            elapsed_ms = round((time.monotonic() - t0) * 1000)
            if trace is not None:
                await trace.finish_node_attempt(
                    attempt,
                    status=TraceStatus.SUCCEEDED,
                    summary={"elapsed_ms": elapsed_ms},
                )
            elapsed = round(elapsed_ms / 1000, 2)
            timing = dict(state.get("agent_timing", {}))
            timing[name] = elapsed
            result["agent_timing"] = timing
            result["current_phase"] = name
            return result
        return _wrapper

    def _create_workflow(self, agents, start_from="query_analyzer"):
        workflow = StateGraph(ResearchState)

        workflow.add_node("query_analyzer", self._timed_node("query_analyzer", agents["query_analyzer"].run))
        workflow.add_node("query_adapter", self._timed_node("query_adapter", agents["query_adapter"].run))
        workflow.add_node("multi_retriever", self._timed_node("multi_retriever", agents["multi_retriever"].run))
        workflow.add_node("source_evaluator", self._timed_node("source_evaluator", agents["source_evaluator"].run))
        workflow.add_node("conflict_detector", self._timed_node("conflict_detector", agents["conflict_detector"].run))
        workflow.add_node("evidence_chain", self._timed_node("evidence_chain", agents["evidence_chain"].run))
        workflow.add_node("conclusion_synthesizer", self._timed_node("conclusion_synthesizer", agents["conclusion_synthesizer"].run))
        workflow.add_node("report_generator", self._timed_node("report_generator", agents["report_generator"].run))
        workflow.add_node("self_reviewer", self._timed_node("self_reviewer", agents["self_reviewer"].run))

        workflow.set_entry_point(start_from)
        if start_from == "query_analyzer":
            workflow.add_edge("query_analyzer", "query_adapter")
        workflow.add_edge("query_adapter", "multi_retriever")
        workflow.add_edge("multi_retriever", "source_evaluator")
        workflow.add_edge("source_evaluator", "conflict_detector")
        workflow.add_edge("conflict_detector", "evidence_chain")
        workflow.add_edge("evidence_chain", "conclusion_synthesizer")
        workflow.add_edge("conclusion_synthesizer", "report_generator")
        workflow.add_edge("report_generator", "self_reviewer")
        workflow.add_conditional_edges(
            "self_reviewer",
            self._route_after_review,
            {
                "end": END,
                "retry_small": "query_adapter",
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
        # self_reviewer increments retry_count before routing, so retry_count==1
        # after the first self-review pass. With >= 1, the first low-confidence
        # pass ends immediately (no retry) — the 08-31 baseline behavior.
        # NOTE: 5908b73b enabled retry via "> 1", but full-pipeline retry
        # (retry_full) blows the 600s per-case budget; reverted here to unblock
        # evaluation. A true incremental retry is a separate follow-up item.
        if retry_count >= 1:
            return "end"

        if len(gaps) <= 2:
            return "retry_small"
        return "retry_full"

    def init_research_team(self, start_from="query_analyzer"):
        agents = self._initialize_agents()
        workflow = self._create_workflow(agents, start_from=start_from)
        return workflow.compile(checkpointer=self.checkpointer)

    def _make_config(self, *, pin_checkpoint: bool = False):
        configurable = {"thread_id": self.thread_id}
        if pin_checkpoint and self.checkpoint_id:
            configurable["checkpoint_id"] = self.checkpoint_id
        return {"configurable": configurable}

    def _make_initial_state(self, task: dict) -> dict:
        initial_state = {
            "task": task,
            "run_manifest": self.run_manifest.model_dump(mode="json"),
        }
        if task.get("sub_questions"):
            initial_state["sub_questions"] = task["sub_questions"]
        return initial_state

    async def run_research_task(self, task: dict | None = None, *, resume: bool = False):
        task = task or self.task
        ensure_run_manifest_compatible(self.run_manifest, task)
        has_sub_questions = bool(task.get("sub_questions"))
        start_from = "query_adapter" if has_sub_questions else "query_analyzer"

        print_agent_output(f"Starting research from: {start_from}", agent="ORCHESTRATOR")
        chain = self.init_research_team(start_from=start_from)
        config = self._make_config(pin_checkpoint=resume)
        graph_input = None if resume else self._make_initial_state(task)
        result = await chain.ainvoke(graph_input, config=config)
        return result

    async def astream_research_task(
        self, task: dict | None = None, *, resume: bool = False
    ):
        task = task or self.task
        ensure_run_manifest_compatible(self.run_manifest, task)
        has_sub_questions = bool(task.get("sub_questions"))
        start_from = "query_adapter" if has_sub_questions else "query_analyzer"

        print_agent_output(f"Starting research stream from: {start_from}", agent="ORCHESTRATOR")
        chain = self.init_research_team(start_from=start_from)
        config = self._make_config(pin_checkpoint=resume)
        graph_input = None if resume else self._make_initial_state(task)

        async for event in chain.astream(graph_input, config=config, stream_mode="updates"):
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
