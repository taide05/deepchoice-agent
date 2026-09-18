"""Bounded prerequisites and offline preparation for one durable qualification.

No command in this module submits a research task. Existing batch preparation
and LLM probe entry points retain their historical behavior.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from importlib.metadata import distributions
import inspect
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess

import httpx
from dotenv import load_dotenv

from benchmarks.product_baseline_experiment import (
    RESOURCE_SETTINGS, embedding_revision, file_hash, tree_hash,
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: dict | list) -> None:
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def git_identity() -> str:
    status = subprocess.run(['git', 'status', '--porcelain'], check=True,
                            capture_output=True, text=True).stdout
    if status.strip():
        raise ValueError('qualification requires a clean tracked working tree')
    return subprocess.run(['git', 'rev-parse', 'HEAD'], check=True,
                          capture_output=True, text=True).stdout.strip()


def dependency_records() -> list:
    return sorted({(d.metadata['Name'].lower(), d.version) for d in distributions()
                   if d.metadata.get('Name')})


def configuration_sha256(cfg) -> str:
    """Compare effective routing/settings without retaining endpoints or keys."""
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest() if value else None
    value = {'channel_order': cfg.channel_order, 'order_overrides': cfg.order_overrides,
             'local_proxy_sha256': digest(cfg.local_proxy), 'forward_sha256': digest(cfg.fwd_base),
             'forward_allowed': cfg.fwd_allowed, 'v6_enabled': cfg.v6_enabled,
             'trusted_proxy_sha256': cfg.safe_fetch_proxy_sha256,
             'settings': {**RESOURCE_SETTINGS, 'LLM_DS_CONCURRENCY': os.getenv('LLM_DS_CONCURRENCY', '80'),
                          'DEEPCHOICE_SYNTH_THINKING': os.getenv('DEEPCHOICE_SYNTH_THINKING', '0')}}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def verify_frozen_environment(environment: dict, cfg=None) -> str:
    """Fail before startup/admission when single-case frozen identity drifts."""
    from benchmarks.product_baseline import load_dataset
    from deepchoice.contracts.api import ResearchRequest
    from deepchoice.contracts.manifest import build_core_asset_registry, build_run_manifest
    from deepchoice.outbound.channels import OutboundConfig
    from deepchoice.utils.llm import TIERS

    notes = environment['notes']
    fixed_settings = {**RESOURCE_SETTINGS, 'LLM_DS_CONCURRENCY': os.getenv('LLM_DS_CONCURRENCY', '80'),
                      'DEEPCHOICE_SYNTH_THINKING': '0'}
    if notes.get('settings') != fixed_settings:
        raise ValueError('frozen qualification resource settings drift')
    if (notes.get('qualification_mode') != 'single-admission-v1' or notes.get('case_id') != 'P01'
            or notes.get('task_admission_limit') != 1 or notes.get('auto_recovery') is not False
            or notes.get('hitl_mode') != 'stop-at-hitl'
            or notes.get('embedding_startup_mode') != 'cold-in-research'):
        raise ValueError('invalid single-case qualification contract')
    cfg = cfg if cfg is not None else OutboundConfig.from_env()
    dependency_hash = hashlib.sha256((json.dumps(dependency_records(), ensure_ascii=False, indent=2)
                                     + '\n').encode()).hexdigest()
    model = TIERS['deepseek-flash']
    if (notes.get('git_commit') != git_identity()
            or notes.get('configuration_sha256') != configuration_sha256(cfg)
            or environment.get('dependency_snapshot_sha256') != dependency_hash
            or environment['model'].get('model_id') != model['model']
            or notes.get('endpoint_sha256') != hashlib.sha256(model['base'].encode()).hexdigest()
            or notes.get('embedding_revision') != embedding_revision()
            or environment['model'].get('thinking') != 'disabled'):
        raise ValueError('frozen qualification environment drift')
    dataset, dataset_hash = load_dataset(Path('benchmarks/product-baseline-v1.json'), require_frozen=True)
    request = next(c['request'] for c in dataset['cases'] if c['id'] == 'P01')
    manifest = build_run_manifest(ResearchRequest.model_validate(request).model_dump(exclude_none=True))
    if (notes.get('dataset_hash') != dataset_hash or notes.get('expected_manifest_id') != manifest.manifest_id
            or notes.get('core_asset_registry_id') != build_core_asset_registry().registry_id):
        raise ValueError('frozen qualification assets or request drift')
    return manifest.manifest_id


def trusted_configuration():
    """Opt in only for this process; never persist an endpoint or credentials."""
    from deepchoice.outbound.channels import OutboundConfig
    from deepchoice.outbound.tunnel import proxy_endpoint_identity

    load_dotenv()
    os.environ.update(RESOURCE_SETTINGS)
    cfg = OutboundConfig.from_env()
    os.environ['SAFE_FETCH_TRUSTED_LOCAL_PROXY'] = proxy_endpoint_identity(cfg.local_proxy)
    if os.getenv('DEEPCHOICE_SYNTH_THINKING', '0') != '0':
        raise ValueError('qualification covers disabled thinking only')
    return OutboundConfig.from_env()


class PrerequisiteBudget:
    """Count before dispatch, including the forward carrier conservatively.

    httpx 0.27/0.28's single-dispatch method is inspected before use. This
    temporary process-wide adapter also covers SDK requests and forward clients;
    it is not installed during research. Counts exclude implicit proxy CONNECT.
    """

    def __init__(self, directory: Path):
        self.directory = directory
        self.phase = 'routing'
        self.http_attempts = 0
        self.tavily_post_attempts = 0
        self.llm_attempts = 0

    def counts(self) -> dict:
        return {'http_attempts': self.http_attempts,
                'tavily_post_attempts': self.tavily_post_attempts,
                'llm_attempts': self.llm_attempts}

    @contextmanager
    def install(self):
        original = httpx.AsyncClient._send_single_request
        if tuple(inspect.signature(original).parameters) != ('self', 'request'):
            raise RuntimeError('unsupported HTTP dispatch adapter')

        async def dispatch(client, request):
            llm = self.phase == 'llm'
            count, limit = (self.llm_attempts, 4) if llm else (self.http_attempts, 20)
            if count >= limit:
                raise RuntimeError('prerequisite request limit reached')
            paid_tavily = (self.phase == 'tavily' and request.method == 'POST')
            if paid_tavily:
                if (request.url.scheme, request.url.host, request.url.port, request.url.path) != (
                        'https', 'api.tavily.com', None, '/search'):
                    raise RuntimeError('unexpected paid probe destination')
                if self.tavily_post_attempts >= 1:
                    raise RuntimeError('prerequisite Tavily POST limit reached')
            if llm:
                self.llm_attempts += 1
            else:
                self.http_attempts += 1
            if paid_tavily:
                self.tavily_post_attempts += 1
            entry = {'phase': self.phase, 'ordinal': count + 1,
                     'method': request.method, 'started_at': now()}
            with (self.directory / 'request-admissions.jsonl').open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(entry) + '\n')
                handle.flush()
                os.fsync(handle.fileno())
            return await original(client, request)

        httpx.AsyncClient._send_single_request = dispatch
        try:
            yield self
        finally:
            httpx.AsyncClient._send_single_request = original


async def probe_llm_once() -> dict:
    """One JSON request, then one tool request; fail without paid retries."""
    from benchmarks.product_baseline_preflight import error_metadata
    from deepchoice.utils.call_diagnostics import observe_output, strict_json
    from deepchoice.utils.llm import TIERS, _get_client, deepseek_extra_body
    from deepchoice.utils.token_usage import provider_usage

    model = TIERS['deepseek-flash']['model']
    results = []
    for name in ('json', 'tools'):
        item = {'probe': name, 'passed': False, 'usage': None}
        try:
            kwargs = {'model': model, 'temperature': 0, 'max_tokens': 128,
                      'extra_body': deepseek_extra_body()}
            if name == 'json':
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
                tag='o1-json-probe' if name == 'json' else 'check')
            item['diagnostics'] = diagnostic
            item['passed'] = (tool_valid and isinstance(parsed, dict) and parsed.get('ok') is True
                and diagnostic['json_status'] == 'strict' and diagnostic['schema_status'] == 'valid'
                and diagnostic['truncated'] is False)
        except Exception as exc:
            item.update(error_metadata(exc))
        results.append(item)
        if not item['passed']:
            break
    return {'schema_version': 1, 'model_id': model, 'results': results,
            'passed': len(results) == 2 and all(item['passed'] for item in results),
            'research_runs_submitted': 0}


async def preflight(directory: Path, cfg, *, commit: str) -> dict:
    from deepchoice import outbound
    from deepchoice.outbound.resolver import ChannelResolver

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
            llm = await probe_llm_once()
            write_json(directory / 'llm-preflight.json', llm)
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


def copy_frozen_seed(seed: Path, destination: Path, expected: str) -> str:
    """Copy a stopped, verified seed byte-for-byte, without SQLite backup drift."""
    if destination.exists():
        raise ValueError('knowledge destination must be fresh')
    if seed.is_symlink() or not seed.is_dir() or set(p.name for p in seed.iterdir()) != {
            'chroma', 'learned_docs.json'}:
        raise ValueError('invalid frozen knowledge layout')
    if any(seed.rglob('*-wal')):
        raise ValueError('frozen knowledge has pending WAL')
    before = tree_hash(seed)
    if before != expected:
        raise ValueError('frozen knowledge identity mismatch')
    with sqlite3.connect((seed / 'chroma/chroma.sqlite3').resolve().as_uri()
                         + '?mode=ro&immutable=1', uri=True) as db:
        if db.execute('PRAGMA quick_check').fetchone() != ('ok',):
            raise ValueError('frozen knowledge integrity check failed')
    shutil.copytree(seed, destination)
    if tree_hash(seed) != before or tree_hash(destination) != before:
        raise ValueError('frozen knowledge changed while copying')
    return before


def prepare(root: Path, preflight_dir: Path, seed: Path, expected: str, cfg) -> dict:
    """Derive a fresh ready environment from same-candidate probe evidence."""
    if root.exists():
        raise ValueError('experiment root must be fresh')
    commit = git_identity()
    evidence = json.loads((preflight_dir / 'preflight-summary.json').read_text(encoding='utf-8'))
    if (not evidence.get('passed') or evidence.get('git_commit') != commit
            or evidence.get('proxy_sha256') != cfg.safe_fetch_proxy_sha256):
        raise ValueError('same-candidate prerequisite evidence required')
    from deepchoice.utils.llm import TIERS
    llm_path = preflight_dir / 'llm-preflight.json'
    llm = json.loads(llm_path.read_text(encoding='utf-8'))
    model = TIERS['deepseek-flash']
    if not llm.get('passed') or llm.get('model_id') != model['model']:
        raise ValueError('same-model prerequisite evidence required')
    dependencies = dependency_records()
    dependency_hash = hashlib.sha256((json.dumps(dependencies, ensure_ascii=False, indent=2)
                                     + '\n').encode()).hexdigest()
    if (evidence.get('dependency_snapshot_sha256') != dependency_hash
            or file_hash(preflight_dir / 'dependencies.json') != dependency_hash
            or evidence.get('configuration_sha256') != configuration_sha256(cfg)
            or evidence.get('model_id') != model['model']
            or evidence.get('endpoint_sha256') != hashlib.sha256(model['base'].encode()).hexdigest()):
        raise ValueError('prerequisite environment configuration drift')
    root.mkdir(parents=True)
    knowledge_hash = copy_frozen_seed(seed, root / 'serial-r1/knowledge', expected)
    (root / 'serial-r1/runtime').mkdir()
    write_json(root / 'dependencies.json', dependencies)
    from benchmarks.product_baseline import load_dataset, load_environment
    from deepchoice.contracts.api import ResearchRequest
    from deepchoice.contracts.manifest import build_core_asset_registry, build_run_manifest
    dataset, dataset_hash = load_dataset(Path('benchmarks/product-baseline-v1.json'), require_frozen=True)
    request = next(c['request'] for c in dataset['cases'] if c['id'] == 'P01')
    manifest = build_run_manifest(ResearchRequest.model_validate(request).model_dump(exclude_none=True))
    environment = {'schema_version': 1, 'status': 'ready', 'model': {
        'provider': 'deepseek-flash', 'model_id': model['model'], 'thinking': 'disabled'},
        'dependency_snapshot_sha256': file_hash(root / 'dependencies.json'),
        'knowledge_snapshot_sha256': knowledge_hash, 'retrieval_health': 'passed',
        'llm_compatibility': 'passed', 'notes': {
            'settings': {**RESOURCE_SETTINGS, 'LLM_DS_CONCURRENCY': os.getenv('LLM_DS_CONCURRENCY', '80'),
                         'DEEPCHOICE_SYNTH_THINKING': '0'},
            'git_commit': commit, 'dataset_hash': dataset_hash, 'case_id': 'P01',
            'llm_evidence_sha256': file_hash(llm_path),
            'retrieval_evidence_sha256': file_hash(preflight_dir / 'preflight-summary.json'),
            'endpoint_sha256': hashlib.sha256(model['base'].encode()).hexdigest(),
            'safe_fetch_proxy_sha256': cfg.safe_fetch_proxy_sha256,
            'configuration_sha256': configuration_sha256(cfg),
            'embedding_model': 'BAAI/bge-m3', 'embedding_revision': embedding_revision(),
            'embedding_startup_mode': 'cold-in-research', 'snapshot_copy_mode': 'byte-exact-frozen-no-wal',
            'expected_manifest_id': manifest.manifest_id,
            'core_asset_registry_id': build_core_asset_registry().registry_id,
            'price_availability': 'unavailable', 'auto_recovery': False,
            'qualification_mode': 'single-admission-v1',
            'hitl_mode': 'stop-at-hitl', 'task_admission_limit': 1}}
    write_json(root / 'environment.json', environment)
    load_environment(root / 'environment.json', require_ready=True)
    return {'prepared': True, 'knowledge_sha256': knowledge_hash,
            'expected_manifest_id': manifest.manifest_id}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('preflight', 'prepare'))
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--trust-current-local-proxy', action='store_true')
    parser.add_argument('--execute-paid-probes', action='store_true')
    parser.add_argument('--preflight-dir')
    parser.add_argument('--frozen-seed')
    parser.add_argument('--expected-knowledge-sha256')
    args = parser.parse_args()
    if not args.trust_current_local_proxy:
        parser.error('explicit trusted local proxy opt-in required')
    try:
        cfg = trusted_configuration()
        if args.command == 'preflight':
            if not args.execute_paid_probes:
                parser.error('paid prerequisite permission required')
            result = asyncio.run(preflight(Path(args.output_dir), cfg, commit=git_identity()))
            print(json.dumps(result), flush=True)
            return 0 if result['passed'] else 1
        if not all((args.preflight_dir, args.frozen_seed, args.expected_knowledge_sha256)):
            parser.error('prepare requires probe evidence and frozen knowledge identity')
        print(json.dumps(prepare(Path(args.output_dir), Path(args.preflight_dir),
            Path(args.frozen_seed), args.expected_knowledge_sha256, cfg)), flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({'error_type': type(exc).__name__, 'research_runs_submitted': 0}), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
