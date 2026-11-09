"""Comparative query coverage is deterministic even when the LLM omits a side."""
import asyncio


from deepchoice.agents import query_adapter as qa


def _state():
    return {
        "task": {"query": "Sigstore vs Notation", "candidate_techs":
                 ["Sigstore (Cosign)", "Notary Project (Notation)"],
                 "constraints": []},
        "sub_questions": ["which signs OCI images?"],
        "token_usage": [],
    }


def test_missing_candidate_gets_a_combined_tavily_query(monkeypatch):
    async def fake_call_model(prompt, **kwargs):
        return {"adapted": [{"sub_question_index": 0,
                             "sub_question": "which signs OCI images?",
                             "tavily": "Sigstore Cosign OCI signing"}]}

    monkeypatch.setattr(qa, "call_model", fake_call_model)
    out = asyncio.run(qa.QueryAdapterAgent().run(_state()))
    tavily = out["adapted_queries"]["tavily"]
    assert any("Notary Project" in query and "Sigstore" in query for query in tavily)
    assert out["quality_signals"][0]["candidate_coverage_query_added"] is True


def test_fully_covered_candidates_do_not_add_a_query(monkeypatch):
    async def fake_call_model(prompt, **kwargs):
        return {"adapted": [{"sub_question_index": 0,
                             "sub_question": "which signs OCI images?",
                             "tavily": "Sigstore Cosign and Notary Project Notation"}]}

    monkeypatch.setattr(qa, "call_model", fake_call_model)
    out = asyncio.run(qa.QueryAdapterAgent().run(_state()))
    assert out["quality_signals"][0]["candidate_coverage_query_added"] is False


def test_partial_shared_words_do_not_count_as_candidate_coverage(monkeypatch):
    state = _state()
    state["task"]["candidate_techs"] = ["Amazon EKS", "Amazon Linux 2023"]

    async def fake_call_model(prompt, **kwargs):
        return {"adapted": [{"sub_question_index": 0,
                             "sub_question": "which runtime?",
                             "tavily": "Amazon cloud pricing overview"}]}

    monkeypatch.setattr(qa, "call_model", fake_call_model)
    out = asyncio.run(qa.QueryAdapterAgent().run(state))
    assert out["quality_signals"][0]["candidate_coverage_query_added"] is True
    assert any("Amazon EKS" in q and "Amazon Linux" in q
               for q in out["adapted_queries"]["tavily"])
