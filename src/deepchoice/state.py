from typing import TypedDict


class ResearchState(TypedDict):
    task: dict
    sub_questions: list[str]
    adapted_queries: dict
    search_results: list[dict]
    source_scores: list[dict]
    conflicts: list[dict]
    conflict_check: dict
    evidence_chains: list[dict]
    final_recommendation: dict
    report: str
    confidence: str
    knowledge_gaps: list[str]
    partial_failures: list[str]
    # Sources that returned no research material (as opposed to failing). Kept in
    # state so the snapshot preserves which source is empty and why; an
    # undeclared field would be dropped by the graph on write.
    empty_sources: list[dict]
    # Per-node quality signals, accumulated explicitly in
    # orchestrator._timed_node. Deliberately no `Annotated` reducer: the graph
    # must not append a node's own signal twice when that node replays.
    quality_signals: list[dict]
    current_phase: str
    agent_timing: dict
    token_usage: list[dict]
