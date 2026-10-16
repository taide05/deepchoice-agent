"""Executed frontend probe: does the reading view number a body-less source?

Drives the real frontend/app.py via Streamlit AppTest with a faked backend.
APP path comes from env DC_APP_PATH so the same probe can be pointed at the
24e4b75 and 1b4a4cb versions of the file for a before/after.
"""
import json
import os
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

import httpx
from streamlit.testing.v1 import AppTest

APP_PATH = os.environ["DC_APP_PATH"]

NAV_URL = "https://www.postgresql.org/docs/"
NAV_TITLE = "PostgreSQL — Official Documentation"
REAL_URL = "https://www.postgresql.org/docs/release-17"
REAL_TITLE = "PostgreSQL 17 release notes"

SNAP = {
    "task": {"query": "pgvector on RDS", "candidate_techs": ["PostgreSQL"]},
    "evidence_chains": [{
        "conclusion": "c1", "evidence_strength": "moderate", "disputed": False,
        "sources": [
            {"title": NAV_TITLE, "url": NAV_URL, "snippet": "", "has_body": False, "score": 6.8},
            {"title": REAL_TITLE, "url": REAL_URL, "snippet": "vacuum improvements",
             "has_body": True, "score": 7.5},
        ],
    }],
    "conflicts": [],
    "confidence": "medium",
    "source_scores": [
        {"title": REAL_TITLE, "url": REAL_URL, "total_score": 7.5,
         "scores": {"authority": 10, "timeliness": 5, "verifiability": 8}},
        {"title": NAV_TITLE, "url": NAV_URL, "has_body": False, "total_score": 6.8,
         "scores": {"authority": 10, "timeliness": 5, "verifiability": 6}},
    ],
    "search_results": [],
    "partial_failures": [],
    "token_usage": [],
}

# Registry the server would produce: only the fact-bearing source is numbered.
ANNOTATED = {
    "report": ('<span id="sec-1"></span>\n# R\n\n'
               'See %s<sup><a class="cite" href="#ev-1">[1]</a></sup>.' % REAL_TITLE),
    "toc": [{"id": "sec-1", "level": 1, "text": "R"}],
    "citations": [{"n": 1, "url": REAL_URL, "title": REAL_TITLE, "chain_idx": 0}],
}


class _Resp:
    def __init__(self, payload, status_code=200, content=None):
        self.status_code = status_code
        self._payload = payload
        self.content = content

    def json(self):
        return self._payload


class _Stream:
    def __init__(self, events):
        self._events = events

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self):
        def ev(node, phase, ts):
            return f"data: {json.dumps({'node': node, 'update': {}, 'phase': phase, 'ts': ts})}"
        return iter([ev(*e) for e in self._events])


class _Backend:
    def get(self, url, **kw):
        if url.endswith("/snapshot"):
            return _Resp(SNAP)
        if url.endswith("/annotated"):
            return _Resp(ANNOTATED)
        if "/export" in url:
            return _Resp({"detail": "not installed"}, status_code=501)
        if url.endswith("/status"):
            return _Resp({"status": "complete"})
        return _Resp({"status": "started"})

    def post(self, url, **kw):
        return _Resp({"task_id": "t1", "status": "started"})

    def stream(self, method, url, **kw):
        return _Stream([])


def _run(monkeypatch):
    b = _Backend()
    monkeypatch.setattr(httpx, "get", b.get)
    monkeypatch.setattr(httpx, "post", b.post)
    monkeypatch.setattr(httpx, "stream", b.stream)
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    at.session_state["phase"] = "research"
    at.session_state["clarified_data"] = {"clarified_task": {"query": "q"}, "sub_questions": []}
    at.session_state["research_started"] = True
    at.session_state["research_running"] = False
    at.session_state["research_complete"] = True
    at.session_state["research_task_id"] = "t1"
    at.run()
    assert not at.exception, at.exception
    return "\n".join(str(m.value) for m in at.markdown)


def test_probe(monkeypatch):
    md = _run(monkeypatch)
    print("PROBE_APP", APP_PATH)
    print("PROBE_card_contains_nav_href",
          f'href="{NAV_URL}"' in md and f'[1] <a href="{NAV_URL}"' in md)
    i = md.find(f'href="{NAV_URL}"')
    print("PROBE_excerpt", repr(md[max(0, i - 60):i + 90]) if i >= 0 else "<absent>")
    print("PROBE_card_numbered_lines_for_nav",
          [ln.strip() for ln in md.splitlines() if f'href="{NAV_URL}"' in ln
           and ln.strip().startswith("[")])
    print("PROBE_real_source_line_present", f'href="{REAL_URL}"' in md)
    # tab2 source ratings: is the body-less source still presented with a score?
    print("PROBE_source_ratings_shows_nav_title", NAV_TITLE in md)
    print("PROBE_evidence_card_count", md.count('evidence-anchor" id="ev-'))
