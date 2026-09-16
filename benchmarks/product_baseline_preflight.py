"""Bounded O1 prerequisite probes; never submits a research task."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv


def error_metadata(exc: Exception) -> dict:
    # Classify provider validation hints without retaining an error body/message.
    body = getattr(exc, "body", None)
    message = str(body).lower() if body is not None else ""
    return {"error_type": type(exc).__name__, "http_status": getattr(exc, "status_code", None),
            "validation_hints": [word for word in (
                "model", "thinking", "max_tokens", "response_format", "insufficient", "balance",
                "not exist", "not found", "invalid", "unsupported", "temperature") if word in message]}


async def probe() -> dict:
    load_dotenv()
    from deepchoice.utils.llm import TIERS, _get_client, call_model, deepseek_extra_body
    from deepchoice.utils.token_usage import provider_usage

    results = []
    usage: list[dict] = []
    try:
        content = await call_model(
            [{"role": "user", "content": 'Return JSON with the single boolean field "ok": true.'}],
            response_format="json", usage=usage,
            timeout=30, tag="o1-json-probe",
        )
        results.append({"probe": "json", "passed": isinstance(content, dict) and content.get("ok") is True,
                        "usage": usage})
    except Exception as exc:
        results.append({"probe": "json", "passed": False, **error_metadata(exc)})
    if results[-1]["passed"]:
        try:
            async with _get_client(timeout=30, max_retries=0) as client:
                response = await client.chat.completions.create(
                    model=TIERS["deepseek-flash"]["model"],
                    messages=[{"role": "user", "content": "Call the check tool with ok=true."}],
                    tools=[{"type": "function", "function": {
                        "name": "check", "description": "Compatibility test",
                        "parameters": {"type": "object", "properties": {
                            "ok": {"type": "boolean"}}, "required": ["ok"]}}}],
                    tool_choice={"type": "function", "function": {"name": "check"}},
                    temperature=0, max_tokens=128, extra_body=deepseek_extra_body(),
                )
            calls = response.choices[0].message.tool_calls or []
            passed = bool(calls) and calls[0].function.name == "check" and json.loads(
                calls[0].function.arguments).get("ok") is True
            results.append({"probe": "tools", "passed": passed, "response_model": response.model,
                            "usage": provider_usage(response.usage) if response.usage else None})
        except Exception as exc:
            results.append({"probe": "tools", "passed": False, **error_metadata(exc)})
    return {"schema_version": 1, "model_id": TIERS["deepseek-flash"]["model"],
            "passed": len(results) == 2 and all(item["passed"] for item in results),
            "results": results, "research_runs_submitted": 0}


async def probe_routes() -> dict:
    """Credential-free outbound checks without importing the research graph."""
    load_dotenv()
    from deepchoice.outbound import get_resolver

    try:
        report = await get_resolver().health_check()
        sources = {name: {"ok": bool(info.get("ok")), "channel": info.get("channel")}
                   for name, info in report.get("sources", {}).items()}
        return {"schema_version": 1, "passed": bool(report.get("ok")), "sources": sources,
                "tavily_credential_probe": "not_run", "llm_probe": "not_run",
                "research_runs_submitted": 0}
    except Exception as exc:
        return {"schema_version": 1, "passed": False, **error_metadata(exc),
                "research_runs_submitted": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--execute-paid-probes", action="store_true")
    parser.add_argument("--mode", choices=("llm", "routes"), default="llm")
    args = parser.parse_args()
    destination = Path(args.output)
    if destination.exists() or (args.mode == "llm" and not args.execute_paid_probes):
        parser.error("requires a fresh output and --execute-paid-probes")
    result = asyncio.run(probe() if args.mode == "llm" else probe_routes())
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
