from __future__ import annotations

import asyncio
import re
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from deepchoice.agents import multi_retriever as multi_module
from deepchoice.agents.multi_retriever import MultiRetrieverAgent
from deepchoice.budget import DeferredBudgetManager
from deepchoice.budget_errors import BudgetPersistenceError
from deepchoice.cache import (
    RETRIEVAL_CACHE_POLICY_VERSION,
    SQLiteRetrievalCache,
    build_retrieval_cache_key,
    parse_retrieval_cache_enabled,
    ttl_for_source,
)
from deepchoice.persistence import connect_database, run_migrations
from deepchoice.retrievers.contracts import RetrievalRequest, RetrievalResult
from deepchoice.runtime.context import RunContext, bind_run_context


NOW = datetime(2026, 9, 15, tzinfo=UTC)


class _Cancellation:
    async def raise_if_cancelled(self) -> None:
        return None


class _NoTrace:
    async def record_run(self, trace) -> None:
        return None

    async def record_node_attempt(self, attempt) -> None:
        return None

    async def record_external_call(self, call) -> None:
        return None

    async def record_event(self, event) -> None:
        return None


def _context(cache, *, run_id: str = "run-1", budget=None) -> RunContext:
    return RunContext(
        task_id="task-1",
        run_id=run_id,
        manifest_id="manifest-1",
        execution_epoch=1,
        deadline_at=NOW + timedelta(days=1),
        cancellation=_Cancellation(),
        trace=_NoTrace(),
        budget=budget or DeferredBudgetManager(),
        retrieval_cache=cache,
    )


def _request(
    query: str = "Compare FastAPI and Flask",
    *,
    adapted_queries: tuple[str, ...] = ("FastAPI", "Flask"),
) -> RetrievalRequest:
    return RetrievalRequest(
        query=query,
        sub_questions=("Compare async request handling",),
        max_results=7,
        adapted_queries=adapted_queries,
    )


def _success(source: str, *, results: list[dict] | None = None) -> RetrievalResult:
    return RetrievalResult(
        source=source,
        status="success",
        results=[] if results is None else results,
        error=None,
        latency_ms=1,
    )


async def _store(tmp_path, *, enabled: bool = True, clock=lambda: NOW, max_bytes=512 * 1024):
    connection = await connect_database(tmp_path / "cache.db")
    await run_migrations(connection)
    store = SQLiteRetrievalCache(
        connection,
        asyncio.Lock(),
        enabled=enabled,
        clock=clock,
        max_entry_bytes=max_bytes,
    )
    return connection, store


def test_cache_key_is_hash_only_and_preserves_semantic_input_distinctions() -> None:
    original = _request(adapted_queries=("FastAPI", "flask", "FastAPI"))
    key = build_retrieval_cache_key(
        source="official",
        request=original,
        manifest_id="manifest-1",
    )
    assert re.fullmatch(r"[0-9a-f]{64}", key)
    assert "FastAPI" not in key
    assert key != build_retrieval_cache_key(
        source="official",
        request=_request(adapted_queries=("FastAPI", "FastAPI", "flask")),
        manifest_id="manifest-1",
    )
    assert key != build_retrieval_cache_key(
        source="official",
        request=_request(
            query="compare FastAPI and Flask",
            adapted_queries=("FastAPI", "flask", "FastAPI"),
        ),
        manifest_id="manifest-1",
    )
    assert build_retrieval_cache_key(
        source="official",
        request=_request(query="Ａ"),
        manifest_id="manifest-1",
    ) == build_retrieval_cache_key(
        source="official",
        request=_request(query="A"),
        manifest_id="manifest-1",
    )
    assert key != build_retrieval_cache_key(
        source="official",
        request=original,
        manifest_id="manifest-1",
        policy_version=RETRIEVAL_CACHE_POLICY_VERSION + "-next",
    )
    assert build_retrieval_cache_key(
        source="chroma",
        request=RetrievalRequest(query="compare", local_scene_needs=("backup",), local_collection_id="a" * 64),
        manifest_id="manifest-1",
    ) != build_retrieval_cache_key(
        source="chroma",
        request=RetrievalRequest(query="compare", local_scene_needs=("full_text_search",), local_collection_id="a" * 64),
        manifest_id="manifest-1",
    )


@pytest.mark.asyncio
async def test_chroma_cache_binds_collection_bytes_and_keeps_cache_hits(tmp_path, monkeypatch) -> None:
    connection, store = await _store(tmp_path)
    calls = 0
    chroma_path = tmp_path / "seed-a" / "chroma_db"
    chroma_path.mkdir(parents=True)
    (chroma_path.parent / "chunks.json").write_bytes(b"same-index")
    (chroma_path.parent / "seed-manifest.json").write_bytes(b"same-manifest")
    collection_file = chroma_path / "chroma.sqlite3"
    collection_file.write_bytes(b"collection-v1")
    monkeypatch.setenv("CHROMA_PATH", str(chroma_path))

    class Retriever:
        source = "chroma"

        async def retrieve(self, request):
            nonlocal calls
            calls += 1
            assert request.local_scene_needs == ("backup",)
            return _success("chroma", results=[{
                "url": "https://sqlite.org/backup.html", "snippet": f"version-{calls}",
            }])

    try:
        with bind_run_context(_context(store)):
            first = await multi_module._invoke_retriever(
                "chroma", Retriever, query="SQLite or PostgreSQL?",
                sub_questions=[], adapted_queries=[], local_scene_needs=("backup",),
            )
            second = await multi_module._invoke_retriever(
                "chroma", Retriever, query="SQLite or PostgreSQL?",
                sub_questions=[], adapted_queries=[], local_scene_needs=("backup",),
            )
            collection_file.write_bytes(b"collection-v2")
            third = await multi_module._invoke_retriever(
                "chroma", Retriever, query="SQLite or PostgreSQL?",
                sub_questions=[], adapted_queries=[], local_scene_needs=("backup",),
            )
            other_path = tmp_path / "seed-b" / "chroma_db"
            other_path.mkdir(parents=True)
            (other_path.parent / "chunks.json").write_bytes(b"same-index")
            (other_path.parent / "seed-manifest.json").write_bytes(b"same-manifest")
            (other_path / "chroma.sqlite3").write_bytes(b"collection-v1")
            monkeypatch.setenv("CHROMA_PATH", str(other_path))
            fourth = await multi_module._invoke_retriever(
                "chroma", Retriever, query="SQLite or PostgreSQL?",
                sub_questions=[], adapted_queries=[], local_scene_needs=("backup",),
            )
        assert calls == 3
        assert (first[2], second[2], third[2], fourth[2]) == ("miss", "hit", "miss", "miss")
        assert first[0].results[0]["snippet"] == "version-1"
        assert second[0].results[0]["snippet"] == "version-1"
        assert third[0].results[0]["snippet"] == "version-2"
        assert fourth[0].results[0]["snippet"] == "version-3"
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_chroma_collection_change_during_dispatch_is_visible_and_not_cached(tmp_path, monkeypatch) -> None:
    connection, store = await _store(tmp_path)
    chroma_path = tmp_path / "chroma_db"
    chroma_path.mkdir()
    (tmp_path / "chunks.json").write_bytes(b"chunks")
    (tmp_path / "seed-manifest.json").write_bytes(b"manifest")
    collection_file = chroma_path / "chroma.sqlite3"
    collection_file.write_bytes(b"old")
    monkeypatch.setenv("CHROMA_PATH", str(chroma_path))
    calls = 0

    class Retriever:
        source = "chroma"

        async def retrieve(self, request):
            nonlocal calls
            calls += 1
            if calls == 1:
                collection_file.write_bytes(b"new")
            return _success("chroma")

    try:
        with bind_run_context(_context(store)):
            first = await multi_module._invoke_retriever(
                "chroma", Retriever, query="compare", sub_questions=[], adapted_queries=[],
            )
            second = await multi_module._invoke_retriever(
                "chroma", Retriever, query="compare", sub_questions=[], adapted_queries=[],
            )
        assert first[0].status == "success"
        assert first[2] == "miss"
        assert second[0].status == "success"
        assert second[2] == "miss"
        assert calls == 2
    finally:
        await connection.close()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, True),
        ("1", True),
        ("true", True),
        ("ON", True),
        ("yes", True),
        ("0", False),
        ("FALSE", False),
        ("off", False),
        ("No", False),
    ],
)
def test_cache_enabled_parser(raw: str | None, expected: bool) -> None:
    assert parse_retrieval_cache_enabled(raw) is expected


def test_cache_enabled_parser_rejects_ambiguous_values() -> None:
    for value in ("", "  ", "enabled"):
        with pytest.raises(ValueError):
            parse_retrieval_cache_enabled(value)


def test_source_ttls_are_frozen() -> None:
    assert ttl_for_source("tavily") == timedelta(hours=1)
    assert ttl_for_source("community") == timedelta(hours=1)
    assert ttl_for_source("official") == timedelta(hours=6)
    assert ttl_for_source("github") == timedelta(hours=6)
    assert ttl_for_source("chroma") == timedelta(hours=6)
    assert ttl_for_source("arxiv") == timedelta(hours=24)


@pytest.mark.asyncio
async def test_successful_empty_result_is_cached_until_source_ttl(tmp_path) -> None:
    observed = [NOW]
    connection, store = await _store(tmp_path, clock=lambda: observed[0])
    request = _request()
    key = store.make_key(source="tavily", request=request, manifest_id="manifest-1")
    try:
        assert await store.put(key, _success("tavily"), source="tavily") is True
        assert await store.get(key) == _success("tavily")
        observed[0] += timedelta(minutes=59)
        assert await store.get(key) == _success("tavily")
        observed[0] += timedelta(minutes=1)
        assert await store.get(key) is None
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_disabled_failed_corrupt_and_oversize_cache_are_fail_open(tmp_path) -> None:
    connection, disabled = await _store(tmp_path, enabled=False)
    key = "a" * 64
    try:
        assert await disabled.put(key, _success("tavily"), source="tavily") is False
        assert await disabled.get(key) is None
        assert await (
            await connection.execute("SELECT COUNT(*) FROM retrieval_cache")
        ).fetchone() == (0,)

        enabled = SQLiteRetrievalCache(connection, asyncio.Lock(), clock=lambda: NOW)
        failed = RetrievalResult(
            source="tavily",
            status="failed",
            results=[],
            error="provider unavailable",
            latency_ms=1,
        )
        assert await enabled.put(key, failed, source="tavily") is False
        assert await enabled.put(key, {"status": "success"}, source="tavily") is False

        corrupt = "b" * 64
        await connection.execute(
            "INSERT INTO retrieval_cache VALUES (?, ?, ?, ?, ?)",
            (corrupt, "{}", 2, NOW.isoformat(), (NOW + timedelta(hours=1)).isoformat()),
        )
        assert await enabled.get(corrupt) is None

        result = _success("tavily", results=[{"snippet": "x" * 300}])
        raw = result.model_dump_json()
        oversize = "c" * 64
        await connection.execute(
            "INSERT INTO retrieval_cache VALUES (?, ?, ?, ?, ?)",
            (
                oversize,
                raw,
                len(raw.encode("utf-8")),
                NOW.isoformat(),
                (NOW + timedelta(hours=1)).isoformat(),
            ),
        )
        bounded = SQLiteRetrievalCache(
            connection,
            asyncio.Lock(),
            clock=lambda: NOW,
            max_entry_bytes=128,
        )
        assert await bounded.get(oversize) is None
        assert await bounded.put(oversize, result, source="tavily") is False
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_successful_put_prunes_at_most_one_hundred_expired_rows(
    tmp_path,
) -> None:
    connection, store = await _store(tmp_path)
    result = _success("tavily")
    raw = result.model_dump_json()
    size = len(raw.encode("utf-8"))
    expired_at = (NOW - timedelta(seconds=1)).isoformat()
    active_at = (NOW + timedelta(hours=1)).isoformat()
    rows = [
        (f"{index:064x}", raw, size, NOW.isoformat(), expired_at)
        for index in range(105)
    ]
    rows.append(("e" * 64, raw, size, NOW.isoformat(), active_at))
    try:
        await connection.executemany(
            "INSERT INTO retrieval_cache VALUES (?, ?, ?, ?, ?)", rows
        )
        assert await store.put("f" * 64, result, source="tavily") is True
        assert await (
            await connection.execute(
                "SELECT COUNT(*) FROM retrieval_cache WHERE expires_at <= ?",
                (NOW.isoformat(),),
            )
        ).fetchone() == (5,)
        assert await (
            await connection.execute("SELECT COUNT(*) FROM retrieval_cache")
        ).fetchone() == (7,)
    finally:
        await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["failure", "cancel"])
async def test_cache_autocommit_failure_or_cancel_does_not_affect_competing_writer(
    tmp_path,
    monkeypatch,
    mode: str,
) -> None:
    connection, store = await _store(tmp_path)
    await connection.execute("CREATE TABLE writer_marks(value TEXT PRIMARY KEY)")
    original_execute = connection.execute
    insert_entered = asyncio.Event()

    async def injected_execute(sql, parameters=None):
        if "INSERT INTO retrieval_cache" in str(sql):
            insert_entered.set()
            if mode == "cancel":
                await asyncio.Event().wait()
            raise sqlite3.OperationalError("injected cache write failure")
        if parameters is None:
            return await original_execute(sql)
        return await original_execute(sql, parameters)

    async def competing_writer():
        async with store._lock:
            cursor = await original_execute(
                "INSERT INTO writer_marks(value) VALUES ('kept')"
            )
            await cursor.close()

    monkeypatch.setattr(connection, "execute", injected_execute)
    put_task = asyncio.create_task(
        store.put("d" * 64, _success("tavily"), source="tavily")
    )
    try:
        await asyncio.wait_for(insert_entered.wait(), timeout=2)
        assert connection.in_transaction is False
        writer = asyncio.create_task(competing_writer())
        if mode == "cancel":
            put_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await put_task
        else:
            assert await put_task is False
        await asyncio.wait_for(writer, timeout=2)
        assert connection.in_transaction is False
        assert await (
            await original_execute("SELECT value FROM writer_marks")
        ).fetchone() == ("kept",)
    finally:
        if not put_task.done():
            put_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await put_task
        await connection.close()


@pytest.mark.asyncio
async def test_same_run_singleflight_coalesces_only_successful_dispatch(tmp_path) -> None:
    connection, store = await _store(tmp_path)
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    class Retriever:
        source = "official"

        async def retrieve(self, request):
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return _success(self.source)

    try:
        with bind_run_context(_context(store)):
            leader = asyncio.create_task(
                multi_module._invoke_retriever(
                    "official",
                    Retriever,
                    query="compare",
                    sub_questions=["a sufficiently detailed question"],
                    adapted_queries=[],
                )
            )
            await entered.wait()
            follower = asyncio.create_task(
                multi_module._invoke_retriever(
                    "official",
                    Retriever,
                    query="compare",
                    sub_questions=["a sufficiently detailed question"],
                    adapted_queries=[],
                )
            )
            await asyncio.sleep(0)
            release.set()
            first, second = await asyncio.gather(leader, follower)

        assert calls == 1
        assert {first[2], second[2]} == {"miss", "coalesced"}
        assert store._flights == {}
    finally:
        await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome",
    ["failed", "invalid", "oversize", "put_false", "database_failure"],
)
async def test_singleflight_shares_non_cacheable_leader_outcome_once(
    tmp_path,
    monkeypatch,
    outcome: str,
) -> None:
    connection, store = await _store(tmp_path)
    entered = asyncio.Event()
    follower_waiting = asyncio.Event()
    release = asyncio.Event()
    calls = 0
    budget_calls = {"reserve": 0, "settle": 0}

    async def reserve_once(*args, **kwargs):
        budget_calls["reserve"] += 1
        return ()

    async def settle_once(*args, **kwargs):
        budget_calls["settle"] += 1

    monkeypatch.setattr("deepchoice.budget.reserve_call", reserve_once)
    monkeypatch.setattr("deepchoice.budget.settle_call", settle_once)
    original_wait = store.wait

    async def observe_wait(claim):
        follower_waiting.set()
        await original_wait(claim)

    monkeypatch.setattr(store, "wait", observe_wait)

    if outcome == "put_false":
        async def reject_put(*args, **kwargs):
            return False

        monkeypatch.setattr(store, "put", reject_put)
    elif outcome == "database_failure":
        await connection.execute("DROP TABLE retrieval_cache")

    class Retriever:
        source = "official"

        async def retrieve(self, request):
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            if outcome == "failed":
                return RetrievalResult(
                    source=self.source,
                    status="failed",
                    results=[],
                    error="unavailable",
                    latency_ms=1,
                )
            if outcome == "invalid":
                return {
                    "source": self.source,
                    "status": "success",
                    "results": [],
                    "error": "invalid-success-error",
                    "latency_ms": 1,
                }
            results = (
                [{"snippet": "x" * (512 * 1024)}]
                if outcome == "oversize"
                else []
            )
            return _success(self.source, results=results)

    async def invoke():
        return await multi_module._invoke_retriever(
            "official",
            Retriever,
            query="compare",
            sub_questions=["a sufficiently detailed question"],
            adapted_queries=[],
        )

    try:
        with bind_run_context(_context(store)):
            leader = asyncio.create_task(invoke())
            await entered.wait()
            follower = asyncio.create_task(invoke())
            await asyncio.wait_for(follower_waiting.wait(), timeout=2)
            release.set()
            first, second = await asyncio.gather(leader, follower)

        assert calls == 1
        assert budget_calls == {"reserve": 1, "settle": 1}
        assert {first[2], second[2]} == {"miss", "coalesced"}
        assert store._flights == {}
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_leader_cancel_wakes_follower_to_retry_and_cleans_flight(tmp_path) -> None:
    connection, store = await _store(tmp_path)
    first_entered = asyncio.Event()
    calls = 0

    class Retriever:
        source = "official"

        async def retrieve(self, request):
            nonlocal calls
            calls += 1
            if calls == 1:
                first_entered.set()
                await asyncio.Event().wait()
            return _success(self.source)

    try:
        with bind_run_context(_context(store)):
            leader = asyncio.create_task(
                multi_module._invoke_retriever(
                    "official",
                    Retriever,
                    query="compare",
                    sub_questions=["a sufficiently detailed question"],
                    adapted_queries=[],
                )
            )
            await first_entered.wait()
            follower = asyncio.create_task(
                multi_module._invoke_retriever(
                    "official",
                    Retriever,
                    query="compare",
                    sub_questions=["a sufficiently detailed question"],
                    adapted_queries=[],
                )
            )
            await asyncio.sleep(0)
            leader.cancel()
            with pytest.raises(asyncio.CancelledError):
                await leader
            result = await asyncio.wait_for(follower, timeout=2)

        assert result[2] == "miss"
        assert calls == 2
        assert store._flights == {}
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_follower_cancel_does_not_cancel_inline_leader(tmp_path) -> None:
    connection, store = await _store(tmp_path)
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    class Retriever:
        source = "official"

        async def retrieve(self, request):
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return _success(self.source)

    try:
        with bind_run_context(_context(store)):
            leader = asyncio.create_task(
                multi_module._invoke_retriever(
                    "official",
                    Retriever,
                    query="compare",
                    sub_questions=["a sufficiently detailed question"],
                    adapted_queries=[],
                )
            )
            await entered.wait()
            follower = asyncio.create_task(
                multi_module._invoke_retriever(
                    "official",
                    Retriever,
                    query="compare",
                    sub_questions=["a sufficiently detailed question"],
                    adapted_queries=[],
                )
            )
            await asyncio.sleep(0)
            follower.cancel()
            with pytest.raises(asyncio.CancelledError):
                await follower
            release.set()
            assert (await asyncio.wait_for(leader, timeout=2))[2] == "miss"

        assert calls == 1
        assert store._flights == {}
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_cache_hit_bypasses_trace_and_budget(tmp_path, monkeypatch) -> None:
    connection, store = await _store(tmp_path)
    request = RetrievalRequest(
        query="compare",
        sub_questions=("a sufficiently detailed question",),
        adapted_queries=(),
        max_results=7,
        official_mapping_id=multi_module.official_mapping_identity(),
    )
    key = store.make_key(
        source="official", request=request, manifest_id="manifest-1"
    )

    class Retriever:
        source = "official"

        async def retrieve(self, request):
            raise AssertionError("cache hit must not dispatch")

    def trace_must_not_start():
        raise AssertionError("cache hit must not create Trace")

    async def budget_must_not_reserve(*args, **kwargs):
        raise AssertionError("cache hit must not reserve budget")

    try:
        assert await store.put(key, _success("official"), source="official")
        monkeypatch.setattr(multi_module, "current_trace_recorder", trace_must_not_start)
        monkeypatch.setattr("deepchoice.budget.reserve_call", budget_must_not_reserve)
        with bind_run_context(_context(store)):
            result = await multi_module._invoke_retriever(
                "official",
                Retriever,
                query="compare",
                sub_questions=["a sufficiently detailed question"],
                adapted_queries=[],
            )
        assert result[2] == "hit"
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_cache_miss_preserves_fail_closed_budget_gate(tmp_path, monkeypatch) -> None:
    connection, store = await _store(tmp_path)
    dispatched = False

    class Retriever:
        source = "official"

        async def retrieve(self, request):
            nonlocal dispatched
            dispatched = True
            return _success(self.source)

    async def deny(*args, **kwargs):
        raise BudgetPersistenceError("budget database unavailable")

    monkeypatch.setattr("deepchoice.budget.reserve_call", deny)
    try:
        with bind_run_context(_context(store)):
            with pytest.raises(BudgetPersistenceError):
                await multi_module._invoke_retriever(
                    "official",
                    Retriever,
                    query="compare",
                    sub_questions=["a sufficiently detailed question"],
                    adapted_queries=[],
                )
        assert dispatched is False
        assert store._flights == {}
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_legacy_search_caches_success_but_not_failure_or_stable_mismatch(
    tmp_path,
) -> None:
    connection, store = await _store(tmp_path)
    legacy_calls = 0
    failed_calls = 0
    mismatch_calls = 0

    class Legacy:
        async def search(self, query, sub_questions, *, adapted_queries):
            nonlocal legacy_calls
            legacy_calls += 1
            return _success("legacy-source").model_dump()

    class Failed:
        async def retrieve(self, request):
            nonlocal failed_calls
            failed_calls += 1
            return RetrievalResult(
                source="official",
                status="failed",
                results=[],
                error="unavailable",
                latency_ms=1,
            )

    class Mismatch:
        async def retrieve(self, request):
            nonlocal mismatch_calls
            mismatch_calls += 1
            return _success("wrong-source")

    async def invoke(name, cls):
        return await multi_module._invoke_retriever(
            name,
            cls,
            query="compare",
            sub_questions=["a sufficiently detailed question"],
            adapted_queries=[],
        )

    try:
        with bind_run_context(_context(store)):
            assert (await invoke("legacy", Legacy))[2] == "miss"
            assert (await invoke("legacy", Legacy))[2] == "hit"
            await invoke("official", Failed)
            await invoke("official", Failed)
            await invoke("github", Mismatch)
            await invoke("github", Mismatch)

        assert legacy_calls == 1
        assert failed_calls == 2
        assert mismatch_calls == 2
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_quality_signals_report_cache_outcomes(tmp_path) -> None:
    connection, store = await _store(tmp_path)
    calls = 0

    class Retriever:
        source = "official"

        async def retrieve(self, request):
            nonlocal calls
            calls += 1
            return _success(self.source)

    state = {
        "task": {"query": "compare"},
        "sub_questions": ["a sufficiently detailed question"],
    }
    agent = MultiRetrieverAgent(retriever_registry={"official": Retriever})
    try:
        with bind_run_context(_context(store)):
            first = await agent.run(state)
            second = await agent.run(state)
        assert {
            key: first["quality_signals"][0][key]
            for key in ("cache_hits", "cache_coalesced", "cache_misses")
        } == {"cache_hits": 0, "cache_coalesced": 0, "cache_misses": 1}
        assert {
            key: second["quality_signals"][0][key]
            for key in ("cache_hits", "cache_coalesced", "cache_misses")
        } == {"cache_hits": 1, "cache_coalesced": 0, "cache_misses": 0}
        assert calls == 1
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_official_learned_identity_invalidates_cached_empty_then_preserves_body_hit(tmp_path, monkeypatch):
    import httpx
    from unittest.mock import AsyncMock
    from deepchoice.retrievers import learned_docs, official, official_pages
    from deepchoice.budget import runtime as budget_runtime
    monkeypatch.setattr(learned_docs, "LEARNED_DOCS_PATH", tmp_path / "learned.json")
    monkeypatch.setattr(learned_docs, "_READONLY", False)
    monkeypatch.setattr(official, "TECH_DOCS", {})
    monkeypatch.setattr(official, "call_model", AsyncMock(return_value={"url": None}))
    monkeypatch.setattr(budget_runtime, "reserve_call", AsyncMock(return_value=("fixture-reservation",)))
    monkeypatch.setattr(budget_runtime, "settle_call", AsyncMock())
    url = "https://docs.unlisted.example/docs/filtering"
    async def fetch(_source, target, **kwargs):
        return httpx.Response(200, text=("<title>Unlisted filtering</title><p>Unlisted filtering evaluates the configured fields "
            "against a predicate before returning matching records. Access restrictions remain separate.</p>"),
            headers={"content-type": "text/html"}, request=httpx.Request("GET", target))
    get = AsyncMock(side_effect=fetch)
    monkeypatch.setattr(official_pages.outbound, "safe_fetch", get)
    connection, store = await _store(tmp_path)
    async def invoke(run_id):
        with bind_run_context(_context(store, run_id=run_id)):
            return await multi_module._invoke_retriever("official", official.OfficialSearch,
                query="unlisted filtering", sub_questions=[], adapted_queries=["unlisted filtering"])
    try:
        first, _, disposition = await invoke("before")
        assert first.results == [] and disposition == "miss"
        assert len(learned_docs.harvest(["unlisted"], [{"source": "tavily", "results": [
            {"url": url, "title": "Unlisted docs"}]}], existing=set())) == 1
        second, _, disposition = await invoke("after")
        assert disposition == "miss" and len(second.results) == 1
        third, _, disposition = await invoke("unchanged")
        assert disposition == "hit" and third.results == second.results
        assert get.await_count == 1
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_official_mapping_written_during_dispatch_does_not_cache_under_old_identity(tmp_path, monkeypatch):
    from deepchoice.retrievers import learned_docs
    path = tmp_path / "learned.json"
    monkeypatch.setattr(learned_docs, "LEARNED_DOCS_PATH", path)
    connection, store = await _store(tmp_path)
    calls = 0
    class Retriever:
        async def retrieve(self, request):
            nonlocal calls
            calls += 1
            if calls == 1:
                path.write_text('{"unlisted":{"url":"https://docs.unlisted.example/docs/"}}', encoding="utf-8")
            return _success("official")
    async def invoke():
        with bind_run_context(_context(store)):
            return await multi_module._invoke_retriever("official", Retriever,
                query="unlisted", sub_questions=[], adapted_queries=[])
    try:
        assert (await invoke())[2] == "miss"
        assert (await invoke())[2] == "miss"
        assert (await invoke())[2] == "hit"
        assert calls == 2
        assert store._flights == {}
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_invalid_official_mapping_bypasses_cache_and_singleflight(tmp_path, monkeypatch):
    from deepchoice.retrievers import learned_docs
    path = tmp_path / "learned.json"
    path.write_text("invalid fixture", encoding="utf-8")
    monkeypatch.setattr(learned_docs, "LEARNED_DOCS_PATH", path)
    connection, store = await _store(tmp_path)
    calls = 0
    class Retriever:
        async def retrieve(self, request):
            nonlocal calls
            calls += 1
            return _success("official")
    try:
        with bind_run_context(_context(store)):
            for _ in range(2):
                assert (await multi_module._invoke_retriever("official", Retriever,
                    query="unlisted", sub_questions=[], adapted_queries=[]))[2] == "bypass"
        assert calls == 2 and store._flights == {}
    finally:
        await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["malformed", "write"])
async def test_successful_fanout_survives_learning_failure(tmp_path, monkeypatch, failure):
    from deepchoice.retrievers import learned_docs
    path = tmp_path / "learned.json"
    monkeypatch.setattr(learned_docs, "LEARNED_DOCS_PATH", path)
    monkeypatch.setattr(learned_docs, "_READONLY", False)
    if failure == "malformed":
        path.write_bytes(b"[]")
    else:
        def denied(*args):
            raise PermissionError("unwritable local mapping")
        monkeypatch.setattr(learned_docs, "_atomic_write_text", denied)
    calls = 0
    items = [{"url": "https://unlisted.example/docs/", "title": "Unlisted", "snippet": "Saved evidence"}]
    class Retriever:
        source = "official"
        async def retrieve(self, request):
            nonlocal calls
            calls += 1
            return _success(self.source, results=items)
    connection, store = await _store(tmp_path)
    try:
        agent = MultiRetrieverAgent(retriever_registry={"official": Retriever})
        with bind_run_context(_context(store)):
            for _ in range(2):
                result = await agent.run({"task": {"query": "unlisted"}, "sub_questions": []})
                assert result["search_results"][0]["results"] == items
                assert not result["partial_failures"]
        # Invalid mapping cannot authorize cache reuse; a failed write leaves the
        # valid empty identity intact and its already fetched evidence reusable.
        assert calls == (2 if failure == "malformed" else 1)
        if failure == "malformed":
            assert path.read_bytes() == b"[]"
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_cached_blank_official_scope_still_requires_actual_selection(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from deepchoice.agents.source_evaluator import SourceEvaluatorAgent
    from deepchoice.contracts.manifest import build_run_manifest
    from deepchoice.utils.source_scope import scope_sentences

    connection, store = await _store(tmp_path)
    query = "Acme字段过滤"
    text = "Acme filters indexed fields using the configured predicate. However, applications must enforce authorization separately."
    item = {"url": "https://docs.acme.example/docs/", "title": "Acme guide", "snippet": "",
            "_source_scope_sentences": list(scope_sentences(text))}
    monkeypatch.setattr(multi_module, 'official_mapping_identity', lambda: 'a' * 64)
    request = RetrievalRequest(query=query, max_results=7, official_mapping_id='a' * 64)
    key = store.make_key(source='official', request=request, manifest_id='manifest-1')

    class Retriever:
        source = 'official'

        async def retrieve(self, request):
            raise AssertionError('cached proposal must not retrieve again')

    selector = AsyncMock(return_value={"sources": []})
    monkeypatch.setattr('deepchoice.utils.llm.call_model', selector)
    try:
        assert await store.put(key, _success('official', results=[item]), source='official')
        with bind_run_context(_context(store)):
            cached, _, hit = await multi_module._invoke_retriever(
                'official', Retriever, query=query, sub_questions=[], adapted_queries=[])
            assert hit == 'hit' and cached.results == [item]
            state = {'task': {'query': query, 'candidate_techs': ['Acme']},
                     'search_results': [cached.model_dump()]}
            agent = SourceEvaluatorAgent(run_manifest=build_run_manifest({}))
            assert not (await agent.run(state))['source_scores']
            selector.return_value = {'sources': [{'id': 'S1', 'ranges': [[0, len(item['_source_scope_sentences'])]]}]}
            selected = await agent.run(state)
            assert selected['source_scores'][0]['passages'] == [text]
        assert selector.await_count == 2
    finally:
        await connection.close()
