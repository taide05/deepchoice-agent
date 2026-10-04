"""Bounded official-page reading, not a general crawler or truth classifier."""
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from .. import outbound
from ..budget_errors import BudgetPersistenceError
from ..utils.evidence import source_title
from ..utils.evidence_choices import whole_source_text
from ..utils.source_scope import MAX_SCOPE_CHARS, scope_sentences
from ..utils.official_catalog import catalog_scope_contains, parse_http_identity

MAX_ROOTS = 2
MAX_CHILDREN = 2
MAX_PAGE_BYTES = 128 * 1024
MAX_LINKS = 256
MAX_SNIPPET = 1200
_STOP = frozenset("a an and are as at be by can compare comparison could docs documentation do does for from guide how in is it of on or official reference should than that the their these this to use using versus vs what when which with would".split())
_ASSETS = (".js", ".css", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".gz", ".pdf", ".json", ".xml")


async def budgeted_http(dispatch, *, kind: str, require_budget: bool = False):
    """One logical HTTP operation, in addition to its source retrieval charge."""
    # The manifest imports retrievers while budget contracts are initialized.
    from ..budget.contracts import BudgetAmount, BudgetResource
    from ..budget.runtime import reserve_call, settle_call, unknown_call

    reservations = await reserve_call(
        (BudgetAmount(resource=BudgetResource.HTTP_CALLS, amount=1),),
        call_id=None, summary={"kind": kind},
    )
    if require_budget and not reservations:
        raise BudgetPersistenceError("Official body retrieval requires an active budget reservation")
    try:
        response = await dispatch()
    except BaseException:
        await unknown_call(reservations)
        raise
    await settle_call(reservations, {BudgetResource.HTTP_CALLS: 1})
    return response


def _terms(text: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z0-9]{2,}", text.casefold())) - _STOP


def _scoped_url(root: str, base: str, href: str) -> str | None:
    if not isinstance(href, str) or not href or len(href) > 2048 or href.startswith("#"):
        return None
    if any(ord(ch) < 32 or 127 <= ord(ch) <= 159 for ch in href) or "\\" in href:
        return None
    try:
        value = urljoin(base, href)
        parsed = urlsplit(value)
        if parsed.query or (urlsplit(root).scheme == "https" and parsed.scheme != "https"):
            return None
        value = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    except (ValueError, UnicodeError):
        return None
    if parse_http_identity(value) is None or not catalog_scope_contains(root, value):
        return None
    if parsed.path.casefold().endswith(_ASSETS):
        return None
    return value


class _PageLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.href = None
        self.label = []
        self.title_parts = []
        self.in_title = False
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "template", "svg"}:
            self.ignored += 1
        if self.ignored:
            return
        if tag == "title":
            self.in_title = True
        if tag == "a" and len(self.links) < MAX_LINKS:
            hrefs = [value for key, value in attrs if key == "href"]
            self.href = hrefs[0] if len(hrefs) == 1 else None
            self.label = []

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "template", "svg"} and self.ignored:
            self.ignored -= 1
        if self.ignored:
            return
        if tag == "title":
            self.in_title = False
        if tag == "a" and self.href is not None:
            self.links.append((self.href, " ".join(self.label)[:500]))
            self.href = None
            self.label = []

    def handle_data(self, value):
        if self.ignored:
            return
        if self.in_title and sum(map(len, self.title_parts)) < 300:
            self.title_parts.append(value[:300])
        if self.href is not None and sum(map(len, self.label)) < 500:
            self.label.append(value[:500])


def _snippet(document, terms: set[str]) -> tuple[str, int]:
    if not terms:
        return "", 0
    choices = []
    for index, block in enumerate(document.blocks):
        # A link list/heading is not substantive prose merely because it matches.
        if len(block) < 80 or not re.search(r"[.!?。！？]", block):
            continue
        score = len(_terms(block) & terms)
        if terms and not score:
            continue
        left, right = max(0, index - 1), min(len(document.blocks), index + 2)
        if document.incomplete and right == len(document.blocks):
            continue
        # Keep neighbouring conditions; never trim a block to fit a positive claim.
        text = " ".join(document.blocks[left:right])
        if len(text) > MAX_SNIPPET or not whole_source_text(text):
            continue
        choices.append((score, -index, text))
    if not choices:
        return "", 0
    score, _, text = max(choices)
    return text, score


def _scope_near_snippet(document, snippet: str) -> list[str] | None:
    """Expose at most one extra neighboring block from an already fetched page."""
    if not snippet or document.incomplete:
        return None
    blocks = document.blocks
    whole = " ".join(blocks)
    start = whole.find(snippet)
    if start < 0 or whole.find(snippet, start + 1) >= 0:
        return None
    end = start + len(snippet)
    positions = []
    cursor = 0
    for index, block in enumerate(blocks):
        if cursor < end and cursor + len(block) > start:
            positions.append(index)
        cursor += len(block) + 1
    if not positions:
        return None
    left, right = positions[0], positions[-1] + 1
    # Prefer the following block, where a nearby exception often follows the
    # main claim. Then admit one preceding block only if the total remains
    # bounded. Neither block earns citation status without a later live fetch.
    if right < len(blocks) and len(" ".join(blocks[left:right + 1])) <= MAX_SCOPE_CHARS:
        right += 1
    if left > 0 and len(" ".join(blocks[left - 1:right])) <= MAX_SCOPE_CHARS:
        left -= 1
    sentences = scope_sentences(" ".join(blocks[left:right]))
    return list(sentences) if sentences else None


async def _read_page(root: str, url: str, terms: set[str]):
    from ..citations.source_windows import extract_source_document

    response = await budgeted_http(
        lambda: outbound.safe_fetch(
            "official", url, method="GET",
            allowed_content_types=("text/html", "application/xhtml+xml", "text/plain"),
            max_response_bytes=MAX_PAGE_BYTES, max_redirects=3, timeout_s=15.0,
            allow_response_truncation=True,
        ), kind="official_body", require_budget=True,
    )
    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(f"Official body HTTP {response.status_code}")
    final_url = _scoped_url(root, url, str(response.url))
    if final_url is None:
        raise ValueError("Official body left its catalog scope")
    plain = response.headers.get("content-type", "").split(";", 1)[0].strip().lower() == "text/plain"
    parsed = _PageLinks()
    if not plain:
        parsed.feed(response.text)
        parsed.close()
    document = extract_source_document(
        response.text, truncated=bool(response.extensions.get("deepchoice_body_truncated")),
        plain_text=plain, skip_navigation=True,
    )
    snippet, score = _snippet(document, terms)
    title = source_title(" ".join(parsed.title_parts), final_url)
    result = {"url": final_url, "title": title, "snippet": snippet, "date": ""} if snippet else None
    if result is not None:
        scope = _scope_near_snippet(document, snippet)
        if scope:
            result["_source_scope_sentences"] = scope
    links = []
    seen = {final_url, url}
    for href, label in parsed.links:
        child = _scoped_url(root, final_url, href)
        if child is None or child in seen:
            continue
        seen.add(child)
        overlap = len((_terms(label) | _terms(urlsplit(child).path)) & terms)
        if overlap:
            links.append((overlap, child))
    links.sort(key=lambda item: -item[0])
    return result, score, [url for _, url in links[:MAX_CHILDREN]]


async def read_official_roots(roots: list[dict], query_text: str) -> list[dict]:
    """Read at most two curated roots and two relevant direct children each.

    Every error propagates into the existing atomic failed source envelope.
    A successful page with no bounded relevant prose contributes no evidence.
    """
    groups = []
    seen = set()
    for root in roots[:MAX_ROOTS]:
        url = root["url"]
        terms = _terms(query_text) - _terms(root["title"]) - _terms(root["tech"])
        result, score, children = await _read_page(url, url, terms)
        group = [(score, result)] if result is not None else []
        for child in children:
            if child in seen:
                continue
            seen.add(child)
            item, child_score, _ = await _read_page(url, child, terms)
            if item is not None:
                group.append((child_score, item))
        group.sort(key=lambda item: -item[0])
        groups.append([item for _, item in group])
    output = []
    seen_results = set()
    # Keep both roots represented before one root consumes the result capacity.
    for index in range(1 + MAX_CHILDREN):
        for group in groups:
            if index < len(group) and group[index]["url"] not in seen_results:
                seen_results.add(group[index]["url"])
                output.append(group[index])
    return output
