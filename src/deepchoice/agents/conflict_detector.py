import json
import os

import numpy as np
import httpx

from ..utils.llm import call_model
from ..utils.views import print_agent_output
from ..utils.embedding import get_embedding_model


ARBITRATION_PROMPT = """You are an impartial technical arbitrator. Two sources make claims about the same topic but may disagree.

## Topic
{topic}

## Source A (score: {score_a}/10, authority: {authority_a}, evidence: {evidence_a})
Claim: {claim_a}

## Source B (score: {score_b}/10, authority: {authority_b}, evidence: {evidence_b})
Claim: {claim_b}

## Rules
1. If scores differ by >=2.5 points, the higher-scored source is more likely correct
2. If both have code/benchmark evidence, both may be partially right (different contexts)
3. If neither has strong evidence, declare "insufficient_data"
4. Your reasoning MUST cite the score difference or evidence type difference

Return ONLY a JSON object:
{{
  "resolution": "A_correct|B_correct|both_partial|insufficient_data",
  "confidence": "high|medium|low",
  "reasoning": "Specific reason citing score/evidence difference",
  "key_factor": "The single most decisive factor"
}}"""

NEGATION_WORDS = {
    "not", "no", "never", "fail", "worse", "slow", "bad", "broken", "cannot",
    "doesn't", "don't", "isn't", "won't", "without", "lack", "lacks", "missing",
    "better than", "outperforms", "superior", "inferior", "however",
    "but", "although", "unlike", "versus", "vs", "contrary", "disagree",
    "instead", "rather than", "prefer", "drawback", "downside",
}

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
            "name": "search_code",
            "description": "Search GitHub repos for implementation examples, benchmark code, issues.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Code/tech search query"},
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
    {
        "type": "function",
        "function": {
            "name": "search_community",
            "description": "Search StackOverflow and Reddit for real-world developer experiences and opinions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Community search query"},
                    "max_results": {"type": "integer", "description": "Max results (1-5)", "default": 3},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_official",
            "description": "Search official documentation and package registries (PyPI, npm).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Package/tech name for official docs search"},
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
        api_key = os.environ.get("TAVILY_API_KEY", "")
        if not api_key:
            return json.dumps({"error": "TAVILY_API_KEY not set"})
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={"api_key": api_key, "query": query,
                          "search_depth": "basic", "max_results": max_results},
                )
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
        chroma_path = os.environ.get("CHROMA_PATH", "./chroma_db")
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
                           max_iterations: int = 3) -> str:
    """Inline multi-turn evidence gathering via DeepSeek native tool calling.

    Returns a plain-text summary of collected evidence suitable for
    enriching claim descriptions in the arbitration prompt.
    """
    from openai import AsyncOpenAI

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=120.0)

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
            f"Search for evidence using at least 2 different tools."
        )},
    ]

    summaries = []

    for _ in range(max_iterations):
        try:
            response = await client.chat.completions.create(
                model="deepseek-v4-flash",
                messages=messages,
                tools=SEARCH_TOOLS,
                temperature=0,
            )
        except Exception as e:
            print_agent_output(f"Evidence gathering LLM error: {e}", agent="CONFLICT_DETECTOR")
            break

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
            result = await _execute_search(tool_name, arguments)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    return "\n".join(summaries) if summaries else ""


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


def find_contradictions(source_scores: list[dict], threshold: float = 0.6) -> list[dict]:
    model = get_embedding_model()
    high_score_sources = [s for s in source_scores if s["total_score"] >= 5.0]
    if len(high_score_sources) < 2:
        return []

    titles = [s.get("title", "") for s in high_score_sources]
    embeddings = model.encode(titles)
    norms = np.linalg.norm(embeddings, axis=1)

    pairs = []
    for i in range(len(high_score_sources)):
        for j in range(i + 1, len(high_score_sources)):
            title_a = titles[i]
            title_b = titles[j]
            if not title_a or not title_b:
                continue

            sim = float(np.dot(embeddings[i], embeddings[j]) / (norms[i] * norms[j]))

            if sim >= threshold:
                neg_a = any(w in title_a.lower() for w in NEGATION_WORDS)
                neg_b = any(w in title_b.lower() for w in NEGATION_WORDS)
                if neg_a != neg_b:
                    pairs.append({
                        "source_a": high_score_sources[i],
                        "source_b": high_score_sources[j],
                        "similarity": round(sim, 3),
                    })

    return pairs


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class ConflictDetectorAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        source_scores = research_state.get("source_scores", [])
        print_agent_output(
            f"Detecting conflicts among {len(source_scores)} sources",
            agent="CONFLICT_DETECTOR",
        )

        pairs = find_contradictions(source_scores)
        if not pairs:
            return {
                "conflicts": [],
                "quality_signals": [{"agent": "conflict_detector", "conflicts_found": 0, "resolved_count": 0}],
            }

        def _make_prompt(a: dict, b: dict) -> list[dict]:
            claim_a = a.get("title", "")
            claim_b = b.get("title", "")
            return [{
                "role": "user",
                "content": ARBITRATION_PROMPT.format(
                    topic=research_state["task"]["query"],
                    score_a=a["total_score"],
                    authority_a=a["scores"]["authority"],
                    evidence_a=a.get("evidence_type", "citation"),
                    claim_a=claim_a,
                    score_b=b["total_score"],
                    authority_b=b["scores"]["authority"],
                    evidence_b=b.get("evidence_type", "citation"),
                    claim_b=claim_b,
                ),
            }]

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
            }

        # Stage 1: Flash arbitration for all pairs
        conflicts = []
        low_confidence_pairs: list[dict] = []

        for pair in pairs:
            try:
                result = await call_model(
                    _make_prompt(pair["source_a"], pair["source_b"]),
                    model="deepseek-v4-flash",
                    response_format="json",
                )
                conflict = _build_conflict(pair, result, model="flash")
                conflicts.append(conflict)
                if conflict["confidence"] == "low":
                    low_confidence_pairs.append(pair)
            except Exception as e:
                print_agent_output(f"Flash arbitration failed: {e}", agent="CONFLICT_DETECTOR")

        # Stage 2: Gather evidence from all 6 sources + pro re-arbitration
        if low_confidence_pairs:
            print_agent_output(
                f"Evidence-gathering re-arbitration: {len(low_confidence_pairs)} pair(s)",
                agent="CONFLICT_DETECTOR",
            )
            for pair in low_confidence_pairs:
                a = pair["source_a"]
                b = pair["source_b"]
                score_gap = abs(a["total_score"] - b["total_score"])
                print_agent_output(
                    f"  Gathering evidence for: \"{a.get('title', '')[:60]}\" vs "
                    f"\"{b.get('title', '')[:60]}\" (gap={score_gap:.1f})",
                    agent="CONFLICT_DETECTOR",
                )
                evidence = ""
                try:
                    evidence = await _gather_evidence(
                        topic=research_state["task"]["query"],
                        claim_a=a.get("title", ""),
                        claim_b=b.get("title", ""),
                        max_iterations=3,
                    )
                except Exception as e:
                    print_agent_output(f"Evidence gathering failed: {e}", agent="CONFLICT_DETECTOR")

                enriched_claim_a = a.get("title", "")
                enriched_claim_b = b.get("title", "")
                if evidence:
                    enriched_claim_a = f"{a.get('title', '')}\n\n[Evidence from additional search: {evidence}]"
                    enriched_claim_b = f"{b.get('title', '')}\n\n[Evidence from additional search: {evidence}]"

                enriched_a = dict(a, title=enriched_claim_a)
                enriched_b = dict(b, title=enriched_claim_b)

                try:
                    pro_result = await call_model(
                        _make_prompt(enriched_a, enriched_b),
                        model="deepseek-v4-pro",
                        response_format="json",
                        timeout=300.0,
                    )
                    pro_conflict = _build_conflict(pair, pro_result, model="pro+evidence")
                    pro_conflict["evidence_collected"] = evidence[:500] if evidence else ""
                    for i, c in enumerate(conflicts):
                        if (c["source_a"]["url"] == pro_conflict["source_a"]["url"] and
                                c["source_b"]["url"] == pro_conflict["source_b"]["url"]):
                            conflicts[i] = pro_conflict
                            break
                except Exception as e:
                    print_agent_output(f"Pro re-arbitration failed: {e}", agent="CONFLICT_DETECTOR")

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
        }
