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


def test_docker_job_is_required_after_first_green_build():
    """The image build was experimental until the first green CI build.

    The first green build was run 44212336183 on 2026-11-18, so a broken image
    must now fail the workflow instead of being tolerated.
    """
    ci = _ci_text()
    assert "continue-on-error: true" not in ci
    assert "docker build -t deepchoice:ci ." in ci


def test_ci_uses_node24_actions_and_a_pinned_runner():
    """GitHub deprecated Node 20 in the pinned actions; ubuntu-latest is migrating.

    Both are non-blocking annotations today but will become failures/behaviour
    changes, so CI pins the Node 24 action releases and an explicit runner image.
    """
    ci = _ci_text()
    assert ci.count("actions/checkout@v7") == 3
    assert ci.count("actions/setup-python@v7") == 2
    assert "actions/checkout@v4" not in ci
    assert "actions/setup-python@v5" not in ci
    assert ci.count("runs-on: ubuntu-24.04") == 3
    assert "runs-on: ubuntu-latest" not in ci
