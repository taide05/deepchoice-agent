"""Explicit native-synthesis prerequisites; legacy qualification assets stay frozen."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from benchmarks.product_baseline_experiment import RESOURCE_SETTINGS
from benchmarks.product_baseline_qualification import (
    PrerequisiteBudget, configuration_sha256, dependency_records,
    file_hash, git_identity, now, write_json,
)


def trusted_configuration(*, synthesis_thinking: bool = True):
    from deepchoice.outbound.channels import OutboundConfig
    from deepchoice.outbound.tunnel import proxy_endpoint_identity
    if synthesis_thinking is not True or os.getenv("DEEPCHOICE_SYNTH_THINKING", "0") != "1":
        raise ValueError("native synthesis must be explicitly enabled")
    load_dotenv()
    os.environ.update(RESOURCE_SETTINGS)
    cfg = OutboundConfig.from_env()
    os.environ["SAFE_FETCH_TRUSTED_LOCAL_PROXY"] = proxy_endpoint_identity(cfg.local_proxy)
    return OutboundConfig.from_env()


def synthesis_probe_contract() -> dict:
    from deepchoice.utils.llm import max_output_tokens_for
    return {"extra_body": {"thinking": {"type": "enabled"}, "reasoning_effort": "high"},
            "max_tokens": max_output_tokens_for("conclusion_synthesizer"), "seed": 0}

async def probe_llm_once(*, synthesis_thinking: bool = True) -> dict:
    """Probe base calls and native synthesis reasoning for this opt-in candidate."""
    from benchmarks.product_baseline_preflight import error_metadata
    from deepchoice.utils.call_diagnostics import observe_output, strict_json
    from deepchoice.utils.llm import TIERS, _get_client, deepseek_extra_body
    from deepchoice.utils.token_usage import provider_usage

    model = TIERS['deepseek-flash']['model']
    if synthesis_thinking is not True:
        raise ValueError('native synthesis mode must be enabled')
    probes = ('json', 'tools', 'synthesis')
    results = []
    for name in probes:
        item = {'probe': name, 'passed': False, 'usage': None}
        try:
            kwargs = {'model': model, 'temperature': 0, 'max_tokens': 128,
                      'extra_body': deepseek_extra_body()}
            if name == 'synthesis':
                kwargs.update(synthesis_probe_contract())
            if name in ('json', 'synthesis'):
                kwargs.update(messages=[{'role': 'user', 'content':
                    'Return JSON with the single boolean field "ok": true.'}],
                    response_format={'type': 'json_object'})
            else:
                kwargs.update(messages=[{'role': 'user', 'content': 'Call the check tool with ok=true.'}],
                    tools=[{'type': 'function', 'function': {'name': 'check',
                        'description': 'Compatibility test', 'parameters': {'type': 'object',
                        'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok']}}}],
                    tool_choice={'type': 'function', 'function': {'name': 'check'}})
            async with _get_client(timeout=30, max_retries=0) as client:
                response = await client.chat.completions.create(**kwargs)
            item['usage'] = provider_usage(response.usage) if response.usage else None
            choice = response.choices[0]
            content = choice.message.content
            tool_valid = True
            if name == 'tools':
                calls = choice.message.tool_calls or []
                tool_valid = len(calls) == 1 and calls[0].function.name == 'check'
                content = calls[0].function.arguments if calls else None
            try:
                parsed = strict_json(content)
            except (TypeError, ValueError, RecursionError):
                parsed = None
            diagnostic = observe_output(choice, json_requested=True, content=content,
                parsed=parsed, parse_ok=isinstance(parsed, dict),
                tag='check' if name == 'tools' else 'o1-json-probe')
            item['diagnostics'] = diagnostic
            item['passed'] = (tool_valid and isinstance(parsed, dict) and parsed.get('ok') is True
                and diagnostic['json_status'] == 'strict' and diagnostic['schema_status'] == 'valid'
                and diagnostic['truncated'] is False)
            if name == 'synthesis':
                reasoning = getattr(choice.message, 'reasoning_content', None)
                item['reasoning_chars'] = len(reasoning) if isinstance(reasoning, str) else 0
                item['passed'] = item['passed'] and item['reasoning_chars'] > 0
                item['call_contract'] = synthesis_probe_contract()
        except Exception as exc:
            item.update(error_metadata(exc))
        results.append(item)
        if not item['passed']:
            break
    return {'schema_version': 1, 'model_id': model, 'results': results,
            'passed': len(results) == len(probes) and all(item['passed'] for item in results),
            'research_runs_submitted': 0}

async def preflight(directory: Path, cfg, *, commit: str, synthesis_thinking: bool = True) -> dict:
    from deepchoice import outbound
    from deepchoice.outbound.resolver import ChannelResolver

    if synthesis_thinking is not True or os.getenv('DEEPCHOICE_SYNTH_THINKING', '0') != '1':
        raise ValueError('prerequisite synthesis mode mismatch')
    if directory.exists():
        raise ValueError('prerequisite output must be fresh')
    directory.mkdir(parents=True)
    from deepchoice.utils.llm import TIERS
    model = TIERS['deepseek-flash']
    write_json(directory / 'dependencies.json', dependency_records())
    budget = PrerequisiteBudget(directory)
    previous = outbound._resolver
    outbound.set_resolver(ChannelResolver(cfg))
    result = {'schema_version': 1, 'started_at': now(), 'git_commit': commit,
              'proxy_sha256': cfg.safe_fetch_proxy_sha256, 'passed': False,
              'configuration_sha256': configuration_sha256(cfg),
              'dependency_snapshot_sha256': file_hash(directory / 'dependencies.json'),
              'model_id': model['model'],
              'endpoint_sha256': hashlib.sha256(model['base'].encode()).hexdigest(),
              'research_runs_submitted': 0, 'money': 'unavailable'}
    try:
        with budget.install():
            health = await outbound.get_resolver().health_check()
            result['sources'] = health['sources']
            write_json(directory / 'retrieval-routes.json', health)
            if not health['ok']:
                result['stop_reason'] = 'retrieval_routes_degraded'
                return result
            budget.phase = 'tavily'
            from deepchoice.retrievers import tavily_keypool as pool
            saved = pool._load_state()
            eligible = [key for key in pool._load_keys()
                        if not pool._is_fresh(saved.get(pool._hash(key), 0.0))]
            if not eligible:
                result['stop_reason'] = 'no_eligible_tavily_key'
                return result
            async with await outbound.make_client('tavily') as client:
                response = await pool._post_once(client.post, eligible[0],
                    {'query': 'langgraph', 'max_results': 1}, probing=True)
            result['tavily_post_status'] = response.status_code
            if response.status_code != 200:
                result['stop_reason'] = 'tavily_post_failed'
                return result
            budget.phase = 'llm'
            llm = await probe_llm_once(synthesis_thinking=True)
            write_json(directory / 'llm-preflight.json', llm)
            result['synthesis_call'] = synthesis_probe_contract()
            result['llm_preflight_sha256'] = file_hash(directory / 'llm-preflight.json')
            result['llm_compatibility'] = llm['passed']
            if not llm['passed']:
                result['stop_reason'] = 'llm_preflight_failed'
                return result
            result['passed'] = True
            return result
    except Exception as exc:
        result.update(stop_reason='preflight_exception', error_type=type(exc).__name__)
        return result
    finally:
        outbound.set_resolver(previous)
        result.update(budget.counts(), ended_at=now())
        write_json(directory / 'preflight-summary.json', result)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--trust-current-local-proxy", action="store_true")
    parser.add_argument("--execute-paid-probes", action="store_true")
    args = parser.parse_args()
    if not args.trust_current_local_proxy or not args.execute_paid_probes:
        parser.error("explicit local proxy and paid prerequisite opt-in required")
    os.environ["DEEPCHOICE_SYNTH_THINKING"] = "1"
    try:
        cfg = trusted_configuration()
        result = asyncio.run(preflight(Path(args.output_dir), cfg, commit=git_identity()))
        print(json.dumps(result), flush=True)
        return 0 if result["passed"] else 1
    except Exception as exc:
        print(json.dumps({"error_type": type(exc).__name__, "research_runs_submitted": 0}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
