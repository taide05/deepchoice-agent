"""Allowlist HTML rendering for untrusted report Markdown."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

import html5lib
import markdown


_ALLOWED_TAGS = frozenset(
    {
        "a",
        "blockquote",
        "br",
        "code",
        "del",
        "div",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "li",
        "ol",
        "p",
        "pre",
        "span",
        "strong",
        "sub",
        "sup",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "ul",
    }
)
_DROP_CONTENT_TAGS = frozenset(
    {"applet", "embed", "iframe", "math", "object", "script", "style", "svg", "template"}
)
_ALLOWED_ATTRIBUTES = {
    "a": frozenset({"class", "href", "rel", "target", "title"}),
    "div": frozenset({"class", "id"}),
    "span": frozenset({"class", "id"}),
    "td": frozenset({"colspan", "rowspan"}),
    "th": frozenset({"colspan", "rowspan"}),
}
_SAFE_CLASS = re.compile(r"^(?:cite|report-[a-z0-9_-]+)$")
_SAFE_ID = re.compile(r"^(?:sec|ev)-[1-9][0-9]{0,8}$")
_SAFE_INTERNAL_HREF = re.compile(r"^#(?:sec|ev)-[1-9][0-9]{0,8}$")


def _safe_external_href(value: str) -> bool:
    if not value or len(value) > 2048 or any(ord(char) < 32 for char in value):
        return False
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"}:
            return False
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return False
        port = parsed.port
        if port is not None and port not in {80, 443}:
            return False
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            return True
        return address.is_global
    except ValueError:
        return False


def _append_tail(parent, index: int, text: str | None) -> None:
    if not text:
        return
    if index > 0:
        previous = parent[index - 1]
        previous.tail = (previous.tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def _sanitize_children(parent) -> None:
    for child in list(parent):
        raw_tag = child.tag.lower() if isinstance(child.tag, str) else ""
        namespaced = "}" in raw_tag
        tag = raw_tag.rsplit("}", 1)[-1]
        if tag not in _ALLOWED_TAGS:
            index = list(parent).index(child)
            if not namespaced and tag not in _DROP_CONTENT_TAGS:
                preserved = (child.text or "") + "".join(
                    html5lib.serialize(grandchild, tree="etree")
                    for grandchild in list(child)
                )
                _append_tail(parent, index, preserved)
            _append_tail(parent, index, child.tail)
            parent.remove(child)
            continue

        allowed = _ALLOWED_ATTRIBUTES.get(tag, frozenset())
        attributes = dict(child.attrib)
        child.attrib.clear()
        for raw_name, raw_value in attributes.items():
            name = raw_name.lower()
            value = str(raw_value)
            if name not in allowed or name.startswith("on"):
                continue
            if name == "href":
                if not (_SAFE_INTERNAL_HREF.fullmatch(value) or _safe_external_href(value)):
                    continue
                child.attrib["href"] = value
            elif name == "class":
                classes = [item for item in value.split() if _SAFE_CLASS.fullmatch(item)]
                if classes:
                    child.attrib["class"] = " ".join(classes)
            elif name == "id":
                if _SAFE_ID.fullmatch(value):
                    child.attrib["id"] = value
            elif name in {"colspan", "rowspan"}:
                if value.isdigit() and 1 <= int(value) <= 100:
                    child.attrib[name] = value
            elif name == "title":
                child.attrib[name] = value[:300]

        if tag == "a" and "href" in child.attrib:
            href = child.attrib["href"]
            if not href.startswith("#"):
                child.attrib["target"] = "_blank"
                child.attrib["rel"] = "noopener noreferrer nofollow"
        _sanitize_children(child)


def sanitize_html(fragment_html: str) -> str:
    """Remove executable HTML, dangerous attributes, and unsafe link schemes."""

    fragment = html5lib.parseFragment(
        str(fragment_html),
        treebuilder="etree",
        namespaceHTMLElements=False,
    )
    _sanitize_children(fragment)
    return html5lib.serialize(
        fragment,
        tree="etree",
        quote_attr_values="always",
        omit_optional_tags=False,
    )


def render_safe_report_html(report_markdown: str) -> str:
    """Render report Markdown once, then sanitize the complete HTML fragment."""

    rendered = markdown.markdown(str(report_markdown), extensions=["tables"])
    return sanitize_html(rendered)


__all__ = ["render_safe_report_html", "sanitize_html"]
