"""Phase 6-A output redaction and report HTML safety contracts."""

from __future__ import annotations

import pytest

from deepchoice.contracts.errors import DeepChoiceError, normalize_error
from deepchoice.security.html import render_safe_report_html, sanitize_html
from deepchoice.security.redaction import REDACTED, redact_text, redact_value
from deepchoice.utils.views import print_agent_output


def test_redactor_removes_credentials_query_secrets_and_secret_shaped_tokens() -> None:
    canary = "AbCDefghijkLMNopqrstUVWXyz0123456789+/="
    text = redact_text(
        "Authorization: Bearer header-secret\n"
        "apiKey=plain-secret "
        "https://alice:password@example.com/path?token=url-secret&view=full "
        f"opaque={canary}"
    )
    for secret in ("header-secret", "plain-secret", "password", "url-secret", canary):
        assert secret not in text
    assert REDACTED in text
    assert "view=full" not in text

    query_url = redact_text("https://api.example/search?q=private-research")
    assert "private-research" not in query_url
    assert "search" not in query_url


@pytest.mark.parametrize(
    "carrier",
    (
        "DS_FLASH_API_KEY=config-canary",
        "QW_FLASH_API_KEY=config-canary",
        "FWD_KEY=config-canary",
        "X-Fwd-Key: config-canary",
        "Authorization: custom config-canary",
        "Cookie: session=config-canary; preference=private",
    ),
)
def test_redactor_covers_prefixed_configuration_and_header_keys(carrier: str) -> None:
    rendered = redact_text(carrier)
    assert "config-canary" not in rendered
    assert "private" not in rendered


def test_structured_redaction_is_recursive_bounded_and_non_mutating() -> None:
    source = {
        "headers": {"Authorization": "Bearer nested-secret"},
        "api_key": "direct-secret",
        "query": "private research question",
        "safe": [{"url": "https://example.com/?signature=signed-secret"}],
    }
    result = redact_value(source)
    assert source["api_key"] == "direct-secret"
    assert result["api_key"] == REDACTED
    assert result["query"] == REDACTED
    rendered = str(result)
    assert "nested-secret" not in rendered
    assert "signed-secret" not in rendered


def test_agent_log_and_application_error_never_emit_secret_canary(capsys) -> None:
    print_agent_output(
        "provider failed api_key=log-secret at "
        "https://example.com/path?access_token=query-secret",
        agent="TEST",
    )
    output = capsys.readouterr().out
    assert "log-secret" not in output
    assert "query-secret" not in output

    error = DeepChoiceError(
        "failed password=error-secret",
        details={"refreshToken": "detail-secret"},
    )
    detail = normalize_error(error)
    assert "error-secret" not in detail.message
    assert "detail-secret" not in str(detail.details)


def test_report_html_allowlist_blocks_active_content_and_unsafe_links() -> None:
    report = """# Safe heading

<script>alert('script-canary')</script>
<iframe src="https://evil.example"></iframe>
<img src=x onerror="alert('handler-canary')">
[bad](javascript:alert('scheme-canary'))
[data](data:text/html,boom)
[credentials](https://user:pass@example.com/private)
[good](https://example.com/docs)
<span id="sec-1"></span>A<sup><a class="cite" href="#ev-1">[1]</a></sup>
"""
    rendered = render_safe_report_html(report)
    lowered = rendered.lower()
    for forbidden in (
        "<script",
        "<iframe",
        "<img",
        "onerror",
        "javascript:",
        "data:text",
        "user:pass",
        "script-canary",
        "handler-canary",
    ):
        assert forbidden not in lowered
    assert 'href="https://example.com/docs"' in rendered
    assert 'rel="noopener noreferrer nofollow"' in rendered
    assert 'id="sec-1"' in rendered
    assert 'class="cite" href="#ev-1"' in rendered


def test_html_sanitizer_drops_styles_namespaces_and_event_attributes() -> None:
    rendered = sanitize_html(
        '<div style="background:url(javascript:boom)" onclick="boom()">ok</div>'
        '<svg><a href="javascript:boom">bad</a></svg>'
    )
    assert rendered == "<div>ok</div>"
