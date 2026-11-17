"""Deployment and CI must agree on the Python version.

The Dockerfile pinned Python 3.13 while CI tested 3.12, so an image could ship a
runtime no test job ever exercised. The repair aligns the image to CI first; a 3.13
CI matrix is a separate change and must not be mixed into this alignment.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_dockerfile_python_matches_ci():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8")
    assert 'python-version: "3.12"' in ci
    assert "FROM python:3.12-slim" in dockerfile
    assert "python:3.13" not in dockerfile
