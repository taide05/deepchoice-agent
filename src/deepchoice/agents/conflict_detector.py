import asyncio
import json
import os

import numpy as np
import httpx

from ..utils.llm import call_model, summarize_usage
from ..utils.views import print_agent_output
from ..utils.embedding import get_embedding_model
from ..retrievers.tavily_keypool import post_with_failover

# ---------------------------------------------------------------------------
# Concurrency limits. Provider-specific (was DeepSeek 500/min flash, 50/min pro);
# now env-tunable with conservative defaults — set LLM_FLASH_CONCURRENCY /
# LLM_PRO_CONCURRENCY to match the active provider's RPM. PRO_SEM is retained
# as the separate re-arbitration-path gate (one low-confidence pair per case).
# ---------------------------------------------------------------------------
FLASH_SEM = asyncio.Semaphore(int(os.environ.get("LLM_FLASH_CONCURRENCY", "30")))
PRO_SEM = asyncio.Semaphore(int(os.environ.get("LLM_PRO_CONCURRENCY", "10")))

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

ARBITRATION_SYSTEM = """You are an impartial technical arbitrator. Two sources make claims about the same topic but may disagree.

Rules:
1. If scores differ by >=2.5 points, the higher-scored source is more likely correct
2. If both have code/benchmark evidence, both may be partially right (different contexts)
3. If neither has strong evidence, declare "insufficient_data"
4. Your reasoning MUST cite the score difference or evidence type difference

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


# ---------------------------------------------------------------------------
# Inline multi-turn evidence gathering — 6 search tools
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
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
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

    elif tool_name == "search_code":
        token = os.environ.get("GITHUB_TOKEN", "")
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        import urllib.parse
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                q = urllib.parse.quote(query, safe="")
                url = f"https://api.github.com/search/repositories?q={q}&per_page={max_results}&sort=stars"
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                results = []
                for item in data.get("items", []):
                    results.append({
                        "repo": item.get("full_name", ""),
                        "description": item.get("description", ""),
                        "url": item.get("html_url", ""),
                        "stars": item.get("stargazers_count", 0),
                    })
                return json.dumps(results[:max_results], ensure_ascii=False)
            except Exception as e:
                return json.dumps({"error": str(e)})

    elif tool_name == "search_kb":
        chroma_path = os.environ.get("CHROMA_PATH", "./chroma_kb/chroma_db")
        try:
            import chromadb
            client = chromadb.PersistentClient(
                path=chroma_path,
                settings=chromadb.Settings(anonymized_telemetry=False),
            )
            try:
                collection = client.get_collection("knowledge_base")
            except Exception:
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

    elif tool_name == "search_community":
        import urllib.parse
        async with httpx.AsyncClient(timeout=15.0) as client:
            results = []
            try:
                q = urllib.parse.quote(query, safe="")
                so_url = (
                    f"https://api.stackexchange.com/2.3/search/advanced"
                    f"?order=desc&sort=votes&q={q}&site=stackoverflow&pagesize={max_results}"
                )
                resp = await client.get(so_url)
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("items", []):
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("link", ""),
                        "source": "stackoverflow",
                        "score": item.get("score", 0),
                    })
            except Exception:
                pass
            try:
                q = urllib.parse.quote(query, safe="")
                reddit_url = f"https://www.reddit.com/search.json?q={q}&limit={max_results}"
                headers = {"User-Agent": "DeepChoice/0.1"}
                resp = await client.get(reddit_url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                for child in data.get("data", {}).get("children", []):
                    post = child.get("data", {})
                    results.append({
                        "title": post.get("title", ""),
                        "url": f"https://reddit.com{post.get('permalink', '')}",
                        "source": "reddit",
                        "score": post.get("score", 0),
                    })
            except Exception:
                pass
            return json.dumps(results[:max_results], ensure_ascii=False)

    elif tool_name == "search_official":
        import urllib.parse
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                q = urllib.parse.quote(query, safe="")
                url = f"https://pypi.org/pypi/{q}/json"
                resp = await client.get(url)
                if resp.status_code == 404:
                    return json.dumps({"results": [], "note": f"'{query}' not found on PyPI"}, ensure_ascii=False)
                resp.raise_for_status()
                data = resp.json()
                info = data.get("info", {})
                return json.dumps([{
                    "name": info.get("name", query),
                    "summary": info.get("summary", ""),
                    "url": info.get("project_url", ""),
                    "version": info.get("version", ""),
                }], ensure_ascii=False)
            except Exception as e:
                return json.dumps({"error": str(e)})

    return json.dumps({"error": f"Unknown tool: {tool_name}"})


async def _gather_evidence(topic: str, claim_a: str, claim_b: str,
                           max_iterations: int = 1,
                           per_call_timeout: float = 30.0,
                           usage: list | None = None) -> str:
    """Inline multi-turn evidence gathering via OpenAI-compatible tool calling.

    Returns a plain-text summary of collected evidence suitable for
    enriching claim descriptions in the arbitration prompt.
    """
    import asyncio as _asyncio

    from ..utils.llm import _get_client

    client = _get_client(timeout=60.0)

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
            response = await _asyncio.wait_for(
                client.chat.completions.create(
                    model="flash",
                    messages=messages,
                    tools=SEARCH_TOOLS,
                    temperature=0,
                ),
                timeout=per_call_timeout,
            )
        except _asyncio.TimeoutError:
            print_agent_output("Evidence gathering LLM call timed out", agent="CONFLICT_DETECTOR")
            break
        except Exception as e:
            print_agent_output(f"Evidence gathering LLM error: {e}", agent="CONFLICT_DETECTOR")
            break

        # Capture token usage (same 4-field shape as call_model) so the
        # panel does not undercount direct-AsyncOpenAI evidence-gathering calls.
        if usage is not None and getattr(response, "usage", None) is not None:
            usage.append({
                "model": getattr(response, "model", None) or "flash",
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

        for tc in msg.tool_calls:
            if tc.type != "function":
                continue
            tool_name = tc.function.name
            try:
                arguments = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                arguments = {}
            try:
                result = await _asyncio.wait_for(
                    _execute_search(tool_name, arguments),
                    timeout=20.0,
                )
            except _asyncio.TimeoutError:
                result = json.dumps({"error": f"{tool_name} timed out"})
            except Exception as e:
                result = json.dumps({"error": str(e)})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    return "\n".join(summaries) if summaries else ""


# ---------------------------------------------------------------------------
# Candidate scanning (LLM replaces negation-word matching)
# ---------------------------------------------------------------------------


async def _scan_pair_contradiction(src_a: dict, src_b: dict, query: str,
                                   usage: list | None = None) -> dict | None:
    """Ask flash model whether two sources present meaningfully different perspectives.

    Returns a dict with contradiction info if detected, None otherwise.
    """
    snippet_a = src_a.get("snippet", "")[:400]
    snippet_b = src_b.get("snippet", "")[:400]
    prompt = [
        {"role": "system", "content": CONTRADICTION_SCAN_SYSTEM},
        {"role": "user", "content": (
            f"Query: {query}\n\n"
            f"Source A: {src_a.get('title', '')}\nDescription: {snippet_a if snippet_a else '(no description)'}\n\n"
            f"Source B: {src_b.get('title', '')}\nDescription: {snippet_b if snippet_b else '(no description)'}\n\n"
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
                model="flash",
                response_format="json",
                usage=usage,
            )
        if isinstance(result, dict) and result.get("has_difference"):
            return result
        return None
    except Exception:
        return None


async def find_contradictions(source_scores: list[dict], query_topic: str = "",
                               threshold: float = 0.6,
                               usage: list | None = None) -> list[dict]:
    """Find contradictory source pairs using LLM semantic scan.

    Pipeline: BGE similarity pre-filter → LLM contradiction scan
    (replaces old negation-word matching).
    """
    model = get_embedding_model()
    high_score_sources = [s for s in source_scores if s["total_score"] >= 5.0]
    if len(high_score_sources) < 2:
        return []

    titles = [s.get("title", "") for s in high_score_sources]
    embeddings = await asyncio.to_thread(model.encode, titles)
    norms = np.linalg.norm(embeddings, axis=1)

    # Build candidate pairs (BGE similarity — LLM handles semantic filtering)
    candidates: list[tuple[int, int, float]] = []
    for i in range(len(high_score_sources)):
        for j in range(i + 1, len(high_score_sources)):
            if not titles[i] or not titles[j]:
                continue
            sim = float(np.dot(embeddings[i], embeddings[j]) / (norms[i] * norms[j]))
            if sim < threshold:
                continue
            candidates.append((i, j, sim))

    if not candidates:
        return []

    # Cap at top-15 by similarity to prevent O(n²) explosion with many sources
    candidates.sort(key=lambda x: x[2], reverse=True)
    candidates = candidates[:15]

    # LLM scan in parallel
    async def _scan(cand):
        i, j, sim = cand
        info = await _scan_pair_contradiction(
            high_score_sources[i], high_score_sources[j], query_topic,
            usage=usage,
        )
        return (i, j, sim, info) if info else None

    print_agent_output(
        f"LLM scanning {len(candidates)} candidate pairs for contradictions",
        agent="CONFLICT_DETECTOR",
    )
    scan_results = await asyncio.gather(*[_scan(c) for c in candidates])

    pairs = []
    for r in scan_results:
        if r is not None:
            i, j, sim, info = r
            pairs.append({
                "source_a": high_score_sources[i],
                "source_b": high_score_sources[j],
                "similarity": round(sim, 3),
                "difference_type": info.get("type", "unknown"),
                "difference_explanation": info.get("explanation", ""),
            })

    return pairs


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
            print_agent_output("No contradictory pairs found after LLM scan", agent="CONFLICT_DETECTOR")
            return {
                "conflicts": [],
                "quality_signals": [{"agent": "conflict_detector", "conflicts_found": 0, "resolved_count": 0}],
                "token_usage": research_state.get("token_usage", [])
                + [summarize_usage("conflict_detector", local_usage)],
            }

        print_agent_output(
            f"LLM scan confirmed {len(pairs)} contradictory pairs, running flash arbitration",
            agent="CONFLICT_DETECTOR",
        )

        def _make_prompt(a: dict, b: dict) -> list[dict]:
            return [
                {"role": "system", "content": ARBITRATION_SYSTEM},
                {"role": "user", "content": (
                    f"## Topic\n{query}\n\n"
                    f"## Source A (score: {a['total_score']}/10, authority: {a['scores']['authority']}, evidence: {a.get('evidence_type', 'citation')})\nClaim: {a.get('title', '')}\n\n"
                    f"## Source B (score: {b['total_score']}/10, authority: {b['scores']['authority']}, evidence: {b.get('evidence_type', 'citation')})\nClaim: {b.get('title', '')}"
                )},
            ]

        def _build_conflict(pair: dict, result: dict, model: str = "flash") -> dict:
            return {
                "claim_a": pair["source_a"].get("title", ""),
                "claim_b": pair["source_b"].get("title", ""),
                "source_a": {"url": pair["source_a"]["url"], "score": pair["source_a"]["total_score"]},
                "source_b": {"url": pair["source_b"]["url"], "score": pair["source_b"]["total_score"]},
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

        # --- Stage 1: Flash arbitration (parallel) ---
        async def _arbitrate_one(pair: dict) -> dict:
            async with FLASH_SEM:
                result = await call_model(
                    _make_prompt(pair["source_a"], pair["source_b"]),
                    model="flash",
                    response_format="json",
                    usage=local_usage,
                )
            return _build_conflict(pair, result, model="flash")

        raw_conflicts = await asyncio.gather(
            *[_arbitrate_one(p) for p in pairs], return_exceptions=True,
        )

        conflicts = []
        low_confidence_pairs = []
        for pair, result in zip(pairs, raw_conflicts):
            if isinstance(result, Exception):
                print_agent_output(f"Flash arbitration failed: {result}", agent="CONFLICT_DETECTOR")
                continue
            conflicts.append(result)
            if result["confidence"] == "low":
                low_confidence_pairs.append(pair)

        # Cap evidence gathering at top-2 most ambiguous pairs (sorted by confidence gap)
        low_confidence_pairs = low_confidence_pairs[:1]

        # --- Stage 2: Evidence gathering + pro re-arbitration (parallel) ---
        if low_confidence_pairs and self.gather_evidence:
            print_agent_output(
                f"Evidence-gathering re-arbitration: {len(low_confidence_pairs)} pair(s)",
                agent="CONFLICT_DETECTOR",
            )
            sem = asyncio.Semaphore(3)  # Evidence gathering is heavy (multi-API per pair)

            async def _re_arbitrate(idx: int, pair: dict) -> int | None:
                async with sem:
                    a = pair["source_a"]
                    b = pair["source_b"]
                    evidence = ""
                    try:
                        evidence = await _gather_evidence(
                            topic=query,
                            claim_a=a.get("title", ""),
                            claim_b=b.get("title", ""),
                            usage=local_usage,
                        )
                    except Exception as e:
                        print_agent_output(f"Evidence gathering failed: {e}", agent="CONFLICT_DETECTOR")

                    enriched_claim_a = a.get("title", "")
                    enriched_claim_b = b.get("title", "")
                    if evidence:
                        enriched_claim_a = (
                            f"{a.get('title', '')}\n\n"
                            f"[Evidence from additional search: {evidence}]"
                        )
                        enriched_claim_b = (
                            f"{b.get('title', '')}\n\n"
                            f"[Evidence from additional search: {evidence}]"
                        )

                    enriched_a = dict(a, title=enriched_claim_a)
                    enriched_b = dict(b, title=enriched_claim_b)

                    try:
                        async with PRO_SEM:
                            pro_result = await call_model(
                                _make_prompt(enriched_a, enriched_b),
                                model="flash",
                                response_format="json",
                                timeout=300.0,
                                usage=local_usage,
                            )
                    except Exception as e:
                        print_agent_output(f"Pro re-arbitration failed: {e}", agent="CONFLICT_DETECTOR")
                        return None

                    pro_conflict = _build_conflict(pair, pro_result, model="pro+evidence")
                    pro_conflict["evidence_collected"] = evidence[:500] if evidence else ""
                    return idx, pro_conflict

            re_results = await asyncio.gather(
                *[_re_arbitrate(i, p) for i, p in enumerate(low_confidence_pairs)],
                return_exceptions=True,
            )
            for r in re_results:
                if isinstance(r, Exception):
                    continue
                if r is not None:
                    idx, pro_conflict = r
                    if idx < len(conflicts):
                        conflicts[idx] = pro_conflict
        elif low_confidence_pairs:
            print_agent_output(
                f"Skipping evidence gathering (disabled): {len(low_confidence_pairs)} pair(s)",
                agent="CONFLICT_DETECTOR",
            )

        resolved_count = sum(
            1 for c in conflicts
            if c.get("resolution") not in ("insufficient_data", None)
        )
        return {
            "conflicts": conflicts,
            "quality_signals": [{
                "agent": "conflict_detector",
                "conflicts_found": len(conflicts),
                "resolved_count": resolved_count,
                "unresolved_count": len(conflicts) - resolved_count,
            }],
            "token_usage": research_state.get("token_usage", [])
            + [summarize_usage("conflict_detector", local_usage)],
        }
