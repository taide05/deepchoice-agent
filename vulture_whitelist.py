"""Vulture whitelist: public/dynamic API referenced outside static analysis.

These names are used by entrypoints, tests, templates or dynamic dispatch and are therefore
reported as unused by vulture's static scan. Listing them here keeps CI's dead-code check
meaningful for genuinely dead code without flagging public API surface.
"""

canonical_source_title  # public API
resolve_citations  # public API
last_rejected  # public API
run_research_task  # public API
run_probe  # public API
run_arm_limited  # public API
default_evidence_budget  # public API
_filter_relevant_used  # public API
source_concentration_flags  # public API
v6_enabled  # public API
handle_async_request  # public API
at  # public API
health_check  # public API
SE_TIMEOUT_S  # public API
requests  # public API
EvidenceResult  # public API
search_queries  # public API
questions_seen  # public API
packages_built  # public API
clear_cache  # public API
_reset_for_tests  # public API
_is_vs_query  # public API
dwSize  # public API
guard_service  # public API
health  # public API
start_research  # public API
cancel_research  # public API
stream_research  # public API
research_checkpoints  # public API
research_report  # public API
research_annotated  # public API
research_export  # public API
research_snapshot  # public API
regenerate_report  # public API
task_status  # public API
start_clarify  # public API
clarify_message  # public API
clarify_status  # public API
clarify_finalize  # public API
final_recommendation  # public API
retry_count  # public API
current_phase  # public API
agent_timing  # public API
candidate_tokens  # public API
bounded_content_summary  # public API
set_local_loader  # public API
reset_embedding_model_state  # public API
set_record_callback  # public API
set_current_case  # public API
handle_starttag  # public API
handle_endtag  # public API
handle_data  # public API

# Starlette invokes middleware.dispatch dynamically.
dispatch  # Starlette middleware entrypoint
