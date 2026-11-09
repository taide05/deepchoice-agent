"""F5 (five sub-questions) and F4 (deeper official docs page) regressions."""
import asyncio
from unittest.mock import AsyncMock, patch


from deepchoice.agents.query_analyzer import QueryAnalyzerAgent
from deepchoice.retrievers.official import _derived_doc_links
from deepchoice.retrievers.official_fetch import _resolved_links
from deepchoice.utils.page_text import extract_page_document


def test_query_analyzer_caps_more_than_five_sub_questions():
    state = {"task": {"query": "Celery vs RQ", "scene_context": "team",
                      "constraints": [], "report_format": "what_why_how"}}
    ten = [f"Celery vs RQ sub-question {i} with a concrete metric" for i in range(10)]

    async def run():
        agent = QueryAnalyzerAgent()
        with patch("deepchoice.agents.query_analyzer.call_model",
                   new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {"sub_questions": ten, "constraints": []}
            return await agent.run(state)

    result = asyncio.run(run())
    assert len(result["sub_questions"]) == 5
    signal = result["quality_signals"][0]
    assert signal["sub_questions_capped"] is True
    assert signal["sub_question_limit"] == 5


def test_page_text_exposes_links_for_follow_up_discovery():
    html = ('<html><body><main><a href="/docs/guide.html">Guide</a>'
            '<a href="https://example.com/api/">API</a></main></body></html>')
    document = extract_page_document(html, truncated=False)
    assert "/docs/guide.html" in document.links
    assert "https://example.com/api/" in document.links


def test_resolved_links_are_absolute_http_only():
    links = _resolved_links("https://docs.example.com/", [
        "/en/stable/", "https://other.example.com/x", "mailto:a@b.c", "",
    ])
    assert links == ["https://docs.example.com/en/stable/", "https://other.example.com/x"]


def test_derived_doc_links_prefers_deeper_docs_same_host():
    links = [
        "https://docs.example.com/",
        "https://docs.example.com/en/stable/",
        "https://docs.example.com/en/stable/guide/tasks.html",
        "https://docs.example.com/en/stable/index.html",
        "https://docs.example.com/pricing/",
        "https://other.example.com/en/stable/guide.html",
        "https://docs.example.com/assets/app.js",
    ]
    derived = _derived_doc_links("https://docs.example.com/", links)
    assert derived, derived
    assert all(url.startswith("https://docs.example.com/") for url in derived)
    assert "https://docs.example.com/en/stable/guide/tasks.html" in derived
    assert "https://docs.example.com/en/stable/index.html" not in derived
    assert "https://docs.example.com/pricing/" not in derived
    assert "https://other.example.com/en/stable/guide.html" not in derived
    assert "https://docs.example.com/assets/app.js" not in derived


def test_formal_case_candidates_resolve_curated_docs_roots():
    from deepchoice.retrievers.official import TECH_DOCS
    from deepchoice.utils.candidate_identity import mapping_key_for

    for candidate in ("ASP.NET Core", "SvelteKit", "Vue", "Koa", "dbt", "pgvector",
                      "React Native", "Text Generation Inference"):
        keys = mapping_key_for([candidate], TECH_DOCS)
        assert keys, f"no curated docs root resolves for {candidate}"
        for key in keys:
            assert TECH_DOCS[key]["url"].startswith("https://")
