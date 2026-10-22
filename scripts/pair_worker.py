"""Real paired worker: one shared collection, then baseline and candidate arms.

Launched by `scripts/launch_pair.py`. The child writes its own `run_limits`
record before any research outbound call; the launcher's process guard watches
that record and enforces the same 1800 s total deadline. No supplementary
retrieval is performed after the shared snapshot, and no external judge is used.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
import time
import traceback

WORKTREE = pathlib.Path(__file__).resolve().parent.parent
SRC = WORKTREE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))


def _json_default(value):
    if isinstance(value, pathlib.Path):
        return str(value)
    return str(value)


def _dump(path: pathlib.Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                default=_json_default), encoding="utf-8")


def _task_from_payload(payload: dict) -> dict:
    task = {key: payload.get(key) for key in (
        "query", "scene_context", "candidate_techs", "constraints",
        "sub_questions", "report_format", "language") if key in payload}
    task.setdefault("report_format", "what_why_how")
    task.setdefault("language", "zh")
    return task


def _initial_state(task: dict) -> dict:
    state = {
        "task": task,
        "sub_questions": list(task.get("sub_questions") or []),
        "adapted_queries": {},
        "search_results": [],
        "source_scores": [],
        "conflicts": [],
        "conflict_check": {},
        "evidence_chains": [],
        "final_recommendation": {},
        "report": "",
        "confidence": "",
        "knowledge_gaps": [],
        "retry_count": 0,
        "partial_failures": [],
        "empty_sources": [],
        "quality_signals": [],
        "current_phase": "shared_collection",
        "agent_timing": {},
        "token_usage": [],
    }
    return state


def _official_http_stats(search_results: list[dict]) -> dict:
    pages = http = redirects = bodies = 0
    for channel in search_results or []:
        if channel.get("source") != "official":
            continue
        stats = channel.get("fetch_stats") or {}
        pages += int(stats.get("page_attempts") or 0)
        http += int(stats.get("http_requests") or 0)
        redirects += int(stats.get("redirects") or 0)
        bodies += int(stats.get("body_pages") or 0)
    return {"page_attempts": pages, "http_requests": http,
            "redirects": redirects, "body_pages": bodies}


def _limit_counts(start: dict, end: dict) -> dict:
    return {
        "llm_requests": int(end.get("llm_requests", 0))
        - int(start.get("llm_requests", 0)),
        "tavily_posts": int(end.get("tavily_posts", 0))
        - int(start.get("tavily_posts", 0)),
    }


async def main_async(args) -> int:
    import run_limits

    outdir = pathlib.Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    payload = json.loads(pathlib.Path(args.payload).read_text(encoding="utf-8"))
    task = _task_from_payload(payload)
    task_id = args.task_id

    # Local model preparation is separate from the shared-collection clock.
    preload = {"started": time.time(), "seconds": None, "state": None}
    try:
        from deepchoice.utils.embedding import prepare_embedding_model
        preload["state"] = prepare_embedding_model()
    except Exception as exc:
        preload["state"] = {"available": False,
                            "detail": f"{type(exc).__name__}: {exc}"}
    preload["seconds"] = round(time.time() - preload["started"], 2)
    _dump(outdir / "preload.json", preload)

    caps = run_limits.snapshot()
    expected = {"llm_requests_max": 48, "tavily_posts_max": 24,
                "wall_clock_max_s": 1800.0}
    if (caps["llm_requests_max"] > expected["llm_requests_max"]
            or caps["tavily_posts_max"] > expected["tavily_posts_max"]
            or caps["wall_clock_max_s"] > expected["wall_clock_max_s"]):
        _dump(outdir / "preflight_failure.json",
              {"caps": caps, "expected_max": expected})
        print("BLOCKED: budget caps are above the authorized maximum", flush=True)
        return 4

    # Run record is a precondition for every dispatch. The launcher's guard
    # watches this record and the same wall-clock deadline.
    run_limits.begin_run(task_id, str(outdir))
    run_limits.arm()
    from deepchoice.evaluation.pair_runtime import PairWindow, PairWindowError, run_arm_limited

    window = PairWindow(total_s=float(run_limits.WALL_CLOCK_MAX_S), arm_s=900.0)
    _dump(outdir / "caps.json", {"snapshot": run_limits.snapshot(),
                                 "expected_max": expected,
                                 "preload": preload})

    from deepchoice.agents.query_adapter import QueryAdapterAgent
    from deepchoice.agents.multi_retriever import MultiRetrieverAgent
    from deepchoice.agents.source_evaluator import SourceEvaluatorAgent
    from deepchoice.evaluation.simple_baseline import (
        build_shared_evidence, run_baseline, run_candidate,
    )

    state = _initial_state(task)
    shared_start_counts = run_limits.snapshot()
    shared_error = None
    shared_evidence = None
    try:
        if not state["sub_questions"]:
            from deepchoice.agents.query_analyzer import QueryAnalyzerAgent
            analyzed = await QueryAnalyzerAgent().run(state)
            state.update(analyzed)
            task["sub_questions"] = state.get("sub_questions") or []
        adapted = await QueryAdapterAgent().run(state)
        state.update(adapted)
        retrieved = await MultiRetrieverAgent().run(state)
        state.update(retrieved)
        evaluated = await SourceEvaluatorAgent().run(state)
        state.update(evaluated)
        shared_evidence = build_shared_evidence(state)
        state["shared_evidence_summary"] = {
            "package_sha256": shared_evidence.package_sha256,
            "entries_signature": shared_evidence.entries_signature,
            "package": shared_evidence.package,
            "coverage": shared_evidence.coverage,
        }
    except Exception as exc:
        shared_error = {
            "type": type(exc).__name__,
            "message": str(exc)[:1000],
            "traceback": traceback.format_exc()[-4000:],
        }
    shared_end_counts = run_limits.snapshot()
    shared_llm = _limit_counts(shared_start_counts, shared_end_counts)
    official = _official_http_stats(state.get("search_results") or [])
    shared_counts = {
        "llm_requests": shared_llm["llm_requests"],
        "tavily_posts": shared_llm["tavily_posts"],
        "official_http_requests": official["http_requests"],
        "official_page_attempts": official["page_attempts"],
        "official_redirects": official["redirects"],
        "official_body_pages": official["body_pages"],
        # Other retrievers do not expose per-source dispatch counters, so a
        # complete retrieval HTTP total is unknown rather than the row count.
        "http_requests": None,
        "http_requests_complete": False,
    }
    shared_snapshot = {
        "task": task,
        "state": state,
        "shared_retrieval_source_envelopes": len(state.get("search_results") or []),
        "shared_retrieval_counts": shared_counts,
        "run_limits_start": shared_start_counts,
        "run_limits_end": shared_end_counts,
        "shared_error": shared_error,
        "saved_at": time.time(),
    }
    _dump(outdir / "shared_snapshot.json", shared_snapshot)
    run_limits.persist_counts(str(outdir))

    result = {
        "task_id": task_id,
        "shared_snapshot": str(outdir / "shared_snapshot.json"),
        "shared_retrieval_source_envelopes": shared_snapshot[
            "shared_retrieval_source_envelopes"],
        "shared_retrieval_counts": shared_counts,
        "shared_error": shared_error,
        "allow_external_model": True,
        "allow_supplementary_search": False,
        "arms": {},
        "evidence_consistent": False,
        "unfinished": [],
    }

    if shared_evidence is not None and not shared_error:
        for arm_name, runner, extra in (
            ("baseline", run_baseline, {}),
            ("candidate", run_candidate,
             {"allow_supplementary_search": False}),
        ):
            if run_limits.stopped():
                result["unfinished"].append({
                    "arm": arm_name,
                    "reason": f"budget_stop:{run_limits.snapshot().get('stop_reason')}",
                })
                continue
            if window.remaining_total_s() <= 0:
                result["unfinished"].append({"arm": arm_name,
                                             "reason": "total_wall_clock_exhausted"})
                continue
            arm_start_counts = run_limits.snapshot()
            arm_record = None
            try:
                async def _run():
                    return await runner(
                        state, budget_chars=None, allow_model=True,
                        shared_evidence=shared_evidence, **extra)

                output, arm_record = await run_arm_limited(window, arm_name, _run)
                arm_end_counts = run_limits.snapshot()
                counts = _limit_counts(arm_start_counts, arm_end_counts)
                _dump(outdir / f"{arm_name}_state.json", output["state"])
                (outdir / f"{arm_name}_report.md").write_text(
                    output.get("report") or "", encoding="utf-8")
                arm_evidence = {
                    "package_sha256": shared_evidence.package_sha256,
                    "entries_signature": shared_evidence.entries_signature,
                    "package": shared_evidence.package,
                    "coverage": shared_evidence.coverage,
                    "actual_evidence_records": output.get(
                        "actual_evidence_records") or [],
                }
                _dump(outdir / f"{arm_name}_evidence.json", arm_evidence)
                arm_summary = {
                    "completed": True,
                    "timed_out": False,
                    "window": arm_record,
                    "counts": counts,
                    "cumulative": arm_end_counts,
                    "token_usage": output.get("token_usage") or [],
                    "final_recommendation": output.get("final_recommendation") or {},
                    "quality_signals": output.get("quality_signals") or [],
                    "report": str(outdir / f"{arm_name}_report.md"),
                    "actual_evidence_records": arm_evidence["actual_evidence_records"],
                }
                if run_limits.stopped():
                    arm_summary.update({
                        "completed": False,
                        "budget_stop": run_limits.snapshot().get("stop_reason"),
                        "reason": "run_limits stop reached; fallback content is not "
                                  "a completed arm",
                    })
                    result["unfinished"].append({
                        "arm": arm_name,
                        "reason": f"budget_stop:{arm_summary['budget_stop']}",
                    })
                result["arms"][arm_name] = arm_summary
                run_limits.persist_counts(str(outdir))
            except PairWindowError as exc:
                result["arms"][arm_name] = {
                    "completed": False, "reason": str(exc),
                    "counts": _limit_counts(arm_start_counts,
                                            run_limits.snapshot()),
                }
                result["unfinished"].append({"arm": arm_name,
                                             "reason": str(exc)})
            except asyncio.TimeoutError as exc:
                arm_end_counts = run_limits.snapshot()
                failure = {
                    "completed": False,
                    "timed_out": True,
                    "type": type(exc).__name__,
                    "message": "arm exceeded its bounded time",
                    "window": arm_record,
                    "counts": _limit_counts(arm_start_counts, arm_end_counts),
                    "cumulative": arm_end_counts,
                }
                _dump(outdir / f"{arm_name}_failure.json", failure)
                result["arms"][arm_name] = failure
                result["unfinished"].append({"arm": arm_name,
                                             "reason": "arm_timeout"})
                run_limits.persist_counts(str(outdir))
            except Exception as exc:
                arm_end_counts = run_limits.snapshot()
                failure = {
                    "completed": False,
                    "type": type(exc).__name__,
                    "message": str(exc)[:1000],
                    "traceback": traceback.format_exc()[-4000:],
                    "window": arm_record,
                    "counts": _limit_counts(arm_start_counts, arm_end_counts),
                    "cumulative": arm_end_counts,
                }
                _dump(outdir / f"{arm_name}_failure.json", failure)
                result["arms"][arm_name] = failure
                result["unfinished"].append({"arm": arm_name,
                                             "reason": f"{type(exc).__name__}"})
                run_limits.persist_counts(str(outdir))
        # Cross-arm actual consumption checks are recorded per arm.
        required = {"baseline": ("baseline_synthesis",),
                    "candidate": ("candidate_synthesis", "candidate_self_review")}
        evidence_ok = True
        for name, consumers in required.items():
            arm = result["arms"].get(name) or {}
            records = arm.get("actual_evidence_records") or []
            present = {record.get("consumer") for record in records}
            if not arm.get("completed") or not all(c in present for c in consumers):
                evidence_ok = False
                continue
            if any(record.get("package_sha256") != shared_evidence.package_sha256
                   or record.get("entries_signature") != shared_evidence.entries_signature
                   or record.get("entries_match") is not True
                   for record in records):
                evidence_ok = False
        result["evidence_consistent"] = evidence_ok

    result["window"] = {
        "elapsed_s": round(window.elapsed_s(), 3),
        "remaining_s": round(window.remaining_total_s(), 3),
        "arms": window.arms,
    }
    result["run_limits"] = run_limits.snapshot()
    _dump(outdir / "pair_result.json", result)
    stopped = bool(result["run_limits"].get("stop_reason"))
    final_state = "complete" if (not shared_error and not stopped
                                 and result["evidence_consistent"]
                                 and len(result["arms"]) == 2
                                 and all(a.get("completed") for a in result["arms"].values())) else "failed"
    run_limits.end_run(final_state,
                       detail=("paired arms complete" if final_state == "complete"
                               else ("run_limits stop preserved" if stopped
                                     else "shared or arm failure preserved")))
    run_limits.persist_counts(str(outdir))
    print(json.dumps({"task_id": task_id, "state": final_state,
                      "shared_error": bool(shared_error),
                      "arms": {k: v.get("completed") for k, v in result["arms"].items()},
                      "evidence_consistent": result["evidence_consistent"],
                      "elapsed_s": result["window"]["elapsed_s"]},
                     ensure_ascii=False), flush=True)
    return 0 if final_state == "complete" else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--preflight-only", action="store_true",
                        help="check frozen caps/env and exit without any dispatch")
    args = parser.parse_args(argv)
    os.chdir(WORKTREE)
    if args.preflight_only:
        import run_limits
        snap = run_limits.snapshot()
        limits = {
            "llm_requests_max": int(os.environ.get("PRECODEX_LLM_MAX", "40")),
            "tavily_posts_max": int(os.environ.get("PRECODEX_TAVILY_MAX", "24")),
            "wall_clock_max_s": float(os.environ.get("PRECODEX_WALL_MAX_S", "900")),
            "official_page_attempts": int(os.environ.get(
                "OFFICIAL_FETCH_MAX_PAGE_ATTEMPTS_PER_RUN", "2")),
            "official_http_requests": int(os.environ.get(
                "OFFICIAL_FETCH_MAX_HTTP_REQUESTS_PER_RUN", "6")),
            "official_page_deadline_s": float(os.environ.get(
                "OFFICIAL_FETCH_TOTAL_DEADLINE_S", "15")),
            "official_max_bytes": int(os.environ.get(
                "OFFICIAL_FETCH_MAX_BYTES", "200000")),
        }
        print(json.dumps({"snapshot": snap, "effective_env": limits,
                          "preflight_only": True}, ensure_ascii=False))
        ok = (snap["llm_requests_max"] <= 48 and snap["tavily_posts_max"] <= 24
              and snap["wall_clock_max_s"] <= 1800
              and limits["official_page_attempts"] <= 4
              and limits["official_http_requests"] <= 12
              and limits["official_page_deadline_s"] <= 15
              and limits["official_max_bytes"] <= 200000)
        return 0 if ok else 4
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
