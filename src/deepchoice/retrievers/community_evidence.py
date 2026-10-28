"""Isolated StackExchange evidence-pack retriever (v1 design).

This module is intentionally *not* wired into the default path. The legacy
``community.py`` behavior stays the default; ``CommunitySearch`` only delegates
here when ``COMMUNITY_RETRIEVAL_MODE=evidence_pack`` is set.

Design notes: COMMUNITY_RETRIEVAL_DESIGN_20261028.md.
"""
from __future__ import annotations

import asyncio
import html
import os
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from .. import outbound as _outbound

SE_API_BASE = "https://api.stackexchange.com/2.3"
SE_SITE = "stackoverflow"
SE_TIMEOUT_S = 30.0
SE_QUEUE_TIMEOUT_S = 30.0
SE_QUEUE_SEM = asyncio.Semaphore(1)
SE_BACKOFF_UNTIL = 0.0
SE_QUOTA_FLOOR = 500

# v1 budgets from the design document. They are deliberately conservative and
# tunable; the important property is that a case can never issue unbounded
# StackExchange requests.
MAX_SEARCH_VARIANTS = 2
MAX_CASE_REQUESTS = 6
MAX_PACKS_PER_CASE = 2
MAX_ANSWERS_PER_PACK = 2
MAX_COMMENTS_PER_PACK = 6
PACK_TEXT_LIMIT = 12_000
QUESTION_BODY_LIMIT = 2_500
ANSWER_BODY_LIMIT = 3_000
COMMENT_BODY_LIMIT = 500

_EN_DIMENSIONS = {
    "审计": "audit",
    "权限": "permissions rbac",
    "迁移": "migration",
    "性能": "performance latency",
    "成本": "cost pricing",
    "安全": "security",
    "监控": "monitoring observability",
    "部署": "deployment",
    "并发": "concurrency",
    "扩展": "scaling",
    "兼容": "compatibility",
    "维护": "maintenance upgrade",
    "集成": "integration",
    "学习曲线": "learning curve",
    "生态": "ecosystem",
    "文档": "documentation",
    "运维": "operations",
    "高可用": "high availability",
    "回滚": "rollback",
    "数据": "data storage",
    "对比": "compare comparison",
    "选型": "choose selection",
    "限制": "limitations",
    "许可证": "license",
    "社区": "community support",
    "插件": "plugins extensions",
    "故障": "troubleshooting issue",
    "可靠性": "reliability",
    "吞吐": "throughput",
    "延迟": "latency",
    "温度": "temperature",
    "内存": "memory",
    "线程": "thread",
    "连接": "connection",
    "代理": "proxy",
}
_ASCII_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}")
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

_LOGIN_HINTS = ("log in", "sign in", "login", "cookie", "javascript")


@dataclass
class RequestBudget:
    """Per-case StackExchange request budget; mutable by design."""

    remaining: int = MAX_CASE_REQUESTS
    requests: int = 0

    def take(self) -> None:
        if self.remaining <= 0:
            raise RuntimeError("StackExchange per-case request budget exhausted")
        self.remaining -= 1
        self.requests += 1


@dataclass
class EvidenceResult:
    packs: list[dict]
    search_queries: list[str]
    questions_seen: int
    requests: int
    packages_built: int
    errors: list[str] = field(default_factory=list)


_SEARCH_CACHE: dict[str, list[dict]] = {}
_PACK_CACHE: dict[str, dict] = {}


def clear_cache() -> None:
    """Clear the process-local caches (tests and explicit retries)."""
    _SEARCH_CACHE.clear()
    _PACK_CACHE.clear()


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


def _api_key() -> str:
    return os.getenv("STACKEXCHANGE_API_KEY", "")


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = html.unescape(str(value))
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    return _WS.sub(" ", text).strip()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _ascii_terms(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for token in _ASCII_WORD.findall(text or ""):
        low = token.lower().strip(".")
        if len(low) < 3 or low in seen:
            continue
        seen.add(low)
        out.append(token)
    return out


def _english_dimensions(text: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for zh, en in _EN_DIMENSIONS.items():
        if zh in (text or ""):
            for part in en.split():
                if part not in seen:
                    seen.add(part)
                    terms.append(part)
    # Also respect explicit English dimension words already in the input.
    for token in _ascii_terms(text or ""):
        low = token.lower()
        if low in {"audit", "permission", "permissions", "rbac", "migration",
                   "performance", "security", "cost", "monitoring", "deployment",
                   "concurrency", "scaling", "compatibility", "maintenance",
                   "integration", "documentation", "operations", "rollback"}:
            if low not in seen:
                seen.add(low)
                terms.append(low)
    return terms


def build_query_variants(
    query: str,
    sub_questions: list[str] | None = None,
    adapted_queries: list[str] | None = None,
    candidate_techs: list[str] | None = None,
) -> list[str]:
    """Build a few short, Stack-Overflow-friendly queries.

    The legacy retriever passed a 150-char natural-language (often Chinese)
    string as ``intitle``; this planner deliberately uses candidate names plus a
    small number of English dimension terms instead.
    """
    candidates = [c.strip() for c in (candidate_techs or []) if c and c.strip()]
    candidates = [c for c in candidates if _ASCII_WORD.search(c)]
    if not candidates:
        candidates = _ascii_terms(" ".join([query or "", *(adapted_queries or [])]))[:4]

    context = " ".join([query or "", *(sub_questions or []), *(adapted_queries or [])])
    dims = _english_dimensions(context)
    base = " ".join(dict.fromkeys(candidates))
    variants: list[str] = []
    if base:
        # Start with the candidate names alone: stacking several dimension words
        # onto an English Q&A title search collapses the result set to zero.
        # Dimension terms are a fallback variant, not the primary query.
        variants.append(_truncate(base, 160))
        if dims:
            variants.append(_truncate(f"{base} {' '.join(dims[:2])}".strip(), 160))
    else:
        # No candidate/English anchor: search cannot be made meaningful on an
        # English Q&A site; let the caller report an empty/failed source instead
        # of sending a long Chinese title query and pretending it was a search.
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    for q in variants:
        q = _WS.sub(" ", q).strip()
        if q and q.lower() not in seen:
            seen.add(q.lower())
            cleaned.append(q)
    return cleaned[:MAX_SEARCH_VARIANTS]


def _contains_term(text: str, term: str) -> bool:
    if not term:
        return False
    pattern = r"(?<![A-Za-z0-9])" + re.escape(term.lower()) + r"(?![A-Za-z0-9])"
    return re.search(pattern, text.lower()) is not None


def score_candidate(
    item: dict,
    candidate_techs: list[str] | None = None,
    dimension_terms: list[str] | None = None,
    now: datetime | None = None,
) -> dict | None:
    """Score one StackExchange question candidate; return None if irrelevant."""
    candidates = [c for c in (candidate_techs or []) if c]
    title = str(item.get("title") or "")
    tags = " ".join(item.get("tags") or [])
    text = f"{title} {tags}"
    name_hits = sum(1 for c in candidates if _contains_term(text, c))
    dim_hits = sum(1 for d in (dimension_terms or []) if _contains_term(text, d))
    if name_hits == 0 and dim_hits < 2:
        return None

    relevance = min(1.0, name_hits * 0.4 + dim_hits * 0.12)
    answer_count = int(item.get("answer_count") or 0)
    score = int(item.get("score") or 0)
    favorite_count = int(item.get("favorite_count") or 0)
    accepted = 1 if item.get("accepted_answer_id") else 0
    quality = min(1.0, accepted * 0.35
                  + min(max(score, 0), 50) / 50 * 0.25
                  + min(max(answer_count, 0), 5) / 5 * 0.20
                  + min(max(favorite_count, 0), 10) / 10 * 0.20)

    ts = item.get("last_activity_date") or item.get("creation_date")
    recency = 0.5
    if ts:
        try:
            age_days = max(0.0, ((now or _now_utc()).timestamp() - float(ts)) / 86400)
            recency = 1.0 / (1.0 + age_days / 365.0)
        except (TypeError, ValueError, OSError):
            recency = 0.5

    total = 0.45 * relevance + 0.30 * quality + 0.15 * recency + 0.10 * min(1.0, max(0, score) / 50)
    enriched = dict(item)
    enriched["_relevance"] = round(relevance, 4)
    enriched["_quality"] = round(quality, 4)
    enriched["_recency"] = round(recency, 4)
    enriched["_rank_score"] = round(total, 4)
    enriched["_name_hits"] = name_hits
    return enriched


def select_questions(
    items: list[dict],
    candidate_techs: list[str] | None = None,
    dimension_terms: list[str] | None = None,
    limit: int = MAX_PACKS_PER_CASE,
    now: datetime | None = None,
) -> list[dict]:
    scored: list[dict] = []
    for item in items:
        enriched = score_candidate(item, candidate_techs, dimension_terms, now=now)
        if enriched is not None:
            scored.append(enriched)
    scored.sort(key=lambda x: (x["_rank_score"], x.get("_relevance", 0)),
                reverse=True)
    # Relative selection only: keep the best candidates, never drop a highly
    # relevant low-vote niche thread merely because its absolute vote count is
    # small. The relevance gate in score_candidate already filters noise.
    selected: list[dict] = []
    seen_ids: set[str] = set()
    for item in scored:
        qid = str(item.get("question_id") or item.get("link") or "")
        if qid in seen_ids:
            continue
        seen_ids.add(qid)
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def _pack_date(item: dict) -> str:
    ts = item.get("last_activity_date") or item.get("creation_date")
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(float(ts), tz=UTC).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


def _author(item: dict) -> str:
    owner = item.get("owner") or {}
    return str(owner.get("display_name") or "anonymous")


def _selected_answers(items: list[dict], limit: int = MAX_ANSWERS_PER_PACK) -> list[dict]:
    def key(ans: dict) -> tuple[int, int, int]:
        return (1 if ans.get("is_accepted") else 0,
                int(ans.get("score") or 0),
                int(ans.get("creation_date") or 0))
    return sorted(items, key=key, reverse=True)[:limit]


def _selected_comments(items: list[dict], limit: int = MAX_COMMENTS_PER_PACK) -> list[dict]:
    def key(comment: dict) -> tuple[int, int]:
        return (int(comment.get("score") or 0), int(comment.get("creation_date") or 0))
    return sorted(items, key=key, reverse=True)[:limit]


def build_pack(question: dict, answers: list[dict], comments: list[dict]) -> dict:
    """Build one question-level evidence pack (question + answers + comments)."""
    qid = str(question.get("question_id") or "")
    title = _clean_text(question.get("title") or "Stack Overflow discussion")
    link = str(question.get("link") or "")
    q_body = _truncate(_clean_text(question.get("body") or ""), QUESTION_BODY_LIMIT)
    date = _pack_date(question)
    lines = [
        f"社区讨论（Stack Overflow，非官方；下列内容为作者/评论者观点，不是官方事实）",
        f"问题：{title}",
        f"问题评分 {int(question.get('score') or 0)}；回答数 {int(question.get('answer_count') or 0)}；"
        f"最后活动 {date or '未知'}",
    ]
    if q_body:
        lines.append(f"问题正文：{q_body}")
    for index, answer in enumerate(_selected_answers(answers), start=1):
        body = _truncate(_clean_text(answer.get("body") or ""), ANSWER_BODY_LIMIT)
        if not body:
            continue
        accepted = "（accepted）" if answer.get("is_accepted") else ""
        lines.append(
            f"回答{index}{accepted}｜作者 {_author(answer)}｜评分 "
            f"{int(answer.get('score') or 0)}｜{_pack_date(answer) or '日期未知'}：{body}"
        )
    for index, comment in enumerate(_selected_comments(comments), start=1):
        body = _truncate(_clean_text(comment.get("body") or ""), COMMENT_BODY_LIMIT)
        if not body:
            continue
        lines.append(
            f"评论{index}｜作者 {_author(comment)}｜评分 "
            f"{int(comment.get('score') or 0)}｜{_pack_date(comment) or '日期未知'}：{body}"
        )
    text = _truncate("\n".join(lines), PACK_TEXT_LIMIT)
    return {
        "url": link,
        "title": f"Stack Overflow — {title}",
        "snippet": text,
        "has_body": True,
        "date": date,
        "content": text,
        "provenance": "community",
        "channel": "community",
        "source_owner": None,
        "community_question_id": qid,
        "community_answers": len(_selected_answers(answers)),
        "community_comments": len(_selected_comments(comments)),
        "body_chars": len(text),
        "body_prose_chars": len(text),
        "body_url": link,
    }


async def _wait_for_backoff() -> None:
    now = time.monotonic()
    if now < SE_BACKOFF_UNTIL:
        await asyncio.sleep(SE_BACKOFF_UNTIL - now)


async def _community_client():
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            return await _outbound.make_client("community")
        except RuntimeError as exc:
            last_error = exc
            if attempt == 0:
                await asyncio.sleep(1.5)
    raise last_error if last_error is not None else RuntimeError(
        "community outbound client unavailable")


async def _request_json(
    client,
    path: str,
    params: dict,
    *,
    budget: RequestBudget,
    key: str,
) -> dict:
    """One bounded StackExchange GET with retry, backoff and quota handling."""
    global SE_BACKOFF_UNTIL
    query = dict(params)
    query.setdefault("site", SE_SITE)
    if key:
        query.setdefault("key", key)
    await asyncio.wait_for(SE_QUEUE_SEM.acquire(), timeout=SE_QUEUE_TIMEOUT_S)
    try:
        await _wait_for_backoff()
        last_error: Exception | None = None
        for attempt in range(2):
            budget.take()
            try:
                response = await client.get(SE_API_BASE + path, params=query)
            except (httpx.TimeoutException, httpx.TransportError, RuntimeError) as exc:
                last_error = exc
                if attempt == 0:
                    await asyncio.sleep(1.5)
                    continue
                raise RuntimeError(
                    f"StackExchange request {path} failed: {type(exc).__name__}: {exc}"
                ) from exc
            if response.status_code == 200:
                try:
                    body = response.json()
                except Exception as exc:  # noqa: BLE001 - malformed API payload
                    raise RuntimeError(
                        f"StackExchange returned non-JSON for {path}: {exc}"
                    ) from exc
                if body.get("backoff"):
                    try:
                        SE_BACKOFF_UNTIL = time.monotonic() + float(body["backoff"])
                    except (TypeError, ValueError):
                        pass
                quota = body.get("quota_remaining")
                if isinstance(quota, int) and quota < SE_QUOTA_FLOOR:
                    raise RuntimeError(
                        f"StackExchange quota too low ({quota} < {SE_QUOTA_FLOOR})"
                    )
                return body
            body_text = (response.text or "")[:300]
            if response.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                backoff = 1.5
                try:
                    payload = response.json()
                    backoff = float(payload.get("backoff") or backoff)
                except Exception:  # noqa: BLE001 - error body may not be JSON
                    pass
                SE_BACKOFF_UNTIL = max(SE_BACKOFF_UNTIL, time.monotonic() + backoff)
                await asyncio.sleep(backoff)
                continue
            raise RuntimeError(
                f"StackExchange HTTP {response.status_code} for {path}: {body_text}"
            )
        raise last_error if last_error is not None else RuntimeError(
            f"StackExchange request {path} produced no response")
    finally:
        SE_QUEUE_SEM.release()


async def _fetch_pack_details(
    client,
    questions: list[dict],
    *,
    budget: RequestBudget,
    key: str,
) -> list[dict]:
    """Fetch question/answer/comment bodies for the selected questions in 3
    batched requests (not 3 per question), keeping the case within budget."""
    qids = [str(item.get("question_id")) for item in questions
            if item.get("question_id")]
    if not qids:
        return []
    ids = ";".join(qids)
    q_resp = await _request_json(
        client, f"/questions/{ids}",
        {"filter": "withbody", "pagesize": len(qids)}, budget=budget, key=key)
    q_items = {str(item.get("question_id")): item
               for item in (q_resp.get("items") or [])}
    a_resp = await _request_json(
        client, f"/questions/{ids}/answers",
        {"filter": "withbody", "pagesize": 8, "order": "desc", "sort": "votes"},
        budget=budget, key=key)
    answers_by_q: dict[str, list[dict]] = {}
    for answer in a_resp.get("items") or []:
        answers_by_q.setdefault(str(answer.get("question_id")), []).append(answer)
    c_resp = await _request_json(
        client, f"/questions/{ids}/comments",
        {"filter": "withbody", "pagesize": 12, "order": "desc", "sort": "votes"},
        budget=budget, key=key)
    comments_by_q: dict[str, list[dict]] = {}
    for comment in c_resp.get("items") or []:
        # question comments carry post_id == question_id.
        comments_by_q.setdefault(str(comment.get("post_id")), []).append(comment)

    packs: list[dict] = []
    for question in questions:
        qid = str(question.get("question_id") or "")
        full_question = q_items.get(qid)
        if full_question is None:
            continue
        packs.append(build_pack(
            full_question,
            answers_by_q.get(qid, []),
            comments_by_q.get(qid, []),
        ))
    return packs


async def fetch_evidence_packs(
    query: str,
    sub_questions: list[str] | None = None,
    max_results: int = 7,
    adapted_queries: list[str] | None = None,
    candidate_techs: list[str] | None = None,
    *,
    client_factory=None,
    budget: RequestBudget | None = None,
    search_cache: dict[str, list[dict]] | None = None,
    pack_cache: dict[str, dict] | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """Run query planning → search → selection → detail fetch → packs.

    The caller (``CommunitySearch``) decides whether this mode is enabled; this
    function makes no changes to the legacy path.
    """
    budget = budget or RequestBudget()
    search_cache = _SEARCH_CACHE if search_cache is None else search_cache
    pack_cache = _PACK_CACHE if pack_cache is None else pack_cache
    key = _api_key()
    variants = build_query_variants(query, sub_questions, adapted_queries,
                                    candidate_techs)
    if not variants:
        return []

    dimension_terms = _english_dimensions(" ".join(
        [query or "", *(sub_questions or []), *(adapted_queries or [])]))
    client_factory = client_factory or _community_client
    client = await client_factory()
    entered = False
    try:
        await client.__aenter__()
        entered = True
        candidates: list[dict] = []
        for variant in variants[:MAX_SEARCH_VARIANTS]:
            if variant in search_cache:
                candidates.extend(search_cache[variant])
                if candidates:
                    break
                continue
            body = await _request_json(
                client, "/search/advanced",
                {"q": variant, "pagesize": 10, "order": "desc",
                 "sort": "relevance", "filter": "withbody"},
                budget=budget, key=key)
            items = body.get("items") or []
            search_cache[variant] = items
            candidates.extend(items)
            # Candidate-name search normally returns results. Only spend the
            # fallback variant when the first query produced nothing.
            if candidates:
                break
        selected = select_questions(
            candidates, candidate_techs, dimension_terms,
            limit=min(MAX_PACKS_PER_CASE, max(1, max_results)), now=now)
        cached_packs: list[dict] = []
        uncached: list[dict] = []
        for question in selected:
            qid = str(question.get("question_id") or "")
            if qid and qid in pack_cache:
                cached_packs.append(pack_cache[qid])
            else:
                uncached.append(question)
        if uncached:
            fetched = await _fetch_pack_details(
                client, uncached, budget=budget, key=key)
            for pack in fetched:
                qid = pack.get("community_question_id")
                if qid:
                    pack_cache[qid] = pack
            cached_packs.extend(fetched)
        return cached_packs[:min(MAX_PACKS_PER_CASE, max(1, max_results))]
    finally:
        if entered:
            try:
                await client.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001 - closing an already-exited client
                pass

