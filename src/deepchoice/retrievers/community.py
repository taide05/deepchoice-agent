import asyncio
from datetime import UTC, datetime

from .. import outbound as _outbound
from ..outbound import throttle
from ..outbound.credentials import stackexchange_params
from ..utils.evidence_choices import whole_source_text
from ..utils.source_scope import proposal_hints, proposal_scope
from .base import BaseRetriever
from .http import budgeted_http, check_response_size
from .query_results import merge_query_results

_SEARCH_TIMEOUT_S = 180.0


class CommunitySearch(BaseRetriever):
    source = "community"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None) -> list[dict]:
        from ..runtime.context import get_run_context
        from ..citations.source_windows import extract_page_document

        queries = list(dict.fromkeys(adapted_queries)) if adapted_queries else [query]
        hints = proposal_hints(" ".join([query, *sub_questions]))
        batches = []
        async with asyncio.timeout(_SEARCH_TIMEOUT_S):
            for keywords in queries:
                params = stackexchange_params({"q": keywords, "site": "stackoverflow",
                                              "pagesize": max(2, max_results),
                                              "order": "desc", "sort": "relevance",
                                              "filter": "withbody"})
                async def dispatch():
                    # Resolve outside the provider slot so its probe can use it.
                    async with await _outbound.make_client("community") as client:
                        return await throttle.get(
                            "community", client, "https://api.stackexchange.com/2.3/search/advanced",
                            params=params, timeout=15.0, request_timeout=15.0,
                        )
                response = await budgeted_http(dispatch, kind="community_query",
                                               require_budget=get_run_context() is not None)
                check_response_size(response)
                if response.status_code != 200:
                    raise RuntimeError(f"StackExchange HTTP {response.status_code}")
                body = response.json()
                if isinstance(body, dict) and body.get("error_id") is not None:
                    raise RuntimeError("StackExchange API error")
                if not isinstance(body, dict) or not isinstance(body.get("items"), list):
                    raise ValueError("Invalid StackExchange question envelope")
                results = []
                for item in body["items"][:max_results]:
                    if (not isinstance(item, dict) or not isinstance(item.get("body"), str)
                            or not item["body"].strip()):
                        raise ValueError("StackExchange question body unavailable")
                    # Questions are reported context, not verified answers. Keep
                    # code settings with prose; skip navigation and explicit hidden blocks.
                    document = extract_page_document(
                        item["body"], truncated=False, raise_on_error=True,
                    )
                    if document.incomplete:
                        raise ValueError("Incomplete StackExchange question body")
                    snippet = whole_source_text(" ".join(document.blocks))
                    # A complete short body needs no second, narrower selection.
                    scope = proposal_scope(document, hints) if not snippet else None
                    if not snippet and not scope:
                        raise ValueError("No admitted StackExchange question range")
                    date_str = ""
                    if ts := item.get("creation_date"):
                        date_str = datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")
                    result = {
                        "url": item.get("link", ""), "title": item.get("title", ""),
                        "snippet": snippet,
                        "date": date_str,
                    }
                    if scope:
                        result["_source_scope_sentences"] = scope
                    results.append(result)
                batches.append(results)
        return merge_query_results(batches, max_results)
