from __future__ import annotations

import json
import hashlib
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from benchmarks.product_baseline_experiment import copy_knowledge, tree_hash, serve
from benchmarks import product_baseline_experiment as experiment
from deepchoice.outbound.channels import OutboundConfig


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    # These startup tests must never read developer secrets or start services.
    monkeypatch.setattr(experiment, "load_dotenv", lambda: False)
    monkeypatch.delenv("SAFE_FETCH_TRUSTED_LOCAL_PROXY", raising=False)


def startup_notes(**extra):
    return {"settings": {**experiment.RESOURCE_SETTINGS, "LLM_DS_CONCURRENCY": "80",
                         "DEEPCHOICE_SYNTH_THINKING": "0"}, **extra}


def write_notes(root, notes):
    (root / "environment.json").write_text(json.dumps({"notes": notes}), encoding="utf-8")


def fake_startup(root, monkeypatch, *, mode="prewarmed", legacy=False, dimension=1024):
    chroma, learned = make_knowledge(root)
    knowledge = root / "serial-r1" / "knowledge"
    identity = copy_knowledge(chroma, learned, knowledge)
    (root / "serial-r1" / "runtime").mkdir()
    model = {"model": "fixture-model", "base": "https://llm.example.test"}
    notes = startup_notes(endpoint_sha256=hashlib.sha256(model["base"].encode()).hexdigest(),
                          embedding_revision="1" * 40)
    if not legacy:
        notes.update(embedding_startup_mode=mode, safe_fetch_proxy_sha256=None)
    environment = {"notes": notes, "knowledge_snapshot_sha256": identity,
                   "model": {"model_id": model["model"]}}
    (root / "environment.json").write_text(json.dumps(environment), encoding="utf-8")
    calls = {"threads": [], "warmup": [], "server": [], "environment": []}
    monkeypatch.setattr(experiment, "embedding_revision", lambda: "1" * 40)
    monkeypatch.setitem(sys.modules, "benchmarks.product_baseline", SimpleNamespace(
        load_environment=lambda path, **kwargs: calls["environment"].append((path, kwargs))))
    monkeypatch.setitem(sys.modules, "deepchoice.utils.llm", SimpleNamespace(TIERS={"deepseek-flash": model}))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        set_num_threads=lambda value: calls["threads"].append(("intra", value)),
        set_num_interop_threads=lambda value: calls["threads"].append(("interop", value))))
    def embedding_model():
        calls["warmup"].append("load")
        def encode(value):
            calls["warmup"].append(value)
            return [0] * dimension
        return SimpleNamespace(encode=encode)
    monkeypatch.setitem(sys.modules, "deepchoice.utils.embedding", SimpleNamespace(get_embedding_model=embedding_model))
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(
        run=lambda *args, **kwargs: calls["server"].append((args, kwargs))))
    return calls


def make_knowledge(root: Path):
    chroma = root / "source"
    chroma.mkdir()
    with sqlite3.connect(chroma / "chroma.sqlite3") as connection:
        connection.execute("CREATE TABLE fixture(value TEXT)")
        connection.execute("INSERT INTO fixture VALUES ('seed')")
    learned = root / "learned.json"
    learned.write_text('{"fixture":"https://example.com/docs"}')
    return chroma, learned


def test_snapshot_copy_is_identical_and_source_is_unchanged(tmp_path):
    chroma, learned = make_knowledge(tmp_path)
    before = tree_hash(chroma)
    identity = copy_knowledge(chroma, learned, tmp_path / "snapshot")
    assert identity == tree_hash(tmp_path / "snapshot")
    assert tree_hash(chroma) == before
    assert (tmp_path / "snapshot" / "learned_docs.json").read_bytes() == learned.read_bytes()
    with sqlite3.connect(tmp_path / "snapshot" / "chroma" / "chroma.sqlite3") as connection:
        assert connection.execute("SELECT value FROM fixture").fetchone() == ("seed",)
    with pytest.raises(ValueError, match="fresh"):
        copy_knowledge(chroma, learned, tmp_path / "snapshot")


def test_snapshot_rejects_pending_wal_without_modifying_source(tmp_path):
    chroma, learned = make_knowledge(tmp_path)
    (chroma / "chroma.sqlite3-wal").write_bytes(b"pending")
    with pytest.raises(ValueError, match="pending WAL"):
        copy_knowledge(chroma, learned, tmp_path / "snapshot")
    assert not (tmp_path / "snapshot").exists()


def test_serve_rejects_non_allowlisted_settings_before_native_import(tmp_path):
    (tmp_path / "environment.json").write_text(json.dumps({"notes": {"settings": {"SECRET_KEY": "test"}}}))
    with pytest.raises(ValueError, match="allowlist"):
        serve(tmp_path, "serial-r1", 8011)


def test_cold_serve_does_not_load_or_encode_embeddings_but_keeps_thread_limits(tmp_path, monkeypatch, capsys):
    calls = fake_startup(tmp_path, monkeypatch, mode="cold-in-research")
    serve(tmp_path, "serial-r1", 8011, "cold-in-research")
    assert calls["warmup"] == []
    assert calls["threads"] == [("intra", 1), ("interop", 1)]
    assert len(calls["server"]) == 1
    assert calls["server"][0][1]["workers"] == 1
    assert calls["environment"][0][1] == {"require_ready": True}
    assert json.loads(capsys.readouterr().out) == {
        "embedding_warmed": False, "embedding_startup_mode": "cold-in-research", "profile": "serial-r1"}


def test_qualification_check_uses_isolated_paths_and_rejects_before_model_or_service(tmp_path, monkeypatch):
    from benchmarks import product_baseline_qualification as qualification
    calls = fake_startup(tmp_path, monkeypatch, mode='cold-in-research')
    path = tmp_path / 'environment.json'
    environment = json.loads(path.read_text())
    environment['notes']['qualification_mode'] = 'single-admission-v1'
    path.write_text(json.dumps(environment))
    def verify(_environment):
        assert experiment.os.environ['CHROMA_PATH'] == str((tmp_path / 'serial-r1/knowledge/chroma').resolve())
        assert experiment.os.environ['LEARNED_DOCS_PATH'] == str((tmp_path / 'serial-r1/knowledge/learned_docs.json').resolve())
        assert experiment.os.environ['DEEPCHOICE_EXPERIMENT_DIR'] == str((tmp_path / 'serial-r1/runtime').resolve())
        raise ValueError('frozen qualification environment drift')
    monkeypatch.setattr(qualification, 'verify_frozen_environment', verify)
    with pytest.raises(ValueError, match='environment drift'):
        serve(tmp_path, 'serial-r1', 8011, 'cold-in-research')
    assert calls['warmup'] == calls['server'] == calls['threads'] == []


@pytest.mark.parametrize("legacy", [False, True])
def test_default_serve_preserves_frozen_and_legacy_prewarm(tmp_path, monkeypatch, capsys, legacy):
    calls = fake_startup(tmp_path, monkeypatch, legacy=legacy)
    serve(tmp_path, "serial-r1", 8011)
    assert calls["warmup"] == ["load", "O1 embedding prerequisite"]
    assert len(calls["server"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["embedding_warmed"] is True
    assert output["embedding_startup_mode"] == "prewarmed"
    assert isinstance(output["embedding_warmup_ms"], int)


@pytest.mark.parametrize(("frozen", "requested"), [
    ("prewarmed", "cold-in-research"), ("cold-in-research", "prewarmed"),
    ("unknown", "prewarmed"), (None, "cold-in-research"),
])
def test_startup_mode_drift_is_rejected_before_knowledge_or_native_startup(tmp_path, frozen, requested):
    notes = startup_notes()
    if frozen is not None:
        notes["embedding_startup_mode"] = frozen
    write_notes(tmp_path, notes)
    with pytest.raises(ValueError, match="startup mode"):
        serve(tmp_path, "serial-r1", 8011, requested)
    assert not (tmp_path / "serial-r1").exists()


@pytest.mark.parametrize(("frozen_proxy", "active_proxy"), [
    (None, "http://127.0.0.1:7890"),
    ("http://127.0.0.1:7890", None),
    ("http://127.0.0.1:7890", "http://127.0.0.1:7891"),
])
def test_proxy_identity_drift_rejected_before_knowledge_or_native_startup(tmp_path, monkeypatch, frozen_proxy, active_proxy):
    frozen_hash = OutboundConfig(safe_fetch_trusted_local_proxy=frozen_proxy).safe_fetch_proxy_sha256
    write_notes(tmp_path, startup_notes(safe_fetch_proxy_sha256=frozen_hash))
    if active_proxy is not None:
        monkeypatch.setenv("SAFE_FETCH_TRUSTED_LOCAL_PROXY", active_proxy)
    with pytest.raises(ValueError, match="proxy configuration"):
        serve(tmp_path, "serial-r1", 8011)
    assert not (tmp_path / "serial-r1").exists()


def test_legacy_environment_cannot_authorize_new_proxy_trust(tmp_path, monkeypatch):
    write_notes(tmp_path, startup_notes())
    monkeypatch.setenv("SAFE_FETCH_TRUSTED_LOCAL_PROXY", "http://127.0.0.1:7890")
    with pytest.raises(ValueError, match="legacy environment"):
        serve(tmp_path, "serial-r1", 8011)


def test_current_proxy_identity_can_match_frozen_normalized_endpoint(monkeypatch):
    monkeypatch.setenv("SAFE_FETCH_TRUSTED_LOCAL_PROXY", "http://[0:0:0:0:0:0:0:1]:07890")
    frozen_hash = OutboundConfig(safe_fetch_trusted_local_proxy="http://[::1]:7890").safe_fetch_proxy_sha256
    experiment._verify_startup_notes(startup_notes(safe_fetch_proxy_sha256=frozen_hash), "prewarmed")


@pytest.mark.parametrize("identity", [False, 123, "not-a-sha256"])
def test_invalid_frozen_proxy_identity_is_rejected(identity):
    with pytest.raises(ValueError, match="identity is invalid"):
        experiment._verify_startup_notes(startup_notes(safe_fetch_proxy_sha256=identity), "prewarmed")


def test_prewarm_dimension_failure_still_prevents_server_start(tmp_path, monkeypatch):
    calls = fake_startup(tmp_path, monkeypatch, dimension=1023)
    with pytest.raises(ValueError, match="dimension"):
        serve(tmp_path, "serial-r1", 8011)
    assert calls["server"] == []


@pytest.mark.parametrize("mode", ["prewarmed", "cold-in-research"])
def test_serve_cli_passes_explicit_startup_mode(tmp_path, monkeypatch, mode):
    calls = []
    monkeypatch.setattr(experiment, "serve", lambda *args: calls.append(args))
    monkeypatch.setattr(sys, "argv", ["experiment", "serve", "--root", str(tmp_path),
                                    "--profile", "serial-r1", "--embedding-startup-mode", mode])
    assert experiment.main() == 0
    assert calls == [(tmp_path.resolve(), "serial-r1", 8011, mode)]


@pytest.mark.asyncio
async def test_prepare_freezes_proxy_identity_and_default_mode_without_extra_probes(tmp_path, monkeypatch):
    chroma, learned = make_knowledge(tmp_path)
    monkeypatch.setenv("CHROMA_PATH", str(chroma))
    monkeypatch.setenv("LEARNED_DOCS_PATH", str(learned))
    monkeypatch.setenv("DEEPCHOICE_SYNTH_THINKING", "0")
    monkeypatch.setenv("SAFE_FETCH_TRUSTED_LOCAL_PROXY", "http://127.0.0.1:7890")
    evidence = tmp_path / "probe.json"
    evidence.write_text(json.dumps({"passed": True, "model_id": "fixture-model"}), encoding="utf-8")
    calls = []
    async def health():
        calls.append("health")
        return {"ok": True, "tavily_direct": {"ok": True}, "sources": {}}
    monkeypatch.setitem(sys.modules, "benchmarks.run_baseline", SimpleNamespace(health_check_report=health))
    monkeypatch.setitem(sys.modules, "deepchoice.utils.llm", SimpleNamespace(TIERS={"deepseek-flash": {
        "model": "fixture-model", "base": "https://llm.example.test"}}))
    monkeypatch.setattr(experiment, "distributions", lambda: [])
    monkeypatch.setattr(experiment, "embedding_revision", lambda: "1" * 40)
    root = tmp_path / "experiment"
    result = await experiment.prepare(root, evidence)
    notes = json.loads((root / "environment.json").read_text(encoding="utf-8"))["notes"]
    assert result["prepared"] is True
    assert notes["embedding_startup_mode"] == "prewarmed"
    assert notes["safe_fetch_proxy_sha256"] == OutboundConfig.from_env().safe_fetch_proxy_sha256
    assert calls == ["health"]
