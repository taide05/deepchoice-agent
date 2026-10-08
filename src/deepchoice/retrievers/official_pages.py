"""Bounded official-page reading, not a general crawler or truth classifier."""
import httpx

from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from .. import outbound
from ..budget_errors import BudgetError
from ..security.urls import SafeFetchFailure, UnsafeUrlError
from .contracts import PartialRetrievalError
from .http import budgeted_http
from ..utils.evidence import source_title
from ..utils.evidence_choices import whole_source_text
from ..utils.source_scope import (
    MAX_SCOPE_CHARS, scope_sentences, source_terms as _terms,
    proposal_hints as _proposal_hints, proposal_scope as _proposal_scope,
)
from ..utils.official_catalog import catalog_scope_contains, parse_http_identity

MAX_ROOTS = 2
MAX_CHILDREN = 2
MAX_PAGE_BYTES = 128 * 1024
MAX_LINKS = 256
MAX_SNIPPET = 1200
_ASSETS = (".js", ".css", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".gz", ".pdf", ".json", ".xml")


def exact_discovered_url(url: object) -> str | None:
    """Validate a dynamic page locator without granting catalog/path authority."""
    if not isinstance(url, str) or len(url) > 2048 or any(ch.isspace() for ch in url):
        return None
    identity = parse_http_identity(url)
    if identity is None:
        return None
    parsed = urlsplit(url)
    if parsed.query or parsed.fragment:
        return None
    scheme = parsed.scheme.casefold()
    port = parsed.port
    host = identity[0]
    if port is not None and port != (443 if scheme == "https" else 80):
        host += f":{port}"
    return urlunsplit((scheme, host, parsed.path or "/", "", ""))


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


async def _read_page(root: str, url: str, terms: set[str], *, exact_page: bool = False, hints: set[str] | None = None):
    from ..citations.source_windows import extract_source_document

    response = await budgeted_http(
        lambda: outbound.safe_fetch(
            "official", url, method="GET",
            allowed_content_types=("text/html", "application/xhtml+xml", "text/plain"),
            max_response_bytes=MAX_PAGE_BYTES, max_redirects=0 if exact_page else 3, timeout_s=15.0,
            allow_response_truncation=True,
        ), kind="official_body", require_budget=True,
    )
    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(f"Official body HTTP {response.status_code}")
    if exact_page:
        final_url = exact_discovered_url(str(response.url))
        if final_url != exact_discovered_url(url):
            raise ValueError("Discovered page changed its exact locator")
    else:
        final_url = _scoped_url(root, url, str(response.url))
    if final_url is None:
        raise ValueError("Official body left its catalog scope")
    plain = response.headers.get("content-type", "").split(";", 1)[0].strip().lower() == "text/plain"
    parsed = _PageLinks()
    try:
        if not plain:
            parsed.feed(response.text)
            parsed.close()
        document = extract_source_document(
            response.text, truncated=bool(response.extensions.get("deepchoice_body_truncated")),
            plain_text=plain, skip_navigation=True, raise_on_error=True,
        )
    except BudgetError:
        raise
    except Exception as exc:
        raise RuntimeError("Official page parsing failed") from exc
    hints = terms if hints is None else hints
    snippet, score = _snippet(document, terms)
    title = source_title(" ".join(parsed.title_parts), final_url)
    scope = _scope_near_snippet(document, snippet) if snippet else _proposal_scope(document, hints)
    result = {"url": final_url, "title": title, "snippet": snippet, "date": ""} if snippet or scope else None
    if result is not None and scope:
        result["_source_scope_sentences"] = scope
    if exact_page:
        return result, score, [], False
    links = []
    fallback_links = []
    seen = {final_url, url}
    for href, label in parsed.links:
        child = _scoped_url(root, final_url, href)
        if child is None or child in seen:
            continue
        seen.add(child)
        fallback_links.append(child)
        overlap = len((_proposal_hints(label) | _proposal_hints(urlsplit(child).path)) & hints)
        if overlap:
            links.append((overlap, child))
    links.sort(key=lambda item: -item[0])
    # A proposal has not established relevance. Explore bounded real links even
    # when an introductory root paragraph exists; preserve it on a local child
    # failure through an explicit partial outcome, never silent success.
    supplemental = bool(not links and result is not None and not snippet)
    children = ([url for _, url in links[:MAX_CHILDREN]] if links
                else fallback_links[:MAX_CHILDREN] if result is None or supplemental else [])
    return result, score, children, supplemental


def _local_page_failure(exc: Exception) -> bool:
    if isinstance(exc, UnsafeUrlError):
        return exc.failure in {
            SafeFetchFailure.SAFETY_REJECTED, SafeFetchFailure.RESPONSE_REJECTED,
            SafeFetchFailure.DNS_UNCERTAIN, SafeFetchFailure.TIMEOUT,
        }
    return isinstance(exc, (RuntimeError, httpx.HTTPError, OSError))


def _ordered_results(groups: list[list[tuple[int, dict]]]) -> list[dict]:
    output, seen = [], set()
    ordered = [sorted(group, key=lambda item: -item[0]) for group in groups]
    # Keep both roots represented before one root consumes the result capacity.
    for index in range(1 + MAX_CHILDREN):
        for group in ordered:
            if index < len(group):
                item = group[index][1]
                if item["url"] not in seen:
                    seen.add(item["url"])
                    output.append(item)
    return output


async def read_official_roots(roots: list[dict], query_text: str) -> list[dict]:
    """Read at most two locators; only curated roots may expand children.

    Discovered locators read one exact page with redirects disabled. They do
    not become official authority merely by entering this acquisition channel.
    Roots and matched children retain atomic failure. A failed supplemental
    child can preserve earlier safe pages in an explicit partial envelope;
    no further page is dispatched after that failure.
    Unselected fallback scopes are proposals, not evidence; the evaluator must
    select bounded passages before they can enter source scoring.
    """
    groups = []
    seen = set()
    for root in roots[:MAX_ROOTS]:
        url = root["url"]
        terms = _terms(query_text) - _terms(root["title"]) - _terms(root["tech"])
        hints = _proposal_hints(query_text) - _proposal_hints(root["title"]) - _proposal_hints(root["tech"])
        curated = root.get("curated") is True
        result, score, children, supplemental = await _read_page(url, url, terms, exact_page=not curated, hints=hints)
        origin_kind = "curated" if curated else "discovered"
        group = [(score, {**result, "origin_kind": origin_kind})] if result is not None else []
        groups.append(group)
        for child in children:
            if child in seen:
                continue
            seen.add(child)
            try:
                item, child_score, _, _ = await _read_page(url, child, terms, hints=hints)
            except BudgetError:
                raise
            except Exception as exc:
                if not supplemental or not _local_page_failure(exc):
                    raise
                raise PartialRetrievalError(_ordered_results(groups), exc) from exc
            if item is not None:
                group.append((child_score, {**item, "origin_kind": origin_kind}))
    return _ordered_results(groups)
