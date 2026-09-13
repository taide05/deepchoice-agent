import pytest
from pydantic import ValidationError

from deepchoice.agents.multi_retriever import MultiRetrieverAgent
from deepchoice.retrievers import (
    RETRIEVER_REGISTRY,
    ArxivSearch,
    ChromaKB,
    CommunitySearch,
    GitHubSearch,
    OfficialSearch,
    TavilySearch,
)
from deepchoice.retrievers.base import BaseRetriever, error_text
from deepchoice.retrievers.contracts import (
    RetrievalRequest,
    RetrievalResult,
    RetrieverPort,
)


def _ok(source="test"):
    return RetrievalResult(
        source=source,
        status="success",
        results=[{"url": "https://example.test"}],
        latency_ms=1,
    )


def test_request_is_frozen_and_forbids_extra_fields():
    request = RetrievalRequest(query="compare frameworks")
    assert request.schema_version == 1
    with pytest.raises(ValidationError):
        request.query = "changed"
    with pytest.raises(ValidationError):
        RetrievalRequest(query="x", unexpected=True)
    with pytest.raises(ValidationError):
        RetrievalRequest(query=" ")
    with pytest.raises(ValidationError):
        RetrievalRequest(query="x", max_results=101)
    with pytest.raises(ValidationError):
        request.sub_questions += ("new",)
    with pytest.raises(ValidationError):
        RetrievalRequest(query="x", sub_questions=[""])
    with pytest.raises(ValidationError):
        RetrievalRequest(query="x", adapted_queries=[" "])
    with pytest.raises(ValidationError):
        RetrievalRequest(query="x" * 4001)


@pytest.mark.parametrize(
    "payload",
    [
        {"source": "x", "status": "success", "error": "bad", "latency_ms": 0},
        {"source": "x", "status": "failed", "results": [{"x": 1}], "error": "bad", "latency_ms": 0},
        {"source": "x", "status": "failed", "error": " ", "latency_ms": 0},
        {"source": "x", "status": "success", "latency_ms": -1},
    ],
)
def test_result_validates_cross_field_invariants(payload):
    with pytest.raises(ValidationError):
        RetrievalResult.model_validate(payload)


def test_retriever_port_is_runtime_checkable():
    class Stable:
        source = "stable"

        async def retrieve(self, request):
            return _ok(self.source)

    assert isinstance(Stable(), RetrieverPort)


class _SuccessRetriever(BaseRetriever):
    source = "success"

    async def _do_search(self, query, sub_questions, max_results, adapted_queries=None):
        return [{"query": query, "adapted": adapted_queries}]


class _FailureRetriever(BaseRetriever):
    source = "failure"

    async def _do_search(self, query, sub_questions, max_results, adapted_queries=None):
        raise RuntimeError("broken")


class _InvalidateFailureRetriever(BaseRetriever):
    source = "invalidate_failure"

    async def _do_search(self, query, sub_questions, max_results, adapted_queries=None):
        raise RuntimeError("original retrieval failure")


@pytest.mark.asyncio
async def test_base_retriever_stable_and_legacy_paths():
    success = _SuccessRetriever()
    result = await success.retrieve(RetrievalRequest(query="x"))
    assert result.status == "success"
    assert (await success.search("x", []))["status"] == "success"

    failed = await _FailureRetriever().retrieve(RetrievalRequest(query="x"))
    assert failed.status == "failed"
    assert failed.results == []
    assert "RuntimeError" in failed.error


@pytest.mark.asyncio
async def test_base_retriever_keeps_original_error_when_invalidate_fails(monkeypatch):
    class Resolver:
        async def invalidate(self, source):
            raise OSError("resolver unavailable")

    monkeypatch.setattr(
        "deepchoice.retrievers.base._outbound.get_resolver", lambda: Resolver()
    )
    result = await _InvalidateFailureRetriever().retrieve(RetrievalRequest(query="x"))
    assert result.status == "failed"
    assert result.error == "RuntimeError"


def test_registry_classes_keep_six_keys_and_stable_base_port():
    assert list(RETRIEVER_REGISTRY) == ["tavily", "chroma", "github", "arxiv", "community", "official"]
    for cls in RETRIEVER_REGISTRY.values():
        assert issubclass(cls, BaseRetriever)
        assert hasattr(cls, "retrieve")
        assert cls.retrieve is BaseRetriever.retrieve


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["stable", "legacy", "invalid"])
async def test_multi_retriever_validates_stable_legacy_and_invalid_results(kind, monkeypatch):
    class Fake:
        source = "fake"

        async def retrieve(self, request):
            if kind == "invalid":
                return {"source": "fake", "status": "success", "results": [], "error": "oops", "latency_ms": 0}
            return _ok(self.source)

        async def search(self, query, sub_questions, max_results=7, adapted_queries=None):
            return _ok(self.source).model_dump()

    class Legacy:
        source = "fake"

        async def search(self, query, sub_questions, max_results=7, adapted_queries=None):
            return _ok(self.source).model_dump()

    cls = Fake if kind != "legacy" else Legacy
    monkeypatch.setattr(
        "deepchoice.agents.multi_retriever.RETRIEVER_REGISTRY",
        {"fake": cls},
    )
    state = {"task": {"query": "x"}, "sub_questions": []}
    result = await MultiRetrieverAgent().run(state)
    envelope = result["search_results"][0]
    assert set(envelope) == {"source", "status", "results", "error", "latency_ms"}
    if kind == "invalid":
        assert envelope["status"] == "failed"
        assert result["partial_failures"] == ["fake"]
    else:
        assert envelope["status"] == "success"
        assert result["partial_failures"] == []


@pytest.mark.asyncio
async def test_multi_retriever_rejects_source_provenance_mismatch(monkeypatch):
    class Fake:
        source = "wrong"

        async def retrieve(self, request):
            return _ok("wrong")

    monkeypatch.setattr(
        "deepchoice.agents.multi_retriever.RETRIEVER_REGISTRY", {"expected": Fake}
    )
    result = await MultiRetrieverAgent().run({"task": {"query": "x"}, "sub_questions": []})
    envelope = result["search_results"][0]
    assert envelope["source"] == "expected"
    assert envelope["status"] == "failed"
    assert "RetrievalContractError" in envelope["error"]
    assert result["partial_failures"] == ["expected"]


@pytest.mark.asyncio
async def test_multi_retriever_accepts_registry_injection_without_module_patching():
    class Fake:
        source = "injected"

        async def retrieve(self, request):
            return _ok(self.source)

    result = await MultiRetrieverAgent(
        retriever_registry={"injected": Fake},
    ).run({"task": {"query": "x"}, "sub_questions": []})

    assert result["search_results"][0]["source"] == "injected"
    assert result["quality_signals"][0]["retrievers_used"] == 1


@pytest.mark.asyncio
async def test_invalid_internal_query_adaptation_is_an_isolated_contract_failure():
    class Fake:
        source = "injected"

        async def retrieve(self, request):
            raise AssertionError("invalid request must not reach the retriever")

    result = await MultiRetrieverAgent(
        retriever_registry={"injected": Fake},
    ).run(
        {
            "task": {"query": "x"},
            "sub_questions": ["a sufficiently detailed research question"],
            "adapted_queries": {"injected": [""]},
        }
    )

    envelope = result["search_results"][0]
    assert envelope["status"] == "failed"
    assert "RetrievalContractError" in envelope["error"]
    assert result["partial_failures"] == ["injected"]


@pytest.mark.asyncio
async def test_generic_sub_question_supplement_stays_within_contract_limit():
    captured = {}

    class Fake:
        source = "injected"

        async def retrieve(self, request):
            captured["request"] = request
            return _ok(self.source)

    result = await MultiRetrieverAgent(
        retriever_registry={"injected": Fake},
    ).run({"task": {"query": "x"}, "sub_questions": ["short"] * 20})

    assert result["search_results"][0]["status"] == "success"
    assert len(captured["request"].sub_questions) == 20


@pytest.mark.asyncio
async def test_registry_is_snapshotted_before_awaiting_retrievers():
    registry = {}

    class First:
        source = "first"

        async def retrieve(self, request):
            registry.clear()
            registry["replacement"] = First
            return _ok(self.source)

    registry["first"] = First
    result = await MultiRetrieverAgent(retriever_registry=registry).run(
        {"task": {"query": "x"}, "sub_questions": []}
    )

    assert [item["source"] for item in result["search_results"]] == ["first"]


@pytest.mark.asyncio
async def test_contract_failure_does_not_reflect_sensitive_input():
    secret = "token-super-secret"

    class Fake:
        source = "fake"

        async def retrieve(self, request):
            return {
                "source": "fake",
                "status": "success",
                "results": [],
                "error": secret,
                "latency_ms": 0,
            }

    result = await MultiRetrieverAgent(retriever_registry={"fake": Fake}).run(
        {"task": {"query": "x"}, "sub_questions": []}
    )

    error = result["search_results"][0]["error"]
    assert "RetrievalContractError" in error
    assert secret not in error


@pytest.mark.asyncio
async def test_provider_failure_does_not_reflect_sensitive_message():
    secret = "https://user:password@example.test/?token=super-secret"

    class Failing(BaseRetriever):
        source = "failing"

        async def _do_search(self, *args, **kwargs):
            raise RuntimeError(secret)

    result = await Failing().retrieve(RetrievalRequest(query="x"))

    assert result.error == "RuntimeError"
    assert secret not in result.error


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_kind", ["constructor", "sync_result"])
async def test_broken_retriever_implementation_is_isolated(failure_kind):
    class Broken:
        source = "broken"

        def __init__(self):
            if failure_kind == "constructor":
                raise RuntimeError("provider secret")

        def retrieve(self, request):
            return {"not": "awaitable"}

    result = await MultiRetrieverAgent(retriever_registry={"broken": Broken}).run(
        {"task": {"query": "x"}, "sub_questions": []}
    )

    envelope = result["search_results"][0]
    assert envelope["status"] == "failed"
    assert result["partial_failures"] == ["broken"]
    assert "provider secret" not in envelope["error"]


def test_error_status_code_must_be_a_valid_integer():
    class MaliciousStatusError(Exception):
        status_code = "secret-status-value"

    assert error_text(MaliciousStatusError("secret-message")) == "MaliciousStatusError"
