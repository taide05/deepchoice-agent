"""Metadata priority and non-increasing restricted evidence projection."""
import copy
from datetime import datetime
from unittest.mock import AsyncMock

import numpy as np
import pytest

from deepchoice.agents import source_evaluator, conflict_detector
from deepchoice.agents.evidence_chain import build_evidence_chain
from deepchoice.budget.limited import usable_evidence_chains, minimum_evidence_is_met, build_budget_limited_state
from tests.test_phase2c_limited_results import _chain, _budget_error, DEFAULT_RUN_BUDGET_POLICY


@pytest.fixture(autouse=True)
def fixed_date(monkeypatch):
    class FrozenDate(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 8, tzinfo=tz)
    monkeypatch.setattr(source_evaluator, "datetime", FrozenDate)


async def score(url, text, date=""):
    result=await source_evaluator.SourceEvaluatorAgent().run({
        "task":{"query":"Alpha journal", "candidate_techs":["Alpha"]},
        "search_results":[{"source":"tavily","results":[{
            "url":url,"title":"Alpha journal","snippet":text,"date":date,
        }]}],
    })
    return result["source_scores"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["https://example.org/doc", "https://github.com/alpha/docs", "https://arxiv.org/abs/123", "https://stackoverflow.com/questions/123", "https://docs.python.org/3/"])
async def test_default_priority_is_invariant_to_irrelevant_words_and_language(url):
    prose=["Alpha requires a journal.", "Alpha requires a journal; the page mentions pip install.",
        "Alpha requires a journal; the page mentions latency.", "I think Alpha requires a journal.",
        "Alpha需要配置日志。", "Alpha requires a journal; reference [1]."]
    rows=[await score(url,text) for text in prose]
    assert len({r["total_score"] for r in rows})==1
    assert all(r["evidence_type"]=="unassessed" for r in rows)
    assert all(r["scores"]["consistency"] is None and r["scores"]["verifiability"] is None for r in rows)
    assert all(r["supporting_sources"]==[] for r in rows)
    assert len({build_evidence_chain([r],[])[0]["evidence_strength"] for r in rows})==1


@pytest.mark.asyncio
async def test_removed_opinion_penalty_crosses_scan_threshold_without_keyword_gate(monkeypatch):
    row=await score("https://example.org/a","I think Alpha requires a journal.")
    old=source_evaluator.compute_total_score({"authority":7,"timeliness":5,"consistency":4,"verifiability":2})
    assert old==4.9 and row["total_score"]==5.7
    class Embedding:
        def encode(self, titles):
            return np.ones((len(titles),2))
    monkeypatch.setattr(conflict_detector,"get_embedding_model",lambda:Embedding())
    scan=AsyncMock(return_value=None)
    monkeypatch.setattr(conflict_detector,"_scan_pair_contradiction",scan)
    assert await conflict_detector.find_contradictions([row,{**row,"url":"https://example.net/b"}])==[]
    scan.assert_awaited_once()
    scan.reset_mock()
    assert await conflict_detector.find_contradictions([{**row,"total_score":old},{**row,"url":"https://example.net/b","total_score":old}])==[]
    scan.assert_not_awaited()


@pytest.mark.asyncio
async def test_removed_opinion_penalty_changes_structural_gate_explicitly():
    row=await score("https://github.com/alpha/docs","I think Alpha requires a journal.","2026-06-01")
    old=source_evaluator.compute_total_score({"authority":6,"timeliness":8,"consistency":4,"verifiability":2})
    assert old==5.3 and row["total_score"]==6.1
    other=[await score("https://example.org/"+name,"Alpha requires a journal.") for name in ("a","b")]
    state={"evidence_chains":build_evidence_chain([row,*other],[]),"conflicts":[]}
    assert minimum_evidence_is_met(state)
    before={"evidence_chains":build_evidence_chain([{**row,"total_score":old},*other],[]),"conflicts":[]}
    assert not minimum_evidence_is_met(before)


@pytest.mark.parametrize("raw_strength,score_value,expected", [("weak",9,"weak"),("moderate",9,"moderate"),("strong",9,"strong"),("strong",6,"moderate"),("strong",5,"weak"),(None,9,"weak"),("forged",9,"weak"),([],9,"weak")])
def test_limited_projection_cannot_raise_original_strength(raw_strength,score_value,expected):
    chain=_chain("https://example.org/a",strength=raw_strength,score=score_value)
    result=usable_evidence_chains({"evidence_chains":[chain],"conflicts":[]})
    assert result[0]["evidence_strength"]==expected
    assert usable_evidence_chains({"evidence_chains":result,"conflicts":[]})==result


@pytest.mark.parametrize("mode", ["invalid_url", "low_score", "duplicate", "already_used", "malformed", "navigation", "nonfinite", "empty"])
def test_limited_filtering_cannot_carry_forward_original_strong(mode):
    chain=_chain("https://example.org/a",strength="strong",score=9)
    extra=copy.deepcopy(chain["sources"][0]);extra["url"]="https://example.net/b"
    preceding=[]
    if mode=="invalid_url": extra["url"]="file:///private"
    elif mode=="low_score": extra["score"]=3
    elif mode=="duplicate": extra["url"]="https://EXAMPLE.org:443/a"
    elif mode=="already_used": preceding=[_chain(extra["url"],strength="moderate",score=9)]
    elif mode=="malformed": extra=None
    elif mode=="navigation": extra["snippet"]="Official documentation site for Alpha."
    elif mode=="nonfinite": extra["score"]=float("nan")
    elif mode=="empty": extra.update(title="",snippet="")
    chain["sources"].append(extra)
    output=usable_evidence_chains({"evidence_chains":[*preceding,chain],"conflicts":[]})
    assert output[-1]["evidence_strength"]=="moderate"
    assert len(output[-1]["sources"])==1


@pytest.mark.parametrize("existing", [True,False])
@pytest.mark.parametrize("route", ["budget", "hitl"])
def test_budget_report_does_not_upgrade_default_single_source_chain(existing, route):
    scores=[{"url":url,"title":"Alpha journal","snippet":"Alpha requires a journal.","total_score":8,"supporting_sources":[]}
            for url in ("https://example.org/a","https://example.org/b","https://example.net/c")]
    state={"source_scores":scores,"conflicts":[]}
    if existing: state["evidence_chains"]=build_evidence_chain(scores,[])
    request={"query":"Alpha journal","report_format":"evidence_first"}
    if route=="budget":
        out=build_budget_limited_state(state,request=request,policy=DEFAULT_RUN_BUDGET_POLICY,error=_budget_error(state))
    else:
        from deepchoice.agents.evidence_decision_gate import _build_limited_report
        out=_build_limited_report({**state,"task":request})
    assert out is not None
    assert {c["evidence_strength"] for c in out["evidence_chains"]}=={"moderate"}
    if route=="budget":
        assert out["budget_limited"]["minimum_evidence_met"] is True
    else:
        assert out["_hitl_limited_report"] is True



def test_disputed_chain_does_not_poison_later_source_deduplication():
    first=_chain("https://example.org/shared",strength="strong",score=9)
    bad=copy.deepcopy(first["sources"][0]);bad["url"]="https://example.net/disputed"
    first["sources"].append(bad)
    later=_chain("https://example.org/shared",strength="moderate",score=9)
    out=usable_evidence_chains({"evidence_chains":[first,later],"conflicts":[{"source_a":{"url":bad["url"]}}]})
    assert len(out)==1 and out[0]["evidence_strength"]=="moderate"
    assert out[0]["sources"][0]["url"]=="https://example.org/shared"


@pytest.mark.asyncio
@pytest.mark.parametrize("historical", [False,True])
async def test_public_result_roundtrip_preserves_unknown_or_historical_score_fields(historical):
    from tests.test_phase2c_limited_results import _records, NOW
    from deepchoice.runtime.coordinator import build_public_run_result
    row=await score("https://example.org/doc","Alpha requires a journal.")
    if historical:
        row["scores"].update(consistency=4,verifiability=10)
        row["evidence_type"]="code"
    task,run=_records("priority-task","priority-run")
    artifact=build_public_run_result(run,task.request.model_dump(),{"source_scores":[row],"report":"A bounded test report."},created_at=NOW)
    restored=type(artifact).model_validate_json(artifact.model_dump_json())
    assert restored.snapshot["source_scores"]==[row]
    assert restored.snapshot["source_scores"][0]["scores"]["consistency"] == (4 if historical else None)
