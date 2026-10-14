"""Durable-route coverage for the annotated reading view and the report export.

The retired ``GET /research/{task_id}/annotated`` and ``GET /research/{task_id}/export``
compatibility routes are re-pointed here at their durable equivalents,
``GET /api/v1/tasks/{task_id}/annotated`` and ``GET /api/v1/tasks/{task_id}/export``.
Every check dimension of the former suite is preserved -- the format matrix, the
sanitization boundary, content-type/attachment headers, 400 on an unsupported
format, ``report_format`` override behaviour, and missing/absent-result behaviour.

The durable path differs from the retired one in ways this file asserts explicitly
rather than papering over:

* Results are read from the product database (``run_results``) through
  ``_get_durable_result``, not through a monkeypatched ``load_snapshot`` (which no
  longer exists). A task/run therefore has to be driven to a published terminal
  result with ``acquire_run_lease`` + ``finalize_run_with_result``, so these tests
  exercise the real durable read path.
* The annotated response is a plain dict carrying ``schema_version`` and ``run_id``
  in addition to the ``task_id``/``format``/``report``/``report_html``/``toc``/
  ``citations`` fields the retired route also returned.
* Asking for the format the run already stored returns ``result.report`` verbatim;
  ``FORMAT_RENDERERS`` is only consulted when the requested format differs from
  ``result.report_format``. The sanitization case is therefore driven by overriding
  a *different* format than the one the stored result carries -- the same
  renderer-output-into-``report_html`` boundary, reached through the durable branch
  that actually calls a renderer.
* ``report_format`` is frozen into the run result and must equal the task request's
  ``report_format``, so the "stored format used when the param is absent" case is
  set up by creating the task with that format instead of editing a snapshot.
* A genuinely unknown task is still 404, but an existing task with no published
  result is a 409 ``TASK_RESULT_NOT_READY`` (still running) or
  ``TASK_RESULT_UNAVAILABLE`` (terminal without a result). The retired suite folded
  both into one 404; both halves are asserted here, so the dimension is widened
  rather than dropped.

No assertion dimension from the retired suite had to be skipped.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from deepchoice.persistence.records import RunResultRecord
from deepchoice.server import app as app_module

QUERY = "FastAPI vs Flask for REST API"

BASE_CHAINS = [
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
]

# Markdown links are what inject_citations rewrites into <a class="cite"> anchors,
# and the headings are what build_toc rewrites into <span id="sec-N"> anchors.
BASE_REPORT = (
    f"# {QUERY}\n"
    "\n"
    "## Conclusion\n"
    "\n"
    "FastAPI wins on async throughput [Benchmark Post](https://example.com/bench).\n"
    "\n"
    "## Supporting Evidence Chain\n"
    "\n"
    "Flask simpler for small apps [Flask Docs](https://flask.palletsprojects.com/).\n"
)

CREATED_AT = datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC)


def _snapshot(*, report, report_format="what_why_how", chains=None, extra=None):
    snapshot = {
        "task": {"query": QUERY, "report_format": report_format},
        "evidence_chains": BASE_CHAINS if chains is None else chains,
        "conflicts": [],
        "final_recommendation": {"winner": "FastAPI", "winner_rationale": "async support"},
        "confidence": "high",
        "report": report,
    }
    if extra:
        snapshot.update(extra)
    return snapshot


def _result(run_id, *, report=BASE_REPORT, report_format="what_why_how", chains=None, extra=None):
    return RunResultRecord(
        run_id=run_id,
        snapshot=_snapshot(
            report=report, report_format=report_format, chains=chains, extra=extra
        ),
        report=report,
        report_format=report_format,
        created_at=CREATED_AT,
    )


@pytest.fixture
def durable_client(tmp_path: Path):
    """A TestClient bound to throwaway product/checkpoint databases."""

    state = app_module.app.state
    missing = object()
    names = (
        "execution_enabled",
        "checkpoint_database_path",
        "product_database_path",
        "legacy_snapshot_root",
    )
    old = {name: getattr(state, name, missing) for name in names}
    state.execution_enabled = False
    state.checkpoint_database_path = tmp_path / "checkpoints.db"
    state.product_database_path = tmp_path / "product.db"
    state.legacy_snapshot_root = tmp_path / "legacy"
    try:
        with TestClient(app_module.app) as client:
            yield client
    finally:
        for name, value in old.items():
            if value is missing:
                delattr(state, name)
            else:
                setattr(state, name, value)


@pytest.fixture
def completed(durable_client):
    """Create a task/run, publish a real durable result, return (task_id, run_id)."""

    def _make(*, report=BASE_REPORT, report_format="what_why_how", chains=None, extra=None):
        created = durable_client.post(
            "/api/v1/tasks", json={"query": QUERY, "report_format": report_format}
        ).json()
        task_id = created["task"]["task_id"]
        run_id = created["latest_run"]["run_id"]
        repository = app_module.app.state.task_repository

        async def finalize():
            grant = await repository.acquire_run_lease(
                run_id,
                lease_owner="worker",
                lease_ttl=timedelta(seconds=30),
                run_timeout=timedelta(minutes=5),
            )
            return await repository.finalize_run_with_result(
                run_id,
                _result(
                    run_id,
                    report=report,
                    report_format=report_format,
                    chains=chains,
                    extra=extra,
                ),
                lease_owner="worker",
                execution_epoch=grant.execution_epoch,
            )

        durable_client.portal.call(finalize)
        return task_id, run_id

    return _make


class TestAnnotatedEndpoint:
    def test_returns_annotated_report_toc_and_citations(self, durable_client, completed):
        task_id, run_id = completed()
        resp = durable_client.get(
            f"/api/v1/tasks/{task_id}/annotated", params={"format": "what_why_how"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["schema_version"] == 1
        assert data["task_id"] == task_id
        assert data["run_id"] == run_id
        assert data["format"] == "what_why_how"
        assert isinstance(data["report"], str)
        assert data["report"]  # non-empty markdown
        assert isinstance(data["report_html"], str)
        assert data["report_html"]
        assert isinstance(data["toc"], list) and data["toc"]
        assert any(t["text"] for t in data["toc"])
        assert isinstance(data["citations"], list)
        assert {c["n"] for c in data["citations"]} == {1, 2}

    def test_citations_injected_into_report(self, durable_client, completed):
        task_id, _ = completed()
        resp = durable_client.get(
            f"/api/v1/tasks/{task_id}/annotated", params={"format": "what_why_how"}
        )
        report = resp.json()["report"]
        assert '<a class="cite" href="#ev-1">[1]</a>' in report
        assert 'href="#ev-2"' in report

    def test_historical_citations_are_projected_as_unknown(self, durable_client, completed):
        task_id, _ = completed()
        citations = durable_client.get(
            f"/api/v1/tasks/{task_id}/annotated", params={"format": "what_why_how"}
        ).json()["citations"]
        assert all(citation["verification_status"] == "unknown" for citation in citations)
        assert all(citation["verification_reason"] == "not_checked" for citation in citations)
        assert all(isinstance(citation["source_idx"], int) for citation in citations)

    def test_annotated_citations_include_canonical_status_and_reason(
        self, durable_client, completed
    ):
        chains = [
            {
                "conclusion": "FastAPI wins on async throughput",
                "evidence_strength": "strong",
                "disputed": False,
                "sources": [
                    {
                        "title": "Benchmark Post",
                        "url": "https://EXAMPLE.com/bench#result",
                        "canonical_url": "https://example.com/bench",
                        "verification_status": "unsupported",
                        "verification_reason": "numeric_mismatch",
                        "score": 8,
                    }
                ],
            }
        ]
        extra = {
            "citation_verification": {
                "status_counts": {"verified": 0, "unsupported": 1, "unreachable": 0, "unknown": 0}
            }
        }
        task_id, _ = completed(chains=chains, extra=extra)
        citation = durable_client.get(
            f"/api/v1/tasks/{task_id}/annotated", params={"format": "what_why_how"}
        ).json()["citations"][0]
        assert citation["url"] == "https://example.com/bench"
        assert citation["canonical_url"] == "https://example.com/bench"
        assert citation["verification_status"] == "unsupported"
        assert citation["verification_reason"] == "numeric_mismatch"
        assert citation["source_idx"] == 0

    def test_toc_anchors_injected(self, durable_client, completed):
        task_id, _ = completed()
        resp = durable_client.get(
            f"/api/v1/tasks/{task_id}/annotated", params={"format": "what_why_how"}
        )
        report = resp.json()["report"]
        assert '<span id="sec-1"></span>' in report

    def test_html_view_is_sanitized_without_changing_markdown_contract(
        self, durable_client, completed, monkeypatch
    ):
        # The stored result carries what_why_how, so the renderer branch is only
        # reached by asking for a different format.
        task_id, _ = completed()
        monkeypatch.setitem(
            app_module.FORMAT_RENDERERS,
            "evidence_first",
            lambda _snapshot: (
                '# Safe <img src=x onerror="alert(1)">\n'
                '[bad](javascript:alert(2)) <script>alert(3)</script>'
            ),
        )
        data = durable_client.get(
            f"/api/v1/tasks/{task_id}/annotated", params={"format": "evidence_first"}
        ).json()
        assert data["format"] == "evidence_first"
        assert "<script>" in data["report"]
        assert "<script" not in data["report_html"].lower()
        assert "onerror" not in data["report_html"].lower()
        assert "javascript:" not in data["report_html"].lower()

    def test_404_on_missing_task(self, durable_client):
        resp = durable_client.get("/api/v1/tasks/annotated-export-missing/annotated")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "TASK_NOT_FOUND"

    def test_absent_result_is_conflict_not_404(self, durable_client):
        task_id = durable_client.post("/api/v1/tasks", json={"query": QUERY}).json()["task"][
            "task_id"
        ]

        not_ready = durable_client.get(f"/api/v1/tasks/{task_id}/annotated")
        assert not_ready.status_code == 409
        assert not_ready.json()["error"]["code"] == "TASK_RESULT_NOT_READY"
        assert not_ready.json()["error"]["retryable"] is True

        assert durable_client.post(f"/api/v1/tasks/{task_id}/cancel").status_code == 200
        unavailable = durable_client.get(f"/api/v1/tasks/{task_id}/annotated")
        assert unavailable.status_code == 409
        assert unavailable.json()["error"]["code"] == "TASK_RESULT_UNAVAILABLE"
        assert unavailable.json()["error"]["retryable"] is False


class TestExportEndpoint:
    def test_md_export_returns_attachment(self, durable_client, completed):
        task_id, _ = completed()
        resp = durable_client.get(f"/api/v1/tasks/{task_id}/export", params={"format": "md"})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        assert 'attachment; filename="deepchoice-report-' in resp.headers["content-disposition"]
        assert (
            resp.headers["content-disposition"]
            == f'attachment; filename="deepchoice-report-{task_id}.md"'
        )
        assert resp.text == BASE_REPORT
        assert "FastAPI wins on async throughput" in resp.text

    def test_pdf_export_returns_pdf_bytes(self, durable_client, completed):
        task_id, _ = completed()
        resp = durable_client.get(f"/api/v1/tasks/{task_id}/export", params={"format": "pdf"})
        if resp.status_code == 501:
            pytest.skip("xhtml2pdf not installed in this environment")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/pdf")
        assert (
            resp.headers["content-disposition"]
            == f'attachment; filename="deepchoice-report-{task_id}.pdf"'
        )
        assert resp.content.startswith(b"%PDF")

    def test_unsupported_format_400(self, durable_client, completed):
        task_id, _ = completed()
        resp = durable_client.get(f"/api/v1/tasks/{task_id}/export", params={"format": "docx"})
        assert resp.status_code == 400
        assert "Unsupported format" in resp.json()["detail"]

    def test_report_format_param_controls_renderer(self, durable_client, completed):
        """Regression (final review): exported content must match the on-screen
        format, not silently fall back to what_why_how."""
        task_id, _ = completed()

        resp = durable_client.get(
            f"/api/v1/tasks/{task_id}/export",
            params={"format": "md", "report_format": "evidence_first"},
        )
        assert resp.status_code == 200
        assert "Evidence Brief" in resp.text

        resp = durable_client.get(
            f"/api/v1/tasks/{task_id}/export",
            params={"format": "md", "report_format": "comparison_matrix"},
        )
        assert resp.status_code == 200
        assert "5-Dimension Comparison Matrix" in resp.text

    def test_stored_report_format_used_when_param_absent(self, durable_client, completed):
        # A run result's report_format must match its task request, so the stored
        # format is selected by creating the task with it.
        stored = app_module.FORMAT_RENDERERS["evidence_first"](
            _snapshot(report="", report_format="evidence_first")
        )
        assert "Evidence Brief" in stored
        assert "Evidence Brief" not in app_module.FORMAT_RENDERERS["what_why_how"](
            _snapshot(report="", report_format="evidence_first")
        )
        task_id, _ = completed(report=stored, report_format="evidence_first")

        resp = durable_client.get(f"/api/v1/tasks/{task_id}/export", params={"format": "md"})
        assert resp.status_code == 200
        assert "Evidence Brief" in resp.text
        assert resp.text == stored

    def test_404_on_missing_task(self, durable_client):
        resp = durable_client.get(
            "/api/v1/tasks/annotated-export-missing/export", params={"format": "md"}
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "TASK_NOT_FOUND"

    def test_absent_result_is_conflict_not_404(self, durable_client):
        task_id = durable_client.post("/api/v1/tasks", json={"query": QUERY}).json()["task"][
            "task_id"
        ]

        not_ready = durable_client.get(
            f"/api/v1/tasks/{task_id}/export", params={"format": "md"}
        )
        assert not_ready.status_code == 409
        assert not_ready.json()["error"]["code"] == "TASK_RESULT_NOT_READY"

        assert durable_client.post(f"/api/v1/tasks/{task_id}/cancel").status_code == 200
        unavailable = durable_client.get(
            f"/api/v1/tasks/{task_id}/export", params={"format": "md"}
        )
        assert unavailable.status_code == 409
        assert unavailable.json()["error"]["code"] == "TASK_RESULT_UNAVAILABLE"
