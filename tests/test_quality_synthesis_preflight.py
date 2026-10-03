from __future__ import annotations
import json

import httpx
from openai import AsyncOpenAI
import pytest

from benchmarks import quality_synthesis_preflight as qualification
from deepchoice.outbound.channels import OutboundConfig

def sdk_fixture(monkeypatch, *, status=200, finish='stop', native_finish='stop', native_reasoning='private reasoning sentinel'):
    from deepchoice.utils import llm
    seen = []
    def handler(request):
        data = json.loads(request.content)
        seen.append(data)
        if status != 200:
            return httpx.Response(status, json={'error': {'message': 'Bearer private-secret',
                                                        'type': 'fixture_error'}})
        tool = 'tools' in data
        native = data.get('thinking', {}).get('type') == 'enabled'
        message = {'role': 'assistant', 'content': None if tool else '{"ok":true}'}
        if native:
            message['reasoning_content'] = native_reasoning
        if tool:
            message['tool_calls'] = [{'id': 'check-1', 'type': 'function', 'function': {
                'name': 'check', 'arguments': '{"ok":true}'}}]
        return httpx.Response(200, json={'id': 'fixture', 'created': 0, 'object': 'chat.completion',
            'model': data['model'], 'choices': [{'index': 0, 'message': message,
                'finish_reason': 'tool_calls' if tool else native_finish if native else finish}],
            'usage': {'prompt_tokens': 3, 'completion_tokens': 2, 'total_tokens': 5}})
    def client(timeout, max_retries):
        assert max_retries == 0
        return AsyncOpenAI(api_key='fixture', base_url='https://model.invalid/v1',
            timeout=timeout, max_retries=max_retries,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(llm, '_get_client', client)
    return seen

async def test_native_synthesis_probe_is_explicit_and_discards_reasoning(tmp_path, monkeypatch):
    from deepchoice.utils.llm import max_output_tokens_for
    seen = sdk_fixture(monkeypatch)
    budget = qualification.PrerequisiteBudget(tmp_path)
    budget.phase = 'llm'
    with budget.install():
        result = await qualification.probe_llm_once(synthesis_thinking=True)
    assert result['passed'] and result['research_runs_submitted'] == 0
    assert budget.llm_attempts == len(seen) == 3
    assert [row['thinking']['type'] for row in seen] == ['disabled', 'disabled', 'enabled']
    assert seen[-1]['reasoning_effort'] == 'high'
    assert seen[-1]['seed'] == 0
    assert seen[-1]['max_tokens'] == max_output_tokens_for('conclusion_synthesizer') == 4096
    assert result['results'][-1]['reasoning_chars'] > 0
    assert result['results'][-1]['call_contract'] == qualification.synthesis_probe_contract()
    assert 'private reasoning sentinel' not in json.dumps(result)

@pytest.mark.parametrize(("finish", "reasoning"), [("length", "thinking"), ("stop", None)])
async def test_native_probe_rejects_truncation_or_ignored_mode(monkeypatch, finish, reasoning):
    seen = sdk_fixture(monkeypatch, native_finish=finish, native_reasoning=reasoning)
    result = await qualification.probe_llm_once(synthesis_thinking=True)
    assert len(seen) == 3 and not result['passed']
    assert [item['passed'] for item in result['results']] == [True, True, False]

@pytest.mark.parametrize(('environment', 'mode'), [('1', False), ('0', False), ('0', True)])
async def test_preflight_mode_drift_fails_before_output_or_network(tmp_path, monkeypatch, environment, mode):
    monkeypatch.setenv('DEEPCHOICE_SYNTH_THINKING', environment)
    seen = sdk_fixture(monkeypatch)
    with pytest.raises(ValueError, match='synthesis mode'):
        await qualification.preflight(tmp_path / 'probe', OutboundConfig(), commit='fixture', synthesis_thinking=mode)
    assert not (tmp_path / 'probe').exists() and not seen
    if mode is False:
        with pytest.raises(ValueError, match='synthesis mode'):
            await qualification.probe_llm_once(synthesis_thinking=False)
        assert not seen

def test_native_cli_requires_explicit_paid_opt_in(tmp_path, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "argv", ["probe", "--output-dir", str(tmp_path / "out")])
    with pytest.raises(SystemExit) as caught:
        qualification.main()
    assert caught.value.code == 2
    assert not (tmp_path / "out").exists()


def test_native_cli_connects_frozen_mode(tmp_path, monkeypatch):
    import os
    import sys
    monkeypatch.setenv("DEEPCHOICE_SYNTH_THINKING", "0")
    monkeypatch.setattr(sys, "argv", ["probe", "--output-dir", str(tmp_path / "out"),
                                   "--execute-paid-probes", "--trust-current-local-proxy"])
    captured = {}
    def config():
        assert os.environ["DEEPCHOICE_SYNTH_THINKING"] == "1"
        return "cfg"
    async def preflight(path, cfg, **kwargs):
        captured.update(path=path, cfg=cfg, **kwargs)
        return {"passed": True}
    monkeypatch.setattr(qualification, "trusted_configuration", config)
    monkeypatch.setattr(qualification, "preflight", preflight)
    monkeypatch.setattr(qualification, "git_identity", lambda: "commit")
    assert qualification.main() == 0
    assert captured == {"path": tmp_path / "out", "cfg": "cfg", "commit": "commit"}
