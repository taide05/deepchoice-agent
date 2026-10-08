"""Actual clarification ports with synthetic model snapshots, never live quality scores."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from deepchoice.clarify import clarification_agent as agent_module
from deepchoice.clarify.session_manager import SessionManager
from deepchoice.contracts.api import ResearchRequest
from deepchoice.server import clarify_routes as routes
from deepchoice.utils.query_context import query_request_context


def snapshot(query, **changes):
    return {"current_query": query, "scene": "team", "complexity": "medium",
            "candidate_techs": ["Redis", "PostgreSQL"], "constraints": ["Redis is required"],
            "unknown_techs": False, "action": "confirm", "message": "MODEL SUMMARY MUST NOT OWN CONFIRMATION",
            **changes}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(routes, "session_manager", SessionManager())
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        yield client


def test_initial_negative_mention_does_not_select_candidate():
    manager = SessionManager()
    sid = manager.create("Do not use Redis. Compare SQLite and PostgreSQL.")["session_id"]
    state = manager.get(sid)
    assert state.candidate_techs == []
    assert "candidate_techs" in state.missing_required


def test_revision_reaches_confirmation_finalize_and_execution_context(client, monkeypatch):
    original = "Compare Redis and PostgreSQL for a team; Redis is required."
    current = "Compare SQLite and PostgreSQL for a simple solo project; Redis is excluded."
    model = AsyncMock(side_effect=[snapshot(original), snapshot(current, scene="solo", complexity="simple",
        candidate_techs=["SQLite", "PostgreSQL"], constraints=["Redis is excluded"]), {"sub_questions": ["Which option needs a server?"]}])
    monkeypatch.setattr(agent_module, "call_model", model)
    start = client.post("/clarify/start", json={"query": original}).json()
    sid = start["session_id"]
    response = client.post(f"/clarify/{sid}/message", json={"message": current})
    assert response.status_code == 200
    confirmation = response.json()
    task = confirmation["payload"]["clarified_task"]
    assert task["query"] == current
    assert task["candidate_techs"] == ["SQLite", "PostgreSQL"]
    assert task["scene_context"] == "solo" and task["complexity"] == "simple"
    assert task["constraints"] == ["Redis is excluded"]
    assert task["original_query"] == original
    assert "MODEL SUMMARY" not in confirmation["answer"]
    finalized = client.post(f"/clarify/{sid}/finalize", json={"clarify_rounds": confirmation["clarify_rounds"]})
    assert finalized.status_code == 200
    assert finalized.json()["payload"]["clarified_task"] == task
    prompt = model.await_args_list[-1].args[0][0]["content"]
    assert current in prompt and original not in prompt
    execution = query_request_context(ResearchRequest.model_validate(task).model_dump())
    assert execution["query"] == current and "original_query" not in execution
    assert original not in json.dumps(execution)
    assert model.await_count == 3


def test_explicit_clear_preserves_unknown_and_removes_old_requirements(client, monkeypatch):
    query = "Compare Redis and PostgreSQL"
    model = AsyncMock(side_effect=[snapshot(query), snapshot("Choose a datastore; previous requirements are withdrawn.",
        scene=None, complexity=None, candidate_techs=[], constraints=[], unknown_techs=True), {"sub_questions": []}])
    monkeypatch.setattr(agent_module, "call_model", model)
    sid = client.post("/clarify/start", json={"query": query}).json()["session_id"]
    client.post(f"/clarify/{sid}/message", json={"message": "Withdraw previous requirements; I do not know the scope or candidates."})
    state = routes.session_manager.get(sid)
    assert state.candidate_techs == [] and state.constraints == []
    assert state.scene is None and state.complexity is None
    assert state.clarified_task is None and state.status == "clarifying"
    # Skip ends questioning with a review; it cannot submit an undisplayed rewrite.
    assert client.post(f"/clarify/{sid}/finalize").status_code == 409
    review = client.post(f"/clarify/{sid}/finalize", json={"review_only": True})
    assert review.status_code == 200 and review.json()["action"] == "confirm"
    result = client.post(f"/clarify/{sid}/finalize", json={"clarify_rounds": 1})
    assert result.status_code == 200
    task = result.json()["payload"]["clarified_task"]
    assert task["scene_context"] is None and task["complexity"] is None
    assert task["constraints"] == [] and task["candidate_techs"] == []


@pytest.mark.parametrize("bad", [{"scene": "solo"}, snapshot("new", constraints="not a list"),
    snapshot("new", current_query="x" * 4001), snapshot("new", complexity="invalid")])
def test_bad_revision_cannot_confirm_or_skip_stale_snapshot(client, monkeypatch, bad):
    query = "Compare Redis and PostgreSQL"
    model = AsyncMock(side_effect=[snapshot(query), bad])
    monkeypatch.setattr(agent_module, "call_model", model)
    sid = client.post("/clarify/start", json={"query": query}).json()["session_id"]
    response = client.post(f"/clarify/{sid}/message", json={"message": "Remove Redis and use SQLite for solo use"})
    assert response.status_code == 200 and response.json()["next_action"] == "ask"
    state = routes.session_manager.get(sid)
    assert state.status == "clarifying" and state.clarified_task is None
    assert state.scene == "team" and state.constraints == ["Redis is required"]  # Uncommitted draft.
    assert client.post(f"/clarify/{sid}/finalize").status_code == 409
    assert client.post(f"/clarify/{sid}/finalize", json={"clarify_rounds": 0}).status_code == 409
    assert model.await_count == 2


def test_old_confirmation_revision_rejected_without_model_call(client, monkeypatch):
    query = "Compare Redis and PostgreSQL"
    model = AsyncMock(side_effect=[snapshot(query), snapshot("Compare SQLite and PostgreSQL", candidate_techs=["SQLite", "PostgreSQL"], constraints=[])])
    monkeypatch.setattr(agent_module, "call_model", model)
    sid = client.post("/clarify/start", json={"query": query}).json()["session_id"]
    client.post(f"/clarify/{sid}/message", json={"message": "Replace Redis with SQLite"})
    assert client.post(f"/clarify/{sid}/finalize", json={"clarify_rounds": 0}).status_code == 409
    assert model.await_count == 2


async def test_late_model_response_cannot_overwrite_a_new_reply(monkeypatch):
    manager = SessionManager()
    monkeypatch.setattr(routes, "session_manager", manager)
    query = "Compare Redis and PostgreSQL"
    sid = manager.create(query)["session_id"]
    started, release = asyncio.Event(), asyncio.Event()
    async def delayed(*args, **kwargs):
        started.set()
        await release.wait()
        return snapshot(query)
    monkeypatch.setattr(agent_module, "call_model", delayed)
    old = asyncio.create_task(routes._respond(manager.get(sid)))
    await asyncio.wait_for(started.wait(), timeout=5)
    manager.process_message(sid, "Replace Redis with SQLite")
    release.set()
    with pytest.raises(HTTPException) as error:
        await old
    assert error.value.status_code == 409
    assert manager.get(sid).candidate_techs == []
    assert manager.get(sid).clarified_task is None


def test_audit_query_is_bounded_and_included_in_aggregate_admission():
    request = ResearchRequest(query="Current request", original_query="o" * 4000)
    assert request.original_query == "o" * 4000
    for original in ("o" * 4001, "unsafe\u202equery"):
        with pytest.raises(ValueError):
            ResearchRequest(query="Current request", original_query=original)
    # 31,000 execution characters are legal, +4,000 audit characters are not.
    values = dict(query="q" * 4000, constraints=["c" * 500] * 50,
                  candidate_techs=["a" * 500] * 4)
    ResearchRequest(**values)
    with pytest.raises(ValueError):
        ResearchRequest(**values, original_query="o" * 4000)


def test_failed_replies_are_preserved_until_resolved_and_have_a_total_bound(client, monkeypatch):
    query = "Compare Redis and PostgreSQL"
    model = AsyncMock(side_effect=[snapshot(query), RuntimeError("failure"), RuntimeError("failure")])
    monkeypatch.setattr(agent_module, "call_model", model)
    sid = client.post("/clarify/start", json={"query": query}).json()["session_id"]
    first, second = "First change " + "a" * 1987, "Second change " + "b" * 1986
    assert len(first) == len(second) == 2000
    client.post(f"/clarify/{sid}/message", json={"message": first})
    client.post(f"/clarify/{sid}/message", json={"message": second})
    prompt = model.await_args.args[0][0]["content"]
    assert first in prompt and second in prompt
    before = routes.session_manager.get(sid).model_dump()
    rejected = client.post(f"/clarify/{sid}/message", json={"message": "A third change"})
    assert rejected.status_code == 422
    assert routes.session_manager.get(sid).model_dump() == before
    assert model.await_count == 3


async def test_new_reply_invalidates_inflight_finalize(monkeypatch):
    manager = SessionManager()
    monkeypatch.setattr(routes, "session_manager", manager)
    query = "Compare Redis and PostgreSQL"
    sid = manager.create(query)["session_id"]
    monkeypatch.setattr(agent_module, "call_model", AsyncMock(return_value=snapshot(query)))
    await routes._respond(manager.get(sid))
    started, release = asyncio.Event(), asyncio.Event()
    async def delayed(*args, **kwargs):
        started.set()
        await release.wait()
        return {"sub_questions": ["Old question"]}
    monkeypatch.setattr(agent_module, "call_model", delayed)
    old = asyncio.create_task(routes.clarify_finalize(sid, routes.FinalizeRequest(clarify_rounds=0)))
    await asyncio.wait_for(started.wait(), timeout=5)
    manager.process_message(sid, "Replace Redis with SQLite")
    release.set()
    with pytest.raises(HTTPException) as error:
        await old
    assert error.value.status_code == 409
    state = manager.get(sid)
    assert state.status == "clarifying" and state.clarified_task is None and state.sub_questions is None


@pytest.mark.parametrize("count", [39, 40])
def test_session_reserves_capacity_for_the_assistant_before_accepting_input(count):
    manager = SessionManager()
    sid = manager.create("Compare Redis and PostgreSQL")["session_id"]
    state = manager.get(sid)
    state.messages = [state.messages[0], *[{"role": "assistant", "content": "Question"}] * (count - 1)]
    before = state.model_dump()
    with pytest.raises(ValueError):
        manager.process_message(sid, "Use SQLite instead")
    assert state.model_dump() == before
    if count == 40:
        with pytest.raises(ValueError):
            manager.finalize(sid)
        assert state.model_dump() == before


@pytest.mark.parametrize("review_first", [False, True])
def test_skip_does_not_execute_unshown_model_rewrite(client, monkeypatch, review_first):
    original = "Compare Redis and PostgreSQL"
    invented = "Must migrate to SQLite and accept data loss"
    model = AsyncMock(side_effect=[snapshot(invented, scene=None, complexity=None, constraints=["Accept data loss"]),
                                  {"sub_questions": ["What deployment requirements apply?"]}])
    monkeypatch.setattr(agent_module, "call_model", model)
    response = client.post("/clarify/start", json={"query": original}).json()
    assert response["next_action"] == "ask" and "payload" not in response
    sid = response["session_id"]
    if review_first:
        review = client.post(f"/clarify/{sid}/finalize", json={"review_only": True})
        assert review.status_code == 200 and review.json()["action"] == "confirm"
        assert review.json()["payload"]["clarified_task"]["query"] == invented
        assert model.await_count == 1
        # Only an explicit current confirmation may submit the shown rewrite.
        result = client.post(f"/clarify/{sid}/finalize", json={"clarify_rounds": 0})
        assert result.json()["payload"]["clarified_task"]["query"] == invented
    else:
        result = client.post(f"/clarify/{sid}/finalize")
        task = result.json()["payload"]["clarified_task"]
        assert task["query"] == original and "original_query" not in task
        assert task["constraints"] == [] and task["candidate_techs"] == []
        assert invented not in model.await_args.args[0][0]["content"]
    assert result.status_code == 200 and model.await_count == 2


@pytest.mark.parametrize("audit", [None, "Original request"])
def test_optional_audit_field_preserves_historical_canonical_serialization(audit):
    request = ResearchRequest(query="Current request", original_query=audit)
    projections = [request.model_dump(), request.model_dump(mode="json", exclude_none=False),
                   json.loads(request.model_dump_json())]
    for data in projections:
        if audit is None:
            assert "original_query" not in data
        else:
            assert data["original_query"] == audit
        assert ResearchRequest.model_validate(data) == request
