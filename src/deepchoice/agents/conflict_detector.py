import asyncio
import json
import os
import time

import httpx
import numpy as np

from .. import outbound as _outbound
from ..retrievers.tavily_keypool import post_with_failover
from ..utils.candidate_identity import has_factual_content, source_content
from ..utils.embedding import get_embedding_model
from ..utils.llm import call_model, summarize_usage
from ..utils.views import print_agent_output

# ---------------------------------------------------------------------------
# Concurrency limit for the DeepSeek flash tier (500/min).
# Env-tunable — set LLM_DS_CONCURRENCY to the provider RPM.
# ---------------------------------------------------------------------------
FLASH_SEM = asyncio.Semaphore(int(os.environ.get("LLM_DS_CONCURRENCY", "80")))

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

ARBITRATION_SYSTEM = """You are an impartial technical arbitrator. Two sources make claims about the same topic but may disagree.

Rules:
1. If scores differ by >=2.5 points, the higher-scored source is more likely correct
2. If both have code/benchmark evidence, both may be partially right (different contexts)
3. If neither has strong evidence, declare "insufficient_data"
4. Your reasoning MUST cite the score difference or evidence type difference
5. NEVER mention rule numbers, these rules, or internal scoring logic in your output. Write the reasoning in reader-facing terms ("the score gap is below the decision threshold", "both sources cite benchmarks"), not "rule 1"/"rule 2".

Return ONLY a JSON object:
{"resolution": "A_correct|B_correct|both_partial|insufficient_data", "confidence": "high|medium|low", "reasoning": "Specific reason citing score/evidence difference", "key_factor": "The single most decisive factor"}"""


CONTRADICTION_SCAN_SYSTEM = """You are checking if two technical sources present meaningfully different perspectives about a technology comparison.

Consider ANY of these as a "difference worth flagging":
1. Different winner recommendations (Source A says pick X, Source B says pick Y)
2. Vendor bias (one source is from a vendor comparing itself to competitors)
3. Contradictory trade-off assessments (one says X is faster, another says Y is faster)
4. Different weight given to the same evidence (one prioritizes simplicity, another scalability)
5. Source A and B draw opposite conclusions from similar facts

A "difference" does NOT require factual contradiction. Different recommendations based on different priorities or use cases also count."""


# Deterministic arbitration short-circuit: ARBITRATION rule 1 — a score gap
# >= SCORE_GAP_DECIDE makes the higher-scored source correct without an LLM
# call. Only close-score pairs need semantic arbitration (evidence-type nuance).
SCORE_GAP_DECIDE = 2.5
SCORE_GAP_HIGH_CONF = 5.0

# A conflict is a disagreement between claims, not between article titles. A
# source can only supply a comparable claim when a body was actually collected;
# repository metadata and official navigation links identify a source but state
# no claim. The excerpt is taken from the stored body, never reconstructed from
# the title.
_CLAIM_EXCERPT_LIMIT = 400


def comparable_claim(source: dict, limit: int = _CLAIM_EXCERPT_LIMIT) -> str:
    """The bounded body excerpt that a conflict scan/arbitration may compare.

    Returns "" when the source has no collected body (navigation, repository
    metadata). Callers must not fall back to the title: a title is source identity,
    not an assertion to arbitrate.
    """
    if not has_factual_content(source):
        return ""
    text = " ".join(str(source_content(source)).split())
    if not text:
        return ""
    return text[:limit].rstrip()


def _deterministic_arbitration(a: dict, b: dict) -> dict | None:
    """Apply arbitration rule 1 without an LLM call. Returns the resolved
    verdict when the score gap is decisive, or None when the gap is too small
    to decide by score alone (semantic arbitration is then required)."""
    score_a = float(a.get("total_score", 0))
    score_b = float(b.get("total_score", 0))
    diff = abs(score_a - score_b)
    if diff < SCORE_GAP_DECIDE:
        return None
    winner = "A" if score_a > score_b else "B"
    confidence = "high" if diff >= SCORE_GAP_HIGH_CONF else "medium"
    return {
        "resolution": f"{winner}_correct",
        "confidence": confidence,
        "reasoning": (f"Score gap {diff:.1f} >= {SCORE_GAP_DECIDE} favors source "
                      f"{winner} ({max(score_a, score_b):.1f} vs {min(score_a, score_b):.1f})"),
        "key_factor": "score_difference",
    }


# ---------------------------------------------------------------------------
# Inline multi-turn evidence gathering — 3 search tools (web / scholarly / kb)
# ---------------------------------------------------------------------------

SEARCH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web for latest tech comparisons, benchmarks, community discussions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "description": "Max results (1-5)", "default": 3},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_scholarly",
            "description": "Search academic papers on arXiv for research findings and benchmarks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Academic search query"},
                    "max_results": {"type": "integer", "description": "Max results (1-5)", "default": 3},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_kb",
            "description": "Search local knowledge base for previously researched tech comparison data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Knowledge base query"},
                    "max_results": {"type": "integer", "description": "Max results (1-5)", "default": 3},
                },
                "required": ["query"],
            },
        },
    },
]


async def _execute_search(tool_name: str, arguments: dict) -> str:
    """Execute a single search tool and return JSON-serialized results."""
    query = arguments.get("query", "")
    max_results = min(arguments.get("max_results", 3), 5)

    if tool_name == "search_web":
        async with httpx.AsyncClient(timeout=15.0) as client:

            async def post(url, json=None, **kw):
                return await client.post(url, json=json, **kw)

            try:
                resp, _ = await post_with_failover(post, {
                    "query": query,
                    "search_depth": "basic",
                    "max_results": max_results,
                })
                if resp is None:
                    return json.dumps({"error": "no Tavily API key available"})
                resp.raise_for_status()
                data = resp.json()
                results = data.get("results", [])[:max_results]
                return json.dumps([{"title": r.get("title", ""),
                                    "content": r.get("content", "")[:300],
                                    "url": r.get("url", "")} for r in results],
                                  ensure_ascii=False)
            except Exception as e:
                return json.dumps({"error": str(e)})

    elif tool_name == "search_scholarly":
        import urllib.parse
        try:
            async with await _outbound.make_client("arxiv") as client:
                q = urllib.parse.quote(f"all:{query}", safe="")
                url = f"https://export.arxiv.org/api/query?search_query={q}&max_results={max_results}"
                resp = await client.get(url)
                resp.raise_for_status()
                import xml.etree.ElementTree as ET
                root = ET.fromstring(resp.text)
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                results = []
                for entry in root.findall("atom:entry", ns):
                    title = entry.find("atom:title", ns)
                    summary = entry.find("atom:summary", ns)
                    link = entry.find("atom:id", ns)
                    results.append({
                        "title": title.text.strip() if title is not None else "",
                        "summary": summary.text.strip()[:300] if summary is not None else "",
                        "url": link.text.strip() if link is not None else "",
                    })
                return json.dumps(results[:max_results], ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    elif tool_name == "search_kb":
        chroma_path = os.environ.get("CHROMA_PATH", "./chroma_kb/chroma_db")
        try:
            import chromadb
            from chromadb.errors import NotFoundError
            client = chromadb.PersistentClient(
                path=chroma_path,
                settings=chromadb.Settings(anonymized_telemetry=False),
            )
            try:
                collection = client.get_collection("knowledge_base")
            except NotFoundError:
                return json.dumps({"error": "KB collection not found", "results": []})
            results = collection.query(query_texts=[query], n_results=max_results)
            docs = []
            for i, doc in enumerate(results.get("documents", [[]])[0]):
                meta = results.get("metadatas", [[]])[0][i] if results.get("metadatas") else {}
                docs.append({"content": doc[:300] if doc else "", "metadata": meta})
            return json.dumps(docs, ensure_ascii=False)
        except ImportError:
            return json.dumps({"error": "chromadb not installed in this process"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    return json.dumps({"error": f"Unknown tool: {tool_name}"})


async def _gather_evidence(topic: str, claim_a: str, claim_b: str,
                           max_iterations: int = 2,
                           per_call_timeout: float = 30.0,
                           usage: list | None = None) -> str:
    """Inline multi-turn evidence gathering via OpenAI-compatible tool calling.

    Returns a plain-text summary of collected evidence suitable for
    enriching claim descriptions in the arbitration prompt.
    """
    from ..utils.llm import TIERS, _get_client

    client = _get_client(timeout=60.0, tier="deepseek-flash")

    messages = [
        {"role": "system", "content": (
            "You gather evidence to resolve technical disagreements. "
            "Search broadly across sources, then summarize the key finding "
            "in 2-3 sentences that would help an arbitrator decide which claim is more credible."
        )},
        {"role": "user", "content": (
            f"Topic: {topic}\n"
            f"Claim A: {claim_a}\n"
            f"Claim B: {claim_b}\n\n"
            f"Search for evidence using at least 1 different tool."
        )},
    ]

    summaries = []

    for _ in range(max_iterations):
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=TIERS["deepseek-flash"]["model"],
                    messages=messages,
                    tools=SEARCH_TOOLS,
                    temperature=0,
                ),
                timeout=per_call_timeout,
            )
        except TimeoutError:
            print_agent_output("Evidence gathering LLM call timed out", agent="CONFLICT_DETECTOR")
            break
        except Exception as e:
            print_agent_output(f"Evidence gathering LLM error: {e}", agent="CONFLICT_DETECTOR")
            break

        # Capture token usage (same 4-field shape as call_model) so the
        # panel does not undercount direct-AsyncOpenAI evidence-gathering calls.
        if usage is not None and getattr(response, "usage", None) is not None:
            usage.append({
                "model": getattr(response, "model", None) or TIERS["deepseek-flash"]["model"],
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            })

        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            if msg.content:
                summaries.append(msg.content)
            break

        tool_calls = [tc for tc in msg.tool_calls if tc.type == "function"]

        async def _run_tool(tc):
            try:
                arguments = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                arguments = {}
            try:
                result = await asyncio.wait_for(
                    _execute_search(tc.function.name, arguments),
                    timeout=20.0,
                )
            except TimeoutError:
                result = json.dumps({"error": f"{tc.function.name} timed out"})
            except Exception as e:
                result = json.dumps({"error": str(e)})
            return tc.id, result

        tool_results = await asyncio.gather(*[_run_tool(tc) for tc in tool_calls])
        for tool_call_id, result in tool_results:
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": result,
            })

    return "\n".join(summaries) if summaries else ""


# ---------------------------------------------------------------------------
# Candidate scanning (LLM replaces negation-word matching)
# ---------------------------------------------------------------------------


async def _scan_pair_contradiction(src_a: dict, src_b: dict, query: str,
                                   usage: list | None = None) -> dict | None:
    """Ask flash model whether two sources present meaningfully different perspectives.

    The comparison uses the stored body excerpts, not the titles: two article
    titles can point at the same topic without asserting anything comparable.
    Titles are kept only as the source identity in the prompt.
    """
    claim_a = comparable_claim(src_a)
    claim_b = comparable_claim(src_b)
    if not claim_a or not claim_b:
        return None
    prompt = [
        {"role": "system", "content": CONTRADICTION_SCAN_SYSTEM},
        {"role": "user", "content": (
            f"Query: {query}\n\n"
            f"Source A: {src_a.get('title', '')}\nExcerpt: {claim_a}\n\n"
            f"Source B: {src_b.get('title', '')}\nExcerpt: {claim_b}\n\n"
            f"Do these two sources present meaningfully different perspectives? Return JSON."
            """

Return ONLY a JSON object:
{{
  "has_difference": true/false,
  "type": "winner_disagreement|tradeoff_disagreement|vendor_bias|none",
  "explanation": "One sentence explaining the difference (or why there is none)"
}}"""
        )},
    ]
    try:
        async with FLASH_SEM:
            result = await call_model(
                prompt,
                model="deepseek-flash", tag="conflict_scan",
                response_format="json",
                usage=usage,
            )
    except Exception as e:
        print_agent_output(f"Conflict scan failed: {e}", agent="CONFLICT_DETECTOR")
        # No answer at all. The caller records this as unscanned instead of
        # treating it as evidence that no conflict exists.
        raise

    # A judgement exists only when the reply states `has_difference` as a real
    # boolean. call_model returns {} for unparsable output, and the model can
    # return "" or "false" for the field, so anything else carries no
    # judgement and must not be read as "no difference".
    verdict = result.get("has_difference") if isinstance(result, dict) else None
    if isinstance(verdict, bool):
        if verdict:
            return result
        # The model answered and found no disagreement. That is a completed scan
        # with a negative result, not a failure.
        return {"has_difference": False, "type": "none"}
    print_agent_output(
        f"Conflict scan returned no usable judgement: {result!r}"[:200],
        agent="CONFLICT_DETECTOR",
    )
    return None


# Coverage of the conflict check for the current run. A completed scan that found
# no difference and a scan that never completed are different facts, and a bare
# conflict list cannot express the difference. This is a plain counter dict, not
# a state framework.
conflict_detector_coverage: dict = {}


def _record_coverage(**fields) -> dict:
    """Replace the coverage record. Never merged, so a stale run cannot leak."""
    conflict_detector_coverage.clear()
    conflict_detector_coverage.update(fields)
    return dict(conflict_detector_coverage)


# Per-stage elapsed seconds for this node, so a slow run can be read as scan vs
# arbitration vs evidence vs re-arbitration instead of one opaque node duration.
# Plain dict of floats; not a tracing system.
conflict_stage_timing: dict = {}


def _stage(name: str, started: float) -> None:
    conflict_stage_timing[name] = round(
        conflict_stage_timing.get(name, 0.0) + (time.monotonic() - started), 2)


# Outcomes the scan can report. Anything else is not a completed judgement.
SCAN_DIFFERENCE = "difference"
SCAN_NO_DIFFERENCE = "no_difference"
SCAN_UNSCANNED = "unscanned"


def conflict_check_incomplete() -> bool:
    """Whether any confirmed difference was left without a resolution.

    Two ways the check can be unfinished, and both read as incomplete:

      * the scan never classified a candidate pair, so a difference could not be
        found; and
      * the scan DID find a difference but its arbitration produced no row, so a
        real disagreement was confirmed and then left unresolved.

    The second case must not read as "check complete, no conflicts": the
    disagreement exists and simply was not adjudicated.
    """
    outcomes = getattr(find_contradictions, "last_outcomes", None) or {}
    if outcomes.get(SCAN_UNSCANNED):
        return True
    # A check that never reached a candidate pair (too few sources, too few
    # comparable claims, or no similar pair) cannot be reported as a completed
    # "no conflict" result either.
    early_reason = conflict_detector_coverage.get("reason")
    if early_reason in ("too_few_comparable_sources", "too_few_high_score_sources",
                        "no_candidate_pairs"):
        return True
    return bool(conflict_detector_coverage.get("pairs_arbitration_failed"))


async def find_contradictions(source_scores: list[dict], query_topic: str = "",
                               threshold: float = 0.65,
                               usage: list | None = None) -> list[dict]:
    """Find contradictory source pairs using LLM semantic scan.

    Pipeline: BGE similarity pre-filter → LLM contradiction scan
    (replaces old negation-word matching).
    """
    # Reset the outcome record for this call so a later reader can never see a
    # previous call's counts and read an incomplete scan as a clean one.
    find_contradictions.last_outcomes = {
        "difference": 0, "no_difference": 0, "unscanned": 0}
    find_contradictions.last_rejected = {}
    find_contradictions.last_insufficient_claim = 0
    # A completed scan with no differences records no coverage of its own; clear
    # the previous run's diagnostic so a later node cannot read a stale reason.
    conflict_detector_coverage.clear()
    model = get_embedding_model()
    high_score_sources = [s for s in source_scores if s["total_score"] >= 5.0]
    # Only sources that actually carry a body can supply a comparable claim.
    # A navigation link or repository-metadata row identifies a source but
    # asserts nothing, and arbitrating on its title would manufacture a
    # disagreement between article names. Keep the count visible instead of
    # silently dropping the ineligible sources.
    eligible_sources = [s for s in high_score_sources if comparable_claim(s)]
    find_contradictions.last_insufficient_claim = (
        len(high_score_sources) - len(eligible_sources))
    high_score_sources = eligible_sources
    if len(high_score_sources) < 2:
        _record_coverage(
            pairs_scanned=0,
            pairs_arbitrated=0,
            pairs_evidence=0,
            scan_outcomes={"difference": 0, "no_difference": 0, "unscanned": 0},
            sources_without_comparable_claim=find_contradictions.last_insufficient_claim,
            reason="too_few_comparable_sources",
        )
        return []

    titles = [s.get("title", "") for s in high_score_sources]
    embeddings = await asyncio.to_thread(model.encode, titles)
    norms = np.linalg.norm(embeddings, axis=1)

    # Candidate pairs (BGE similarity — LLM handles semantic filtering). The
    # bound is deliberate and unchanged: at most 15 pairs are scanned, ranked by
    # similarity, so the scan cost stays proportional to the source count rather
    # than growing with every possible pair.
    candidates: list[tuple[int, int, float]] = []
    rejected = {"missing_title": 0}
    for i in range(len(high_score_sources)):
        for j in range(i + 1, len(high_score_sources)):
            if not titles[i] or not titles[j]:
                rejected["missing_title"] += 1
                continue
            sim = float(np.dot(embeddings[i], embeddings[j]) / (norms[i] * norms[j]))
            if sim < threshold:
                continue
            candidates.append((i, j, sim))

    if not candidates:
        print_agent_output(
            f"No candidate pairs above the similarity threshold "
            f"(missing_title={rejected['missing_title']})",
            agent="CONFLICT_DETECTOR",
        )
        _record_coverage(
            pairs_scanned=0,
            pairs_arbitrated=0,
            pairs_evidence=0,
            scan_outcomes={"difference": 0, "no_difference": 0, "unscanned": 0},
            sources_without_comparable_claim=find_contradictions.last_insufficient_claim,
            reason="no_candidate_pairs",
        )
        return []

    candidates.sort(key=lambda x: x[2], reverse=True)
    candidates = candidates[:15]

    # LLM scan in parallel. A pair the scan could not classify is reported as
    # unscanned rather than being folded into "no difference": an empty conflict
    # list must not silently mean "we did not finish looking".
    outcomes = {"difference": 0, "no_difference": 0, "unscanned": 0}

    async def _scan(cand):
        i, j, sim = cand
        try:
            info = await _scan_pair_contradiction(
                high_score_sources[i], high_score_sources[j], query_topic,
                usage=usage,
            )
        except Exception as exc:
            print_agent_output(
                f"Conflict scan error for pair ({i},{j}): {exc}",
                agent="CONFLICT_DETECTOR",
            )
            return (i, j, sim, None, "unscanned")
        if info is None:
            return (i, j, sim, None, "unscanned")
        if not info.get("has_difference"):
            return (i, j, sim, None, "no_difference")
        return (i, j, sim, info, "difference")

    print_agent_output(
        f"LLM scanning {len(candidates)} candidate pairs for contradictions",
        agent="CONFLICT_DETECTOR",
    )
    _scan_started = time.monotonic()
    scan_results = await asyncio.gather(*[_scan(c) for c in candidates])
    _stage("scan_s", _scan_started)

    pairs = []
    for r in scan_results:
        i, j, sim, info, outcome = r
        outcomes[outcome] += 1
        if outcome != "difference":
            continue
        pairs.append({
            "source_a": high_score_sources[i],
            "source_b": high_score_sources[j],
            "similarity": round(sim, 3),
            "difference_type": info.get("type", "unknown"),
            "difference_explanation": info.get("explanation", ""),
        })

    if outcomes["unscanned"]:
        # Visible incompleteness: these pairs were never classified, so the
        # conflict list is partial. Reported rather than passed off as clean.
        print_agent_output(
            f"WARNING: {outcomes['unscanned']} pair(s) were not scanned; "
            f"the conflict list is incomplete",
            agent="CONFLICT_DETECTOR",
        )
    print_agent_output(
        f"Scan outcomes: differences={outcomes['difference']} "
        f"no_difference={outcomes['no_difference']} "
        f"unscanned={outcomes['unscanned']}",
        agent="CONFLICT_DETECTOR",
    )
    find_contradictions.last_outcomes = dict(outcomes)
    find_contradictions.last_rejected = dict(rejected)

    return pairs


find_contradictions.last_outcomes = {}
find_contradictions.last_rejected = {}
find_contradictions.last_insufficient_claim = 0


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class ConflictDetectorAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None,
                 gather_evidence: bool = True):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers
        self.gather_evidence = gather_evidence

    async def run(self, research_state: dict) -> dict:
        source_scores = research_state.get("source_scores", [])
        query = research_state["task"]["query"]
        print_agent_output(
            f"Detecting conflicts among {len(source_scores)} sources",
            agent="CONFLICT_DETECTOR",
        )

        local_usage: list = []
        pairs = await find_contradictions(source_scores, query_topic=query, usage=local_usage)
        if not pairs:
            outcomes = dict(getattr(find_contradictions, "last_outcomes", {}))
            # Keep the diagnostic recorded by an early return (too few sources /
            # too few comparable claims / no candidate pairs); a completed scan
            # with no differences has no earlier reason.
            diagnostic_reason = (
                dict(conflict_detector_coverage).get("reason") or "no_pairs_confirmed")
            check = _record_coverage(
                # The scan did run; the count comes from what it classified.
                # Reporting 0 here would say no pair was ever examined.
                pairs_scanned=(int(outcomes.get(SCAN_DIFFERENCE, 0))
                               + int(outcomes.get(SCAN_NO_DIFFERENCE, 0))
                               + int(outcomes.get(SCAN_UNSCANNED, 0))),
                pairs_arbitrated=0,
                pairs_evidence=0,
                scan_outcomes=outcomes,
                sources_without_comparable_claim=(
                    getattr(find_contradictions, "last_insufficient_claim", 0)),
                reason=diagnostic_reason,
            )
            incomplete = conflict_check_incomplete()
            print_agent_output(
                f"No confirmed contradictory pairs "
                f"(scan {outcomes}, incomplete={incomplete})",
                agent="CONFLICT_DETECTOR",
            )
            return {
                "conflicts": [],
                "conflict_check": check,
                "quality_signals": [{
                    "agent": "conflict_detector",
                    "conflicts_found": 0,
                    "resolved_count": 0,
                    "scan_no_difference": outcomes.get(SCAN_NO_DIFFERENCE, 0),
                    "scan_unscanned": outcomes.get(SCAN_UNSCANNED, 0),
                    "conflict_check_incomplete": incomplete,
                }],
                "token_usage": research_state.get("token_usage", [])
                + [summarize_usage("conflict_detector", local_usage)],
            }

        print_agent_output(
            f"LLM scan confirmed {len(pairs)} contradictory pairs, running flash arbitration",
            agent="CONFLICT_DETECTOR",
        )

        def _make_prompt(a: dict, b: dict) -> list[dict]:
            claim_a = comparable_claim(a)
            claim_b = comparable_claim(b)
            return [
                {"role": "system", "content": ARBITRATION_SYSTEM},
                {"role": "user", "content": (
                    f"## Topic\n{query}\n\n"
                    f"## Source A\nTitle: {a.get('title', '')}\n"
                    f"Score: {a['total_score']}/10, authority: {a['scores']['authority']}, "
                    f"evidence: {a.get('evidence_type', 'citation')}\n"
                    f"Claim excerpt: {claim_a}\n\n"
                    f"## Source B\nTitle: {b.get('title', '')}\n"
                    f"Score: {b['total_score']}/10, authority: {b['scores']['authority']}, "
                    f"evidence: {b.get('evidence_type', 'citation')}\n"
                    f"Claim excerpt: {claim_b}"
                )},
            ]

        def _cited_source(src: dict) -> dict:
            """The claim's source, keeping what the renderer needs to judge it.

            The marker says whether a body was collected; the snippet is the body.
            Dropping either one made has_factual_content fall back to an empty
            string and brand an ordinary evidence source as carrying no body.
            """
            entry = {"url": src["url"], "title": src.get("title", ""),
                     "score": src["total_score"]}
            if "has_body" in src:
                entry["has_body"] = src["has_body"]
            snippet = src.get("snippet")
            if snippet:
                entry["snippet"] = snippet
            return entry

        def _build_conflict(pair: dict, result: dict, model: str = "flash") -> dict:
            return {
                # The stored claim is the comparable body excerpt, not the
                # source title. The source identity travels separately below,
                # so a report can show what was compared and where it came from.
                "claim_a": comparable_claim(pair["source_a"]),
                "claim_b": comparable_claim(pair["source_b"]),
                "source_a": _cited_source(pair["source_a"]),
                "source_b": _cited_source(pair["source_b"]),
                "similarity": pair["similarity"],
                "resolution": result.get("resolution", "insufficient_data"),
                "confidence": result.get("confidence", "low"),
                "reasoning": result.get("reasoning", ""),
                "key_factor": result.get("key_factor", ""),
                "arbiter_model": model,
                "evidence_collected": result.get("evidence_collected", ""),
                "difference_type": pair.get("difference_type", "unknown"),
                "difference_explanation": pair.get("difference_explanation", ""),
            }

        # A pair is arbitrated once on titles, and the single ambiguous pair is
        # then arbitrated once more with gathered evidence. That second call is
        # the only one whose input actually differs from the first. The removed
        # work is the pair being judged twice on identical titles.
        async def _arbitrate_one(pair: dict, evidence: str = "") -> dict:
            det = _deterministic_arbitration(pair["source_a"], pair["source_b"])
            if det is not None:
                # The deterministic rule decides from scores alone and needs no
                # evidence, so it must not pay the multi-search cost.
                return _build_conflict(pair, det, model="deepseek-flash(rule)")
            source_a = pair["source_a"]
            source_b = pair["source_b"]
            if evidence:
                note = f"\n\n[Evidence from additional search: {evidence}]"
                source_a = dict(source_a, title=f"{source_a.get('title', '')}{note}")
                source_b = dict(source_b, title=f"{source_b.get('title', '')}{note}")
            async with FLASH_SEM:
                result = await call_model(
                    _make_prompt(source_a, source_b),
                    model="deepseek-flash", tag="conflict_arbitration",
                    response_format="json",
                    usage=local_usage,
                )
            return _build_conflict(pair, result, model="deepseek-flash")

        _arb_started = time.monotonic()
        raw_conflicts = await asyncio.gather(
            *[_arbitrate_one(p) for p in pairs], return_exceptions=True,
        )
        _stage("initial_arbitration_s", _arb_started)

        conflicts = []
        # Track the pair index alongside its conflict row, so a later stage can
        # address the original pair. Using the position inside `conflicts` would
        # be off by the number of failed arbitrations, spending the single
        # evidence slot on a pair that had already failed.
        conflict_pairs = []
        low_confidence = []
        failed_arbitrations = 0
        for pair, result in zip(pairs, raw_conflicts):
            if isinstance(result, Exception):
                print_agent_output(
                    f"Arbitration failed: {result}", agent="CONFLICT_DETECTOR")
                failed_arbitrations += 1
                continue
            conflicts.append(result)
            conflict_pairs.append(pair)
            if result.get("confidence") == "low":
                low_confidence.append(len(conflicts) - 1)

        # Evidence gathering stays bounded exactly as before: the single most
        # ambiguous pair only.
        evidence_pairs = low_confidence[:1] if self.gather_evidence else []
        if not self.gather_evidence and low_confidence:
            print_agent_output(
                f"Evidence gathering disabled: {len(low_confidence)} ambiguous pair(s)",
                agent="CONFLICT_DETECTOR",
            )
        for index in evidence_pairs:
            pair = conflict_pairs[index]
            evidence = ""
            _ev_started = time.monotonic()
            try:
                evidence = await _gather_evidence(
                    topic=query,
                    claim_a=comparable_claim(pair["source_a"]),
                    claim_b=comparable_claim(pair["source_b"]),
                    usage=local_usage,
                )
            except Exception as e:
                print_agent_output(
                    f"Evidence gathering failed: {e}", agent="CONFLICT_DETECTOR")
            finally:
                _stage("evidence_gathering_s", _ev_started)
            if not evidence:
                continue
            _re_started = time.monotonic()
            try:
                revised = await _arbitrate_one(pair, evidence)
            except Exception as e:
                print_agent_output(
                    f"Evidence arbitration failed: {e}", agent="CONFLICT_DETECTOR")
                continue
            finally:
                _stage("re_arbitration_s", _re_started)
            revised["evidence_collected"] = evidence[:500]
            conflicts[index] = revised

        coverage = {
            "pairs_scanned": len(pairs),
            "pairs_arbitrated": len(conflicts),
            "pairs_evidence": len(evidence_pairs),
            # A scan-confirmed pair whose arbitration failed produced no conflict
            # row. Recorded so the loss is visible instead of looking like the
            # scan never found anything.
            "pairs_arbitration_failed": failed_arbitrations,
            "scan_outcomes": dict(getattr(find_contradictions, "last_outcomes", {})),
            # Sources that could not supply a comparable claim (navigation or
            # repository metadata). They are not silently treated as agreeing.
            "sources_without_comparable_claim": (
                getattr(find_contradictions, "last_insufficient_claim", 0)),
            # Where this node's time went, so a slow run reads as scan vs
            # arbitration vs evidence vs re-arbitration.
            "stage_timing_s": dict(conflict_stage_timing),
        }
        conflict_detector_coverage.clear()
        conflict_detector_coverage.update(coverage)

        return {
            "conflicts": conflicts,
            "conflict_check": dict(conflict_detector_coverage),
            "quality_signals": [{
                "agent": "conflict_detector",
                "conflicts_found": len(conflicts),
                "resolved_count": sum(
                    1 for c in conflicts
                    if c.get("resolution") not in ("insufficient_data", None)
                ),
                "unresolved_count": sum(
                    1 for c in conflicts
                    if c.get("resolution") in ("insufficient_data", None)
                ),
                # Pairs the scan could not classify, so partial coverage stays
                # visible instead of looking like a clean empty result.
                "scan_unscanned": coverage["scan_outcomes"].get(SCAN_UNSCANNED, 0),
                "scan_no_difference": coverage["scan_outcomes"].get(SCAN_NO_DIFFERENCE, 0),
                "sources_without_comparable_claim": coverage.get(
                    "sources_without_comparable_claim", 0),
                "conflict_check_incomplete": conflict_check_incomplete(),
                "pairs_arbitrated": len(conflicts),
            }],
            "token_usage": research_state.get("token_usage", [])
            + [summarize_usage("conflict_detector", local_usage)],
        }

