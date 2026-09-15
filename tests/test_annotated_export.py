"""Tests for /annotated and /export endpoints (reading view + report download)."""
import pytest
from fastapi.testclient import TestClient

import deepchoice.server.app as app_module

client = TestClient(app_module.app)

TASK_ID = "annotated_export_test"

SNAPSHOT = {
    "task": {"query": "FastAPI vs Flask for REST API", "report_format": "what_why_how"},
    "evidence_chains": [
        {
            "conclusion": "FastAPI wins on async throughput",
            "evidence_strength": "strong",
            "disputed": False,
            "sources": [
                {"title": "Benchmark Post", "url": "https://example.com/bench", "score": 8},
            ],
        },
        {
            "conclusion": "Flask simpler for small apps",
            "evidence_strength": "moderate",
            "disputed": False,
            "sources": [
                {"title": "Flask Docs", "url": "https://flask.palletsprojects.com/", "score": 7},
            ],
        },
    ],
    "conflicts": [],
    "final_recommendation": {"winner": "FastAPI", "winner_rationale": "async support"},
    "confidence": "high",
}


@pytest.fixture(autouse=True)
def _seed_snapshot(monkeypatch):
    monkeypatch.setattr(app_module, "load_snapshot", lambda _: dict(SNAPSHOT))
    yield


class TestAnnotatedEndpoint:
    def test_returns_annotated_report_toc_and_citations(self):
        resp = client.get(f"/research/{TASK_ID}/annotated", params={"format": "what_why_how"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == TASK_ID
        assert data["format"] == "what_why_how"
        assert isinstance(data["report"], str)
        assert data["report"]  # non-empty markdown
        assert isinstance(data["report_html"], str)
        assert data["report_html"]
        assert isinstance(data["toc"], list) and data["toc"]
        assert any(t["text"] for t in data["toc"])
        assert isinstance(data["citations"], list)
        assert {c["n"] for c in data["citations"]} == {1, 2}

    def test_citations_injected_into_report(self):
        resp = client.get(f"/research/{TASK_ID}/annotated", params={"format": "what_why_how"})
        report = resp.json()["report"]
        assert '<a class="cite" href="#ev-1">[1]</a>' in report
        assert 'href="#ev-2"' in report

    def test_historical_citations_are_projected_as_unknown(self):
        citations = client.get(
            f"/research/{TASK_ID}/annotated", params={"format": "what_why_how"}
        ).json()["citations"]
        assert all(citation["verification_status"] == "unknown" for citation in citations)
        assert all(citation["verification_reason"] == "not_checked" for citation in citations)
        assert all(isinstance(citation["source_idx"], int) for citation in citations)

    def test_annotated_citations_include_canonical_status_and_reason(self, monkeypatch):
        snapshot = {
            **SNAPSHOT,
            "evidence_chains": [{
                **SNAPSHOT["evidence_chains"][0],
                "sources": [{
                    "title": "Benchmark Post",
                    "url": "https://EXAMPLE.com/bench#result",
                    "canonical_url": "https://example.com/bench",
                    "verification_status": "unsupported",
                    "verification_reason": "numeric_mismatch",
                    "score": 8,
                }],
            }],
            "citation_verification": {
                "status_counts": {"verified": 0, "unsupported": 1, "unreachable": 0, "unknown": 0}
            },
        }
        monkeypatch.setattr(app_module, "load_snapshot", lambda _: snapshot)
        citation = client.get(
            f"/research/{TASK_ID}/annotated", params={"format": "what_why_how"}
        ).json()["citations"][0]
        assert citation["url"] == "https://example.com/bench"
        assert citation["canonical_url"] == "https://example.com/bench"
        assert citation["verification_status"] == "unsupported"
        assert citation["verification_reason"] == "numeric_mismatch"
        assert citation["source_idx"] == 0

    def test_toc_anchors_injected(self):
        resp = client.get(f"/research/{TASK_ID}/annotated", params={"format": "what_why_how"})
        report = resp.json()["report"]
        assert '<span id="sec-1"></span>' in report

    def test_html_view_is_sanitized_without_changing_markdown_contract(self, monkeypatch):
        monkeypatch.setitem(
            app_module.FORMAT_RENDERERS,
            "what_why_how",
            lambda _snapshot: (
                '# Safe <img src=x onerror="alert(1)">\n'
                '[bad](javascript:alert(2)) <script>alert(3)</script>'
            ),
        )
        data = client.get(
            f"/research/{TASK_ID}/annotated", params={"format": "what_why_how"}
        ).json()
        assert "<script>" in data["report"]
        assert "<script" not in data["report_html"].lower()
        assert "onerror" not in data["report_html"].lower()
        assert "javascript:" not in data["report_html"].lower()

    def test_404_on_missing_task(self, monkeypatch):
        monkeypatch.setattr(app_module, "load_snapshot", lambda _: None)
        resp = client.get(f"/research/{TASK_ID}/annotated")
        assert resp.status_code == 404


class TestExportEndpoint:
    def test_md_export_returns_attachment(self):
        resp = client.get(f"/research/{TASK_ID}/export", params={"format": "md"})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        assert 'attachment; filename="deepchoice-report-' in resp.headers["content-disposition"]
        assert "FastAPI wins on async throughput" in resp.text

    def test_pdf_export_returns_pdf_bytes(self):
        resp = client.get(f"/research/{TASK_ID}/export", params={"format": "pdf"})
        if resp.status_code == 501:
            pytest.skip("xhtml2pdf not installed in this environment")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/pdf")
        assert resp.content.startswith(b"%PDF")

    def test_unsupported_format_400(self):
        resp = client.get(f"/research/{TASK_ID}/export", params={"format": "docx"})
        assert resp.status_code == 400

    def test_report_format_param_controls_renderer(self):
        """Regression (final review): exported content must match the on-screen
        format, not silently fall back to what_why_how."""
        resp = client.get(
            f"/research/{TASK_ID}/export",
            params={"format": "md", "report_format": "evidence_first"},
        )
        assert resp.status_code == 200
        assert "Evidence Brief" in resp.text

        resp = client.get(
            f"/research/{TASK_ID}/export",
            params={"format": "md", "report_format": "comparison_matrix"},
        )
        assert resp.status_code == 200
        assert "5-Dimension Comparison Matrix" in resp.text

    def test_stored_report_format_used_when_param_absent(self, monkeypatch):
        snap = dict(SNAPSHOT)
        snap["task"] = {**SNAPSHOT["task"], "report_format": "evidence_first"}
        monkeypatch.setattr(app_module, "load_snapshot", lambda _: snap)
        resp = client.get(f"/research/{TASK_ID}/export", params={"format": "md"})
        assert resp.status_code == 200
        assert "Evidence Brief" in resp.text

    def test_404_on_missing_task(self, monkeypatch):
        monkeypatch.setattr(app_module, "load_snapshot", lambda _: None)
        resp = client.get(f"/research/{TASK_ID}/export", params={"format": "md"})
        assert resp.status_code == 404
