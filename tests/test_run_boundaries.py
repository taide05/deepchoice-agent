"""Offline boundary tests for the no-model-load and final-stop fixes.

Four paths are covered, each with a real mechanism rather than a timing stand-in:

1. All indexed material is evaluation material: no model load, no encoding, no
   external request, and the envelope says "empty" rather than "failed".
2. Research material exists but the local model does not: the source fails
   promptly with an explicit reason, no hub access happens, and the event loop
   keeps running while the synchronous load attempt is in progress.
3. A dedicated child process is blocked in synchronous work when the deadline
   passes: the launcher's guard stops only that child, confirms the exit and
   records the deadline and the actual exit time.
4. A normal run (model available, child finishes before the deadline) retrieves
   and is not killed.
"""
import asyncio
import json
import pathlib
import socket
import subprocess
import sys
import textwrap
import threading
import time

import pytest

from deepchoice import run_guard


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Keep the process-global run record and model state from leaking between tests."""
    yield
    import deepchoice.utils.embedding as embedding

    embedding.reset_embedding_model_state()
    import run_limits

    run_limits._run_dir = None
    run_limits._task_id = None
    run_limits._state.update({
        "run_started_at": None,
        "run_started_at_epoch": None,
        "stop_reason": None,
        "stop_at": None,
        "counts_at_start": None,
        "events": [],
    })


def _no_network(recorder, label):
    def fail(*args, **kwargs):
        recorder.append(label)
        raise AssertionError(f"external network access attempted: {label}")
    return fail


def _is_loopback(address) -> bool:
    host = address[0] if isinstance(address, tuple) else str(address)
    return str(host) in ("127.0.0.1", "::1", "localhost", "0.0.0.0", "")


class FakeCollection:
    """Metadata-only fake of a Chroma collection."""

    def __init__(self, metadatas, documents=None):
        self.metadatas = metadatas
        self.documents = documents or [["body"] * len(metadatas)][0]
        self.queries = 0
        self.deleted = 0

    def get(self, **kwargs):
        return {"ids": [f"id{i}" for i in range(len(self.metadatas))],
                "metadatas": self.metadatas}

    def query(self, **kwargs):
        self.queries += 1
        return {"ids": [[f"id{i}" for i in range(len(self.metadatas))]],
                "metadatas": [self.metadatas],
                "documents": [self.documents]}

    def delete(self, **kwargs):
        self.deleted += 1


class FakeModel:
    def __init__(self):
        self.encodes = 0

    class _Arr(list):
        def tolist(self):
            return list(self)

    def encode(self, texts):
        self.encodes += 1
        return self._Arr([[0.1] * 4 for _ in texts])


def _kb_with(metadatas):
    from deepchoice.retrievers.chroma_kb import ChromaKB

    kb = ChromaKB.__new__(ChromaKB)
    kb.collection = FakeCollection(metadatas)
    return kb


BENCHMARK_META = {
    "title": "redis-vs-memcached",
    "url": "file:///kb/data/benchmark_answers/redis-vs-memcached.md",
    "provenance": "benchmark_ground_truth",
    "source_type": "benchmark_answers",
    "channel": "local_kb",
    "date": "",
}
RESEARCH_META = {
    "title": "Real local doc",
    "url": "file:///kb/data/blogs/real.md",
    "provenance": "unknown",
    "source_type": "blogs",
    "channel": "local_kb",
    "date": "",
}


@pytest.fixture
def network_guard(monkeypatch):
    """Fail loudly if anything tries to open an external network connection.

    Loopback is allowed: asyncio creates its self-pipe through a local socket pair
    on Windows, and that is not hub access.
    """
    attempted: list[str] = []
    import deepchoice.utils.embedding as embedding

    original_connect = socket.socket.connect
    original_create = socket.create_connection

    def guarded_connect(self, address):
        if _is_loopback(address):
            return original_connect(self, address)
        attempted.append(str(address))
        raise AssertionError(f"external network access attempted: {address}")

    def guarded_create(address, *args, **kwargs):
        if _is_loopback(address):
            return original_create(address, *args, **kwargs)
        attempted.append(str(address))
        raise AssertionError(f"external network access attempted: {address}")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", guarded_create)
    monkeypatch.setattr(embedding, "_local_loader",
                        lambda: (_ for _ in ()).throw(
                            AssertionError("local model load attempted")),
                        raising=True)
    yield attempted
    assert attempted == [], f"network was attempted: {attempted}"


class TestNoMaterialMeansNoModel:
    def test_evaluation_material_only_is_empty_and_costs_nothing(self, monkeypatch,
                                                                 network_guard):
        from deepchoice.retrievers import chroma_kb as mod

        loaded = []
        monkeypatch.setattr(mod, "get_embedding_model", lambda: loaded.append(1))
        kb = _kb_with([dict(BENCHMARK_META)] * 5)

        result = asyncio.run(kb.search("q", [], max_results=4))

        assert result["status"] == "empty"
        assert result["empty_reason"] == chroma_kb_reason("no_research_material")
        assert result["results"] == []
        assert result["error"] is None
        assert loaded == [], "the embedding model must not be loaded"
        assert kb.collection.queries == 0, "the collection must not be queried"
        assert kb.collection.deleted == 0, "evaluation material must not be deleted"

    def test_an_empty_index_is_reported_separately(self, monkeypatch, network_guard):
        from deepchoice.retrievers import chroma_kb as mod

        monkeypatch.setattr(mod, "get_embedding_model", lambda: pytest.fail("loaded"))
        kb = _kb_with([])

        result = asyncio.run(kb.search("q", [], max_results=4))

        assert result["status"] == "empty"
        assert result["empty_reason"] == chroma_kb_reason("index_empty")
        assert result["empty_reason"] != chroma_kb_reason("no_research_material")

    def test_a_real_local_document_still_makes_the_source_searchable(self, monkeypatch,
                                                                    network_guard):
        from deepchoice.retrievers import chroma_kb as mod

        model = FakeModel()
        monkeypatch.setattr(mod, "get_embedding_model", lambda: model)
        kb = _kb_with([RESEARCH_META])

        result = asyncio.run(kb.search("q", [], max_results=4))

        assert result["status"] == "success"
        assert [r["title"] for r in result["results"]] == ["Real local doc"]
        assert model.encodes >= 1


def chroma_kb_reason(name):
    from deepchoice.retrievers import chroma_kb as mod

    return {"no_research_material": mod.EMPTY_NO_RESEARCH_MATERIAL,
            "index_empty": mod.EMPTY_INDEX}[name]


class TestMissingModelFailsFast:
    def test_the_source_fails_explicitly_without_hub_access(self, monkeypatch,
                                                           network_guard):
        import deepchoice.utils.embedding as embedding

        embedding.reset_embedding_model_state()
        monkeypatch.setattr(embedding, "_local_loader",
                            lambda: (_ for _ in ()).throw(
                                OSError("local model directory not found")),
                            raising=True)
        try:
            kb = _kb_with([RESEARCH_META])
            result = asyncio.run(kb.search("q", [], max_results=4))
        finally:
            embedding.reset_embedding_model_state()

        assert result["status"] == "failed"
        assert "EmbeddingModelUnavailable" in result["error"]
        assert "BAAI/bge-m3" in result["error"]
        assert kb.collection.queries == 0

    def test_the_load_attempt_does_not_run_on_the_event_loop_thread(self, monkeypatch):
        """A synchronous load must not block the loop the service answers on."""
        import deepchoice.utils.embedding as embedding

        embedding.reset_embedding_model_state()
        seen = {}

        def loading():
            seen["thread"] = threading.current_thread()
            time.sleep(0.2)  # a real synchronous load attempt
            raise OSError("no local model")

        monkeypatch.setattr(embedding, "_local_loader", loading, raising=True)
        ticks = []

        async def scenario():
            async def ticker():
                while True:
                    ticks.append(time.monotonic())
                    await asyncio.sleep(0.01)

            task = asyncio.create_task(ticker())
            try:
                kb = _kb_with([RESEARCH_META])
                result = await kb.search("q", [], max_results=4)
            finally:
                task.cancel()
            return result

        try:
            result = asyncio.run(scenario())
        finally:
            embedding.reset_embedding_model_state()

        assert result["status"] == "failed"
        assert seen["thread"] is not threading.main_thread(), \
            "the synchronous load ran on the calling thread"
        assert len(ticks) >= 5, "the event loop kept running during the load attempt"


class TestModelLoadingIsExplicitlyLocal:
    def test_sentence_transformer_is_constructed_local_only(self, monkeypatch):
        import sentence_transformers

        import deepchoice.utils.embedding as embedding

        seen = {}
        model = FakeModel()

        def fake_transformer(name, **kwargs):
            seen["name"] = name
            seen["kwargs"] = kwargs
            return model

        monkeypatch.setattr(sentence_transformers, "SentenceTransformer", fake_transformer)
        monkeypatch.setattr(socket.socket, "connect",
                            _no_network([], "socket.connect"))
        embedding.reset_embedding_model_state()
        try:
            loaded = embedding.get_embedding_model()
            state = embedding.embedding_model_state()
        finally:
            embedding.reset_embedding_model_state()

        assert loaded is model
        assert seen["name"] == "BAAI/bge-m3"
        assert seen["kwargs"].get("local_files_only") is True, \
            "the model must be loaded from local files only"
        assert state["available"] is True


class TestTheGuardStopsABlockedChild:
    def _run_dir(self, root, task_id):
        return pathlib.Path(root) / task_id

    def _spawn_blocked_child(self, root, task_id, script):
        run_dir = self._run_dir(root, task_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        child_script = pathlib.Path(root) / "blocked_service.py"
        child_script.write_text(textwrap.dedent(script).format(
            run_dir=repr(str(run_dir)), task_id=repr(task_id)), encoding="utf-8")
        return run_dir, subprocess.Popen([sys.executable, str(child_script)])

    def test_a_child_blocked_in_synchronous_work_is_stopped(self, tmp_path):
        run_dir, child = self._spawn_blocked_child(tmp_path, "blocked-task", """
            import json, os, pathlib, time
            run_dir = pathlib.Path({run_dir})
            (run_dir / "run_state.json").write_text(json.dumps({{
                "task_id": {task_id}, "state": "running", "pid": os.getpid(),
                "started_at_epoch": time.time(), "wall_clock_max_s": 900,
            }}), encoding="utf-8")
            (run_dir / "run_limits_counts.json").write_text(json.dumps({{
                "llm_requests": 3, "tavily_posts": 2,
            }}), encoding="utf-8")
            time.sleep(600)  # a real synchronous block, not asyncio.sleep
        """)

        started = time.monotonic()
        try:
            record = run_guard.guard_service(
                child,
                outputs_dir=tmp_path,
                wall_clock_max_s=1.0,
                service_started_epoch=time.time() - 1,
                cancel_fn=lambda task_id: (_ for _ in ()).throw(
                    TimeoutError("cancel endpoint blocked")),
                poll_s=0.05,
                grace_s=0.5,
                kill_grace_s=3.0,
                log=lambda message: None,
            )
        finally:
            if child.poll() is None:
                child.kill()
        elapsed = time.monotonic() - started

        assert record["forced"] is True
        assert record["reason"] == "wall_clock"
        assert record["exit_confirmed"] is True
        assert child.poll() is not None, "the dedicated child must be gone"
        assert elapsed < 15, f"the guard took too long: {elapsed:.1f}s"
        assert record["cancel_result"].startswith("failed"), \
            "the blocked normal-cancel path must be recorded as failed"
        assert record["deadline_epoch"] <= record["exited_at_epoch"]
        assert record["exited_at_iso"] and record["deadline_iso"]

        stop_file = run_dir / "guard_stop.json"
        assert stop_file.is_file(), "the forced stop must leave a record"
        written = json.loads(stop_file.read_text(encoding="utf-8"))
        assert written["forced"] is True
        assert written["confirmed_counts"] == {"llm_requests": 3, "tavily_posts": 2}
        assert written["final_consumption"] == "unknown"

        # The child was killed, so its record still says running — a forced
        # termination is never rewritten as complete.
        state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
        assert state["state"] == "running"

        # Only the one child was involved, and no new run appeared afterwards.
        assert record["service_pid"] == child.pid
        time.sleep(0.3)
        assert len(list(tmp_path.glob("*/run_state.json"))) == 1, \
            "no new local dispatch may appear after a forced stop"

    def test_only_the_dedicated_child_is_signalled(self, tmp_path):
        """The guard holds the child handle; it never scans for processes."""
        import inspect

        source = inspect.getsource(run_guard)
        for forbidden in ("psutil", "taskkill", "os.kill", "killpg", "Process("):
            assert forbidden not in source, f"guard must not use {forbidden!r}"


class TestNormalPathIsNotKilled:
    def test_a_child_that_finishes_normally_exits_cleanly(self, tmp_path):
        run_dir = tmp_path / "normal-task"
        run_dir.mkdir()
        script = tmp_path / "normal_service.py"
        script.write_text(textwrap.dedent(f"""
            import json, os, pathlib, time
            run_dir = pathlib.Path({str(run_dir)!r})
            (run_dir / "run_state.json").write_text(json.dumps({{
                "task_id": "normal-task", "state": "running", "pid": os.getpid(),
                "started_at_epoch": time.time(), "wall_clock_max_s": 900,
            }}), encoding="utf-8")
            time.sleep(0.4)
            (run_dir / "run_state.json").write_text(json.dumps({{
                "task_id": "normal-task", "state": "complete", "pid": os.getpid(),
                "started_at_epoch": time.time() - 0.4, "wall_clock_max_s": 900,
            }}), encoding="utf-8")
            raise SystemExit(0)
        """), encoding="utf-8")
        child = subprocess.Popen([sys.executable, str(script)])
        try:
            record = run_guard.guard_service(
                child,
                outputs_dir=tmp_path,
                wall_clock_max_s=30.0,
                service_started_epoch=time.time() - 1,
                cancel_fn=lambda task_id: "not_called",
                poll_s=0.05,
                grace_s=1.0,
                kill_grace_s=1.0,
                log=lambda message: None,
            )
        finally:
            if child.poll() is None:
                child.kill()
        assert record["forced"] is False, f"a normal run was killed: {record}"
        assert record["reason"] == "service_exited"
        assert child.returncode == 0

    def test_a_finished_older_run_never_supplies_the_deadline(self, tmp_path):
        outputs = tmp_path / ("outputs")
        for task_id, state, started in (
                ("old-done", "complete", time.time() - 3600),
                ("old-running", "running", time.time() - 3600)):
            run_dir = outputs / task_id
            run_dir.mkdir(parents=True)
            (run_dir / "run_state.json").write_text(json.dumps({
                "task_id": task_id, "state": state, "started_at_epoch": started,
            }), encoding="utf-8")
        assert run_guard.find_active_run(outputs, time.time() - 10) is None


class TestRunRecord:
    def test_the_record_starts_with_identity_and_limits(self, tmp_path):
        import run_limits

        run_limits.begin_run("task-1", str(tmp_path))
        record = json.loads((tmp_path / "run_state.json").read_text(encoding="utf-8"))
        counts = json.loads((tmp_path / "run_limits_counts.json").read_text(encoding="utf-8"))
        assert record["task_id"] == "task-1"
        assert record["state"] == "running"
        assert isinstance(record["started_at_epoch"], (int, float))
        assert record["wall_clock_max_s"] == run_limits.WALL_CLOCK_MAX_S
        assert record["llm_requests_max"] == run_limits.LLM_REQUESTS_MAX
        assert counts["task_id"] == "task-1"

    def test_a_count_change_is_written_before_the_run_ends(self, tmp_path):
        import run_limits

        run_limits.begin_run("task-2", str(tmp_path))
        run_limits._state["llm_requests"] += 2
        run_limits._persist_active()
        counts = json.loads((tmp_path / "run_limits_counts.json").read_text(encoding="utf-8"))
        assert counts["llm_requests"] == 2
        # The run has not ended; the file exists anyway.
        assert json.loads((tmp_path / "run_state.json").read_text(encoding="utf-8"))["state"] == "running"

    def test_the_end_state_is_recorded_and_never_lies(self, tmp_path):
        import run_limits

        run_limits.begin_run("task-3", str(tmp_path))
        run_limits.end_run("failed", "boom")
        record = json.loads((tmp_path / "run_state.json").read_text(encoding="utf-8"))
        assert record["state"] == "failed"
        assert record["detail"] == "boom"
        assert record["ended_at_epoch"] >= record["started_at_epoch"]


class TestEmptySourceIsNotAFailure:
    def test_multi_retriever_reports_empty_separately(self, monkeypatch):
        from deepchoice.agents import multi_retriever as mr

        class EmptyRetriever:
            source = "fake"

            async def search(self, *args, **kwargs):
                return {"source": "fake", "status": "empty", "results": [],
                        "error": None, "empty_reason": "no_research_material",
                        "latency_ms": 1}

        monkeypatch.setattr(mr, "RETRIEVER_REGISTRY", {"fake": EmptyRetriever})
        monkeypatch.setattr(mr, "harvest", lambda *a, **k: [])
        monkeypatch.setattr(mr, "extract_terms", lambda *a, **k: [])
        state = {"task": {"query": "q", "candidate_techs": []}, "sub_questions": []}
        out = asyncio.run(mr.MultiRetrieverAgent().run(state))

        assert out["partial_failures"] == []
        assert out["empty_sources"] == [{"source": "fake",
                                         "reason": "no_research_material"}]
        signal = out["quality_signals"][0]
        assert signal["retrievers_failed"] == 0
        assert signal["retrievers_empty"] == 1
