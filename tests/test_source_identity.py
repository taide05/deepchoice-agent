"""Offline tests for curated source identity and catalog compatibility."""

import hashlib
import json
import subprocess
import sys

import pytest

from deepchoice.agents.source_evaluator import classify_source_type
from deepchoice.retrievers import official
from deepchoice.utils.official_catalog import (
    TECH_DOCS,
    is_catalog_official_url,
)


TECH_DOCS_HASH = "5bd5f76bd4a453ed1bf5878673db2bab9b5b383d6050290a86a7c6ec562b8544"


def test_catalog_is_exact_static_payload_and_legacy_entry_is_same_object():
    payload = json.dumps(TECH_DOCS, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert len(TECH_DOCS) == 96
    assert hashlib.sha256(payload.encode()).hexdigest() == TECH_DOCS_HASH
    assert official.TECH_DOCS is TECH_DOCS
    assert official.TECH_DOCS["react"] == TECH_DOCS["react"]


def test_sqlite_explicit_www_alias_is_official_but_file_copy_is_not():
    assert classify_source_type("https://www.sqlite.org/wal.html", "tavily") == "official_doc"
    assert classify_source_type("https://www.sqlite.org/wal.html", "chroma") == "official_doc"
    assert classify_source_type("file:///knowledge/www.sqlite.org/wal.html", "chroma") == "tech_blog"


def test_platform_families_require_hostname_boundaries_and_take_priority():
    assert classify_source_type("https://arxiv.org/abs/2401.1234", "unknown") == "arxiv_paper"
    assert classify_source_type("https://export.arxiv.org/abs/2401.1234", "unknown") == "arxiv_paper"
    assert classify_source_type("https://github.com/org/repo", "unknown") == "github"
    assert classify_source_type("https://docs.github.com/en/actions", "official") == "github"
    assert classify_source_type("https://github.com.evil/repo", "unknown") == "tech_blog"
    assert classify_source_type("https://evilgithub.com/repo", "unknown") == "tech_blog"
    assert classify_source_type("https://stackexchange.com/questions/1", "unknown") == "stackoverflow"
    assert classify_source_type("https://reddit.com/r/python", "unknown") == "reddit"


def test_catalog_path_prefix_is_segment_bounded_and_case_sensitive():
    assert is_catalog_official_url("https://www.postgresql.org/docs/current/")
    assert is_catalog_official_url("https://www.postgresql.org/docs?view=current")
    assert not is_catalog_official_url("https://www.postgresql.org/documentation/current/")
    assert not is_catalog_official_url("https://www.postgresql.org/DOCS/current/")
    assert is_catalog_official_url("https://docs.python.org/3/reference/?q=docs.python.org")
    assert not is_catalog_official_url("https://docs.python.org/3.12evil/")


def test_malformed_urls_and_encoded_or_dot_segments_fail_closed():
    rejected = (
        "https://user@docs.python.org/3/",
        "https://docs.python.org:8080/3/",
        "https://docs.python.org:not-a-port/3/",
        "https://docs.python.org/3/%2e%2e/private",
        "https://huggingface.co/docs/transformers/../../evil",
        "https://docs.python.org\\@github.com/3/",
        "https://example.org/?next=github.com",
    )
    assert all(classify_source_type(url, "official") == "tech_blog" for url in rejected)


def test_unregistered_docs_readthedocs_and_source_labels_do_not_prove_officiality():
    assert classify_source_type("https://project.readthedocs.io/en/latest/", "unknown") == "tech_blog"
    assert classify_source_type("https://docs.unregistered.example/guide", "unknown") == "tech_blog"
    assert classify_source_type("https://unknown.example/official", "official") == "tech_blog"
    assert classify_source_type("some-internal-id", "official") == "tech_blog"
    assert classify_source_type("https://docs.python.org/3/", "chroma") == "official_doc"


def test_catalog_import_does_not_initialize_retrievers_llm_or_chroma():
    subprocess.run(
        [sys.executable, "-c", "import sys; import deepchoice.agents.source_evaluator; "
         "assert 'deepchoice.retrievers' not in sys.modules; "
         "assert 'deepchoice.utils.llm' not in sys.modules; "
         "assert 'chromadb' not in sys.modules"],
        check=True, capture_output=True, text=True, timeout=20,
    )


@pytest.mark.parametrize("url", [
    "https://example.org/path/github.com/file",
    "https://example.org/path/docs.python.org/3/",
    "https://example.org/?next=docs.python.org/3/",
    "https://github.com@evil.example/project",
    "https://www.docs.python.org/3/",
    "https://github.com../project",
    "https://docs.python.org/3/\x7fguide",
    "https://" + "a" * 254 + "/",
])
def test_locator_words_and_unregistered_aliases_never_grant_identity(url):
    assert classify_source_type(url, "official") == "tech_blog"


@pytest.mark.parametrize("prefix", [
    "https://huggingface.co/docs/transformers",
    "https://microsoft.github.io/autogen",
    "https://learn.microsoft.com/semantic-kernel",
])
def test_multitenant_catalog_does_not_upgrade_unregistered_paths(prefix):
    assert is_catalog_official_url(prefix + "/guide")
    assert not is_catalog_official_url(prefix + "-other/guide")
    assert not is_catalog_official_url(prefix + "/../other")
    assert not is_catalog_official_url(prefix + "/%2f../other")
    assert not is_catalog_official_url(prefix + "/%252e%252e/other")


def test_hostname_normalization_is_not_an_automatic_alias_or_path_normalizer():
    assert classify_source_type("https://WWW.SQLITE.ORG./wal.html", "tavily") == "official_doc"
    assert classify_source_type("https://www.docs.python.org/3/", "official") == "tech_blog"
    assert classify_source_type("https://github.com/org/a%20file", "github") == "github"
    assert classify_source_type("https://github.com/org/../repo", "github") == "github"
    assert not is_catalog_official_url("https://docs.python.org/3/a%20file")
