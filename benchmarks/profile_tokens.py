"""Run 1 case and report flash token usage per call site."""
import asyncio, json, time, sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# --- Patch call_model at module level BEFORE any imports ---
import deepchoice.utils.llm as llm_mod

stats = {}

_original = llm_mod.call_model

async def _patched(prompt, model="flash", response_format=None, timeout=120.0):
    import inspect
    frame = inspect.currentframe()
    caller = "unknown"
    for _ in range(8):
        frame = frame.f_back
        if frame is None:
            break
        fname = frame.f_code.co_filename.replace("\\", "/")
        if "conflict_detector" in fname:
            caller = "conflict_" + ("gather" if "gather_evidence" in frame.f_code.co_name else
                                     "arbitrate" if "arbitrate" in frame.f_code.co_name else
                                     "scan" if "scan" in frame.f_code.co_name else "other")
            break
        for tag in ["query_analyzer", "query_adapter", "self_reviewer", "conclusion_synthesizer"]:
            if tag in fname:
                caller = tag
                break
        if caller != "unknown":
            break

    t0 = time.monotonic()
    result = await _original(prompt, model=model, response_format=response_format, timeout=timeout)
    elapsed = time.monotonic() - t0

    total_chars = sum(len(str(m.get("content", ""))) for m in prompt)
    in_tokens = max(1, total_chars // 4)
    out_str = json.dumps(result, ensure_ascii=False, default=str) if isinstance(result, (dict, list)) else str(result)
    out_tokens = max(1, len(out_str) // 4)

    entry = stats.setdefault(caller, {"calls": 0, "total_in": 0, "total_out": 0, "total_s": 0})
    entry["calls"] += 1
    entry["total_in"] += in_tokens
    entry["total_out"] += out_tokens
    entry["total_s"] += elapsed
    return result

llm_mod.call_model = _patched

# Force re-import of modules that already imported call_model
for mod_name in list(sys.modules.keys()):
    if "deepchoice.agents" in mod_name:
        mod = sys.modules[mod_name]
        if hasattr(mod, "call_model"):
            mod.call_model = _patched

from deepchoice.agents.orchestrator import ChiefEditorAgent

async def main():
    case = {
        "query": "LangGraph vs CrewAI for building AI agents as a solo developer",
        "scene": "solo",
    }
    task = {
        "query": case["query"],
        "scene_context": case["scene"],
        "constraints": [],
        "report_format": "what_why_how",
        "gather_evidence": True,
    }

    print(f"Running: {case['query']}")
    t0 = time.monotonic()
    orchestrator = ChiefEditorAgent(task)
    await asyncio.wait_for(orchestrator.run_research_task(), timeout=480)
    total_s = time.monotonic() - t0

    print(f"\nTotal: {total_s:.1f}s\n")
    print(f"{'Caller':<30} {'Calls':>5} {'In tokens':>10} {'Out tokens':>10} {'Time(s)':>8}")
    print("-" * 65)
    grand_in = grand_out = grand_calls = grand_time = 0
    for caller in sorted(stats.keys()):
        s = stats[caller]
        print(f"{caller:<30} {s['calls']:>5} {s['total_in']:>10} {s['total_out']:>10} {s['total_s']:>8.1f}")
        grand_in += s["total_in"]
        grand_out += s["total_out"]
        grand_calls += s["calls"]
        grand_time += s["total_s"]
    print("-" * 65)
    print(f"{'TOTAL':<30} {grand_calls:>5} {grand_in:>10} {grand_out:>10} {grand_time:>8.1f}")
    print(f"\nEstimated cache-miss input: {grand_in:,} tokens")
    print(f"Estimated output: {grand_out:,} tokens")

if __name__ == "__main__":
    asyncio.run(main())
