from typing import TypedDict


class ResearchState(TypedDict):
    task: dict
    sub_questions: list[str]
    adapted_queries: dict
    search_results: list[dict]
    source_scores: list[dict]
    conflicts: list[dict]
    evidence_chains: list[dict]
    final_recommendation: dict
    report: str
    confidence: str
    knowledge_gaps: list[str]
    retry_count: int
    partial_failures: list[str]
    quality_signals: list[dict]
    current_phase: str
