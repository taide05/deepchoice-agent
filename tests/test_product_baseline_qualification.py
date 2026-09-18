from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import httpx
from openai import AsyncOpenAI
import pytest

from benchmarks import product_baseline_qualification as qualification
from benchmarks.product_baseline_experiment import tree_hash
from deepchoice.outbound.channels import OutboundConfig


async def test_request_caps_stop_before_dispatch_and_carrier_does_not_spend_tavily(tmp_path):
    seen = []
    budget = qualification.PrerequisiteBudget(tmp_path)
    transport = httpx.MockTransport(lambda request: (seen.append(request) or httpx.Response(200)))
    async with httpx.AsyncClient(transport=transport) as client:
        with budget.install():
            await client.post('https://forward.invalid')
            assert budget.tavily_post_attempts == 0
            budget.phase = 'tavily'
            await client.post('https://api.tavily.com/search')
            with pytest.raises(RuntimeError, match='POST limit'):
                await client.post('https://api.tavily.com/search')
            assert len(seen) == 2
            budget.phase = 'routing'
            for _ in range(18):
                await client.get('https://example.com')
            with pytest.raises(RuntimeError, match='request limit'):
                await client.get('https://example.com')
            budget.phase = 'llm'
            for _ in range(4):
                await client.post('https://model.invalid')
            with pytest.raises(RuntimeError, match='request limit'):
                await client.post('https://model.invalid')
    assert len(seen) == 24
    assert budget.counts() == {'http_attempts': 20, 'tavily_post_attempts': 1, 'llm_attempts': 4}
    entries = [json.loads(line) for line in (tmp_path / 'request-admissions.jsonl').read_text().splitlines()]
    assert len(entries) == 24 and all(set(e) == {'phase', 'ordinal', 'method', 'started_at'} for e in entries)


async def test_degraded_routes_never_probe_paid_services(tmp_path, monkeypatch):
    from deepchoice import outbound
    from deepchoice.outbound.resolver import ChannelResolver
    async def health(_self):
        return {'ok': False, 'sources': {'arxiv': {'ok': False, 'status': 'rate_limited'}}}
    monkeypatch.setattr(ChannelResolver, 'health_check', health)
    previous = outbound._resolver
    result = await qualification.preflight(tmp_path / 'preflight', OutboundConfig(), commit='fixture')
    assert not result['passed'] and result['stop_reason'] == 'retrieval_routes_degraded'
    assert result['llm_attempts'] == result['tavily_post_attempts'] == result['research_runs_submitted'] == 0
    assert outbound._resolver is previous
    assert json.loads((tmp_path / 'preflight/preflight-summary.json').read_text()) == result


def sdk_fixture(monkeypatch, *, status=200, finish='stop'):
    from deepchoice.utils import llm
    seen = []
    def handler(request):
        data = json.loads(request.content)
        seen.append(data)
        if status != 200:
            return httpx.Response(status, json={'error': {'message': 'Bearer private-secret',
                                                        'type': 'fixture_error'}})
        tool = 'tools' in data
        message = {'role': 'assistant', 'content': None if tool else '{"ok":true}'}
        if tool:
            message['tool_calls'] = [{'id': 'check-1', 'type': 'function', 'function': {
                'name': 'check', 'arguments': '{"ok":true}'}}]
        return httpx.Response(200, json={'id': 'fixture', 'created': 0, 'object': 'chat.completion',
            'model': data['model'], 'choices': [{'index': 0, 'message': message,
                'finish_reason': 'tool_calls' if tool else finish}],
            'usage': {'prompt_tokens': 3, 'completion_tokens': 2, 'total_tokens': 5}})
    def client(timeout, max_retries):
        assert max_retries == 0
        return AsyncOpenAI(api_key='fixture', base_url='https://model.invalid/v1',
            timeout=timeout, max_retries=max_retries,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(llm, '_get_client', client)
    return seen


async def test_native_json_and_tool_probe_records_usage_without_content(tmp_path, monkeypatch):
    seen = sdk_fixture(monkeypatch)
    budget = qualification.PrerequisiteBudget(tmp_path)
    budget.phase = 'llm'
    with budget.install():
        result = await qualification.probe_llm_once()
    assert result['passed'] and len(seen) == budget.llm_attempts == 2
    assert all(item['usage']['total_tokens'] == 5 for item in result['results'])
    assert all(item['diagnostics']['truncated'] is False for item in result['results'])
    assert all(data['extra_body']['thinking']['type'] == 'disabled' if 'extra_body' in data
               else data['thinking']['type'] == 'disabled' for data in seen)
    assert 'messages' not in str(result) and '{"ok":true}' not in str(result)


@pytest.mark.parametrize('status,finish', [(429, 'stop'), (503, 'stop'), (200, 'length')])
async def test_probe_failure_or_truncation_is_one_request_no_tool_no_retry(tmp_path, monkeypatch, status, finish):
    seen = sdk_fixture(monkeypatch, status=status, finish=finish)
    budget = qualification.PrerequisiteBudget(tmp_path)
    budget.phase = 'llm'
    with budget.install():
        result = await qualification.probe_llm_once()
    assert not result['passed'] and len(seen) == budget.llm_attempts == len(result['results']) == 1
    assert 'private-secret' not in str(result)


def seed_fixture(root: Path):
    seed = root / 'seed'
    (seed / 'chroma').mkdir(parents=True)
    with sqlite3.connect(seed / 'chroma/chroma.sqlite3') as db:
        db.execute('CREATE TABLE fixture(value TEXT)')
        db.execute("INSERT INTO fixture VALUES ('frozen')")
    (seed / 'learned_docs.json').write_text('{}')
    return seed


def test_byte_copy_preserves_frozen_sqlite_identity_and_original(tmp_path):
    seed = seed_fixture(tmp_path)
    expected = tree_hash(seed)
    original = (seed / 'chroma/chroma.sqlite3').read_bytes()
    assert qualification.copy_frozen_seed(seed, tmp_path / 'copy', expected) == expected
    assert tree_hash(seed) == tree_hash(tmp_path / 'copy') == expected
    assert (tmp_path / 'copy/chroma/chroma.sqlite3').read_bytes() == original
    with pytest.raises(ValueError, match='fresh'):
        qualification.copy_frozen_seed(seed, tmp_path / 'copy', expected)


def test_seed_wal_and_identity_mismatch_rejected_before_copy(tmp_path):
    seed = seed_fixture(tmp_path)
    expected = tree_hash(seed)
    with pytest.raises(ValueError, match='identity'):
        qualification.copy_frozen_seed(seed, tmp_path / 'mismatch', '0' * 64)
    (seed / 'chroma/chroma.sqlite3-wal').write_bytes(b'pending')
    with pytest.raises(ValueError, match='WAL'):
        qualification.copy_frozen_seed(seed, tmp_path / 'copy', expected)
    assert not (tmp_path / 'copy').exists() and not (tmp_path / 'mismatch').exists()


def test_preparation_refuses_wrong_candidate_without_creating_output(tmp_path, monkeypatch):
    evidence = tmp_path / 'preflight'
    evidence.mkdir()
    qualification.write_json(evidence / 'preflight-summary.json', {'passed': True,
                            'git_commit': 'old', 'proxy_sha256': None})
    monkeypatch.setattr(qualification, 'git_identity', lambda: 'new')
    with pytest.raises(ValueError, match='same-candidate'):
        qualification.prepare(tmp_path / 'experiment', evidence, tmp_path / 'unused', '0' * 64,
                              OutboundConfig())
    assert not (tmp_path / 'experiment').exists()


@pytest.mark.parametrize('drift', [None, 'dependencies', 'configuration', 'endpoint'])
def test_preparation_binds_probe_environment_and_preserves_seed(tmp_path, monkeypatch, drift):
    from deepchoice.utils.llm import TIERS
    seed = seed_fixture(tmp_path)
    expected = tree_hash(seed)
    cfg = OutboundConfig()
    evidence = tmp_path / 'preflight'
    evidence.mkdir()
    qualification.write_json(evidence / 'dependencies.json', qualification.dependency_records())
    model = TIERS['deepseek-flash']
    summary = {'passed': True, 'git_commit': 'fixture', 'proxy_sha256': None,
               'configuration_sha256': qualification.configuration_sha256(cfg),
               'dependency_snapshot_sha256': qualification.file_hash(evidence / 'dependencies.json'),
               'model_id': model['model'],
               'endpoint_sha256': qualification.hashlib.sha256(model['base'].encode()).hexdigest()}
    if drift:
        field = {'dependencies': 'dependency_snapshot_sha256', 'configuration': 'configuration_sha256',
                 'endpoint': 'endpoint_sha256'}[drift]
        summary[field] = '0' * 64
    qualification.write_json(evidence / 'preflight-summary.json', summary)
    qualification.write_json(evidence / 'llm-preflight.json', {'passed': True, 'model_id': model['model']})
    monkeypatch.setattr(qualification, 'git_identity', lambda: 'fixture')
    monkeypatch.setattr(qualification, 'embedding_revision', lambda: 'a' * 40)
    output = tmp_path / 'experiment'
    if drift:
        with pytest.raises(ValueError, match='drift'):
            qualification.prepare(output, evidence, seed, expected, cfg)
        assert not output.exists()
    else:
        result = qualification.prepare(output, evidence, seed, expected, cfg)
        environment = json.loads((output / 'environment.json').read_text())
        assert result['prepared'] and tree_hash(output / 'serial-r1/knowledge') == expected
        assert not list((output / 'serial-r1/runtime').iterdir())
        assert environment['notes']['embedding_startup_mode'] == 'cold-in-research'
        assert environment['notes']['expected_manifest_id'] == result['expected_manifest_id']
        assert environment['notes']['hitl_mode'] == 'stop-at-hitl'
        assert qualification.verify_frozen_environment(environment, cfg) == result['expected_manifest_id']
        environment['notes']['expected_manifest_id'] = '0' * 64
        with pytest.raises(ValueError, match='assets or request drift'):
            qualification.verify_frozen_environment(environment, cfg)
        environment['notes']['expected_manifest_id'] = result['expected_manifest_id']
        environment['dependency_snapshot_sha256'] = '0' * 64
        with pytest.raises(ValueError, match='environment drift'):
            qualification.verify_frozen_environment(environment, cfg)
        environment['dependency_snapshot_sha256'] = summary['dependency_snapshot_sha256']
        environment['notes']['settings']['HF_HUB_OFFLINE'] = '0'
        with pytest.raises(ValueError, match='resource settings drift'):
            qualification.verify_frozen_environment(environment, cfg)
    assert tree_hash(seed) == expected
