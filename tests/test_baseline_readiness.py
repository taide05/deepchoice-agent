"""No-network regression tests for the retired measurement entry points."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from benchmarks import run_baseline as legacy


def test_retired_generator_import_and_cli_do_not_write(monkeypatch, tmp_path):
    import runpy
    from pathlib import Path

    target = Path(legacy.__file__).with_name("generate_200_cases.py")
    def forbidden(*args, **kwargs):
        raise AssertionError("Retired generator must never write a dataset")
    monkeypatch.setattr(Path, "write_text", forbidden)
    namespace = runpy.run_path(str(target))
    with pytest.raises(SystemExit):
        namespace["main"]()


@pytest.mark.asyncio
async def test_diagnostic_case_and_tag_cannot_escape_output_directory(monkeypatch, tmp_path):
    callbacks = []
    monkeypatch.setattr(legacy, "set_record_callback", callbacks.append)
    destination = tmp_path / "diagnostics"
    legacy._setup_debug_dump(destination)
    await callbacks[0]({"case_id": "../../escape", "tag": "../../../outside", "response_chars": 0})
    files = list(tmp_path.rglob("*.json"))
    assert len(files) == 1
    assert files[0].is_relative_to(destination)
    assert len(files[0].parent.name) == 64


def test_existing_diagnostics_prevent_dispatch_and_preserve_records(monkeypatch, tmp_path):
    sentinel = tmp_path / "existing.json"
    sentinel.write_text("historical", encoding="utf-8")
    health = AsyncMock()
    execute = AsyncMock()
    monkeypatch.setattr(legacy, "RUNS_DIR", legacy.RUNS_DIR)
    monkeypatch.setattr(legacy, "health_check_report", health)
    monkeypatch.setattr(legacy, "run_baseline", execute)
    with pytest.raises(SystemExit) as caught:
        legacy.main(["--legacy-direct", "--output-dir", str(tmp_path / "new"), "--debug-dump-dir", str(tmp_path)])
    assert caught.value.code == 2
    assert sentinel.read_text(encoding="utf-8") == "historical"
    health.assert_not_called()
    execute.assert_not_called()


@pytest.mark.parametrize("argv", [[], ["--skip-health-check"], ["--merge"], ["--legacy-direct"]])
def test_unqualified_legacy_cli_stops_before_calls_or_files(monkeypatch, tmp_path, argv):
    health = AsyncMock()
    execute = AsyncMock()
    monkeypatch.setattr(legacy, "health_check_report", health)
    monkeypatch.setattr(legacy, "run_baseline", execute)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as caught:
        legacy.main(argv)
    assert caught.value.code == 2
    health.assert_not_called()
    execute.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_existing_legacy_output_is_never_overwritten(monkeypatch, tmp_path):
    sentinel = tmp_path / "runs-full.json"
    sentinel.write_text("historical", encoding="utf-8")
    execute = AsyncMock()
    monkeypatch.setattr(legacy, "run_baseline", execute)
    with pytest.raises(SystemExit):
        legacy.main(["--legacy-direct", "--output-dir", str(tmp_path), "--skip-health-check"])
    assert sentinel.read_text(encoding="utf-8") == "historical"
    execute.assert_not_called()


def test_explicit_legacy_cli_uses_isolated_output(monkeypatch, tmp_path):
    destination = tmp_path / "new-run"
    execute = AsyncMock(return_value=destination / "report.json")
    monkeypatch.setattr(legacy, "run_baseline", execute)
    monkeypatch.setattr(legacy, "RUNS_DIR", legacy.RUNS_DIR)
    legacy.main(["--legacy-direct", "--output-dir", str(destination), "--skip-health-check", "--cases", "1"])
    assert legacy.RUNS_DIR == destination
    execute.assert_awaited_once()
    assert execute.await_args.kwargs["n_cases"] == 1


def test_health_only_preserves_compatibility_without_starting_research(monkeypatch, tmp_path):
    health = AsyncMock(return_value=0)
    execute = AsyncMock()
    monkeypatch.setattr(legacy, "run_health_check", health)
    monkeypatch.setattr(legacy, "run_baseline", execute)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as caught:
        legacy.main(["--health-check"])
    assert caught.value.code == 0
    health.assert_awaited_once()
    execute.assert_not_called()
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_legacy_failure_artifact_does_not_expose_exception(monkeypatch, capsys):
    orchestrator = MagicMock()
    orchestrator.run_research_task = AsyncMock(side_effect=RuntimeError("credential-canary"))
    monkeypatch.setattr(legacy, "ChiefEditorAgent", lambda *_: orchestrator)
    result = await legacy.run_single_case({"id": "private-case-id", "query": "private-query-canary"}, verbose=True)
    assert result["error"] == "RuntimeError"
    stripped = legacy._strip_run(result)
    assert stripped["execution_path"] == "legacy-direct-graph"
    output = capsys.readouterr().out
    assert "credential-canary" not in str(stripped) + output
    assert "private-query-canary" not in output
    assert "private-case-id" not in output


@pytest.mark.parametrize("status", [404, 200, 500])
def test_readonly_load_probe_uses_durable_route_and_expected_404(status, monkeypatch):
    # Exercise our HTTP callback without Locust's process-wide gevent patches.
    # Native load-runtime compatibility is separate from this unit contract.
    import runpy
    import sys
    from pathlib import Path
    from types import ModuleType

    locust = ModuleType("locust")
    locust.HttpUser = object
    locust.between = lambda *_: None
    locust.task = lambda *_: lambda callback: callback
    monkeypatch.setitem(sys.modules, "locust", locust)
    namespace = runpy.run_path(str(Path(legacy.__file__).with_name("locustfile.py")))
    DeepChoiceUser = namespace["DeepChoiceUser"]

    response = MagicMock(status_code=status)
    request = MagicMock()
    request.__enter__.return_value = response
    client = MagicMock()
    client.get.return_value = request
    DeepChoiceUser.task_status(SimpleNamespace(client=client))
    client.get.assert_called_once_with("/api/v1/tasks/nonexistent", catch_response=True)
    if status == 404:
        response.success.assert_called_once()
        response.failure.assert_not_called()
    else:
        response.failure.assert_called_once()
