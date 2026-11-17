"""Deployment and CI must agree on the Python version.

The Dockerfile pinned Python 3.13 while CI tested 3.12, so an image could ship a
runtime no test job ever exercised. The image is aligned to 3.12; 3.13 is
validated in the CI matrix first and stays experimental until it has been green
for a while. The image deliberately does not follow the matrix.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _ci_text() -> str:
    return (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8")


def test_dockerfile_python_matches_ci_baseline():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.12-slim" in dockerfile
    assert "python:3.13" not in dockerfile
    assert '"3.12"' in _ci_text()


def test_ci_matrix_tests_both_supported_versions():
    ci = _ci_text()
    assert 'python-version: ["3.12", "3.13"]' in ci
    assert "fail-fast: false" in ci


def test_3_13_leg_is_experimental_until_observed():
    """3.13 failures must not gate a PR before dependency support is observed."""
    ci = _ci_text()
    assert "continue-on-error: ${{ matrix.python-version == '3.13' }}" in ci


def test_static_checks_run_once_not_per_version():
    ci = _ci_text()
    assert ci.count("pyflakes src/ tests/") == 1
    assert ci.count("vulture src/ vulture_whitelist.py") == 1
