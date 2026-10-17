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
    retry_count: int
    partial_failures: list[str]
    # Sources that returned no research material (as opposed to failing). Kept in
    # state so the snapshot preserves which source is empty and why; an
    # undeclared field would be dropped by the graph on write.
    empty_sources: list[dict]
    quality_signals: list[dict]
    current_phase: str
    agent_timing: dict
    token_usage: list[dict]
