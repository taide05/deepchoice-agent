from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

import benchmarks.product_optimization_seed as seed_module
from benchmarks.product_optimization_seed import (
    ADMISSION_POLICY_ID,
    ADMISSION_POLICY_VERSION,
    DEFAULT_MAX_FILE_BYTES,
    DEFAULT_MAX_SOURCES,
    DEFAULT_MAX_TOTAL_BYTES,
    EXPECTED_BUILDER_IDENTITY,
    EXPECTED_CHUNKING_IDENTITY,
    EXPECTED_COLLECTION_IDENTITY,
    EXPECTED_EMBEDDING_IDENTITY,
    EXPECTED_NORMALIZATION_IDENTITY,
    SCHEMA_VERSION,
    SeedAdmissionError,
    load_and_validate_seed_manifest,
    validate_seed_manifest,
)


def _source(path: str, content: bytes, *, stable_id: str, source_kind: str) -> dict[str, str]:
    return {
        "stable_id": stable_id,
        "path": path,
        "url": f"https://docs.example.org/{stable_id}",
        "source_kind": source_kind,
        "publisher": "Example Standards Body",
        "retrieved_at": "2026-09-23T08:30:00Z",
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "encoding": "utf-8",
    }


def _manifest(sources: list[dict[str, str]]) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "builder": dict(EXPECTED_BUILDER_IDENTITY),
        "normalization": dict(EXPECTED_NORMALIZATION_IDENTITY),
        "chunking": dict(EXPECTED_CHUNKING_IDENTITY),
        "embedding": dict(EXPECTED_EMBEDDING_IDENTITY),
        "collection": dict(EXPECTED_COLLECTION_IDENTITY),
        "sources": sources,
    }


def _write_source(root: Path, relative: str, content: bytes) -> None:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_validate_seed_manifest_returns_sorted_in_memory_records_and_frozen_hashes(tmp_path: Path) -> None:
    official = "A stable official reference.\n".encode()
    paper = "A peer-reviewed methods paper.\n".encode()
    _write_source(tmp_path, "official/zeta.txt", official)
    _write_source(tmp_path, "papers/alpha.md", paper)
    sources = [
        _source("official/zeta.txt", official, stable_id="zeta-official", source_kind="official"),
        _source("papers/alpha.md", paper, stable_id="alpha-paper", source_kind="paper"),
    ]

    admitted = validate_seed_manifest(_manifest(sources), tmp_path)
    reordered = validate_seed_manifest(_manifest(list(reversed(sources))), tmp_path)

    assert [record.stable_id for record in admitted.records] == ["alpha-paper", "zeta-official"]
    assert admitted.records[0].content == paper.decode()
    assert admitted.source_hashes == (
        ("alpha-paper", hashlib.sha256(paper).hexdigest()),
        ("zeta-official", hashlib.sha256(official).hexdigest()),
    )
    assert admitted.total_bytes == len(official) + len(paper)
    assert admitted.admission_policy_id == ADMISSION_POLICY_ID
    assert admitted.admission_policy_version == ADMISSION_POLICY_VERSION
    assert admitted.max_file_bytes == DEFAULT_MAX_FILE_BYTES
    assert admitted.max_total_bytes == DEFAULT_MAX_TOTAL_BYTES
    assert admitted.max_sources == DEFAULT_MAX_SOURCES
    assert admitted.manifest_sha256 == reordered.manifest_sha256
    assert admitted.admission_identity_sha256 == reordered.admission_identity_sha256
    assert len(admitted.manifest_sha256) == 64
    assert len(admitted.admission_identity_sha256) == 64
    expected_identity = {
        "manifest_sha256": admitted.manifest_sha256,
        "policy": {"id": ADMISSION_POLICY_ID, "version": ADMISSION_POLICY_VERSION},
        "effective_limits": {
            "max_file_bytes": DEFAULT_MAX_FILE_BYTES,
            "max_total_bytes": DEFAULT_MAX_TOTAL_BYTES,
            "max_sources": DEFAULT_MAX_SOURCES,
        },
        "identities": {
            "builder": dict(EXPECTED_BUILDER_IDENTITY),
            "normalization": dict(EXPECTED_NORMALIZATION_IDENTITY),
            "chunking": dict(EXPECTED_CHUNKING_IDENTITY),
            "embedding": dict(EXPECTED_EMBEDDING_IDENTITY),
            "collection": dict(EXPECTED_COLLECTION_IDENTITY),
        },
    }
    expected_bytes = json.dumps(
        expected_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert admitted.admission_identity_sha256 == hashlib.sha256(expected_bytes).hexdigest()


def test_load_manifest_accepts_bounded_strict_json(tmp_path: Path) -> None:
    content = b"Official deployment guidance."
    _write_source(tmp_path, "official/guide.txt", content)
    manifest = _manifest(
        [_source("official/guide.txt", content, stable_id="official-guide", source_kind="official")]
    )
    path = tmp_path / "seed-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    admitted = load_and_validate_seed_manifest(path, tmp_path)

    assert admitted.records[0].relative_path == "official/guide.txt"


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda manifest: manifest.update({"unexpected": True}), "invalid keys"),
        (lambda manifest: manifest.update({"schema_version": "old"}), "unsupported"),
        (lambda manifest: manifest["builder"].update({"prompt": "secret"}), "builder has invalid keys"),
        (lambda manifest: manifest["builder"].update({"version": "2"}), "policy identity"),
        (lambda manifest: manifest["normalization"].update({"version": "2"}), "policy identity"),
        (lambda manifest: manifest["chunking"].update({"id": "sentence-window"}), "policy identity"),
        (lambda manifest: manifest["embedding"].update({"revision": "0" * 40}), "policy identity"),
        (lambda manifest: manifest["collection"].update({"name": "other"}), "policy identity"),
        (lambda manifest: manifest["sources"][0].update({"extra": "value"}), "invalid keys"),
        (lambda manifest: manifest["sources"][0].update({"encoding": "utf-16"}), "must be utf-8"),
        (lambda manifest: manifest["sources"][0].update({"url": "http://docs.example.org/doc"}), "canonical HTTPS"),
        (lambda manifest: manifest["sources"][0].update({"url": "https://DOCS.example.org/doc"}), "canonical HTTPS"),
        (lambda manifest: manifest["sources"][0].update({"retrieved_at": "2026-09-23"}), "UTC"),
    ],
)
def test_manifest_schema_is_strict(tmp_path: Path, mutation, match: str) -> None:
    content = b"An official source."
    _write_source(tmp_path, "official/doc.txt", content)
    manifest = _manifest(
        [_source("official/doc.txt", content, stable_id="official-doc", source_kind="official")]
    )
    mutation(manifest)

    with pytest.raises(SeedAdmissionError, match=match):
        validate_seed_manifest(manifest, tmp_path)


@pytest.mark.parametrize(
    ("path", "source_kind", "match"),
    [
        ("../official/doc.txt", "official", "safe relative"),
        ("C:/official/doc.txt", "official", "safe relative"),
        ("official\\doc.txt", "official", "portable relative"),
        ("official//doc.txt", "official", "safe relative"),
        ("official/doc.txt:stream", "official", "safe relative"),
        ("blogs/doc.txt", "official", "prohibited directory"),
        ("benchmarks/doc.txt", "official", "prohibited directory"),
        ("outputs/doc.txt", "official", "prohibited directory"),
        ("papers/doc.txt", "official", "must be under official"),
        ("official/doc.txt", "paper", "must be under papers"),
    ],
)
def test_source_paths_are_confined_to_kind_specific_roots(
    tmp_path: Path, path: str, source_kind: str, match: str
) -> None:
    content = b"Safe source content."
    manifest = _manifest([_source(path, content, stable_id="source-one", source_kind=source_kind)])

    with pytest.raises(SeedAdmissionError, match=match):
        validate_seed_manifest(manifest, tmp_path)


def test_source_symlink_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "target.txt"
    target.write_bytes(b"outside")
    (tmp_path / "official").mkdir()
    link = tmp_path / "official" / "linked.txt"
    try:
        link.symlink_to(target)
    except (AttributeError, NotImplementedError, OSError):
        # Some Windows accounts cannot create symlinks.  Retain the negative
        # assertion with a controlled reparse detector instead of skipping the
        # security boundary altogether.
        link.write_bytes(b"outside")
        real_detector = seed_module._is_reparse_or_symlink
        monkeypatch.setattr(
            seed_module,
            "_is_reparse_or_symlink",
            lambda path: path == link or real_detector(path),
        )
    manifest = _manifest(
        [_source("official/linked.txt", b"outside", stable_id="linked-source", source_kind="official")]
    )

    with pytest.raises(SeedAdmissionError, match="symlink or reparse"):
        validate_seed_manifest(manifest, tmp_path)


def test_directories_and_empty_files_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "official" / "folder").mkdir(parents=True)
    directory_manifest = _manifest(
        [_source("official/folder", b"", stable_id="directory-source", source_kind="official")]
    )
    with pytest.raises(SeedAdmissionError, match="not a regular file"):
        validate_seed_manifest(directory_manifest, tmp_path)

    _write_source(tmp_path, "official/empty.txt", b"")
    empty_manifest = _manifest(
        [_source("official/empty.txt", b"", stable_id="empty-source", source_kind="official")]
    )
    with pytest.raises(SeedAdmissionError, match="file is empty"):
        validate_seed_manifest(empty_manifest, tmp_path)


def test_hash_utf8_and_byte_limits_fail_closed_without_body_in_error(tmp_path: Path) -> None:
    secret = "PRIVATE-BODY-SENTINEL"
    content = secret.encode()
    _write_source(tmp_path, "official/doc.txt", content)
    source = _source("official/doc.txt", content, stable_id="official-doc", source_kind="official")
    source["content_sha256"] = "0" * 64
    with pytest.raises(SeedAdmissionError) as hash_error:
        validate_seed_manifest(_manifest([source]), tmp_path)
    assert secret not in str(hash_error.value)

    invalid_utf8 = b"\xff\xfe"
    _write_source(tmp_path, "official/doc.txt", invalid_utf8)
    source = _source("official/doc.txt", invalid_utf8, stable_id="official-doc", source_kind="official")
    with pytest.raises(SeedAdmissionError, match="strict UTF-8"):
        validate_seed_manifest(_manifest([source]), tmp_path)

    oversized = b"abcd"
    _write_source(tmp_path, "official/doc.txt", oversized)
    source = _source("official/doc.txt", oversized, stable_id="official-doc", source_kind="official")
    with pytest.raises(SeedAdmissionError, match="per-file byte limit"):
        validate_seed_manifest(_manifest([source]), tmp_path, max_file_bytes=3)


def _exception_representations(error: BaseException) -> list[str]:
    representations: list[str] = []
    pending: list[BaseException] = [error]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        representations.append(repr(current))
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return representations


def test_source_body_is_absent_from_repr_and_utf8_exception_chain(tmp_path: Path) -> None:
    sentinel = "PRIVATE-BODY-SENTINEL"
    safe = sentinel.encode()
    _write_source(tmp_path, "official/safe.txt", safe)
    admitted = validate_seed_manifest(
        _manifest([_source("official/safe.txt", safe, stable_id="safe-source", source_kind="official")]),
        tmp_path,
    )
    assert sentinel not in repr(admitted.records[0])
    assert sentinel not in repr(admitted)

    invalid = sentinel.encode() + b"\xff"
    _write_source(tmp_path, "official/invalid.txt", invalid)
    manifest = _manifest(
        [_source("official/invalid.txt", invalid, stable_id="invalid-source", source_kind="official")]
    )
    with pytest.raises(SeedAdmissionError, match="strict UTF-8") as captured:
        validate_seed_manifest(manifest, tmp_path)
    assert not captured.value.__suppress_context__
    assert all(sentinel not in item for item in _exception_representations(captured.value))


@pytest.mark.parametrize(
    "payload",
    [
        b'{"private":"PRIVATE-MANIFEST-SENTINEL" broken',
        b'{"private":"PRIVATE-MANIFEST-SENTINEL\xff"}',
    ],
)
def test_manifest_parse_failures_do_not_retain_payload_in_exception_chain(
    tmp_path: Path, payload: bytes
) -> None:
    path = tmp_path / "manifest.json"
    path.write_bytes(payload)

    with pytest.raises(SeedAdmissionError, match="strict-UTF-8 JSON") as captured:
        load_and_validate_seed_manifest(path, tmp_path)

    assert all(
        "PRIVATE-MANIFEST-SENTINEL" not in item
        for item in _exception_representations(captured.value)
    )


@pytest.mark.parametrize(
    ("argument", "value"),
    [
        ("max_file_bytes", DEFAULT_MAX_FILE_BYTES + 1),
        ("max_total_bytes", DEFAULT_MAX_TOTAL_BYTES + 1),
        ("max_sources", DEFAULT_MAX_SOURCES + 1),
    ],
)
def test_callers_cannot_widen_admission_policy_limits(
    tmp_path: Path, argument: str, value: int
) -> None:
    content = b"Official content."
    _write_source(tmp_path, "official/doc.txt", content)
    manifest = _manifest(
        [_source("official/doc.txt", content, stable_id="official-doc", source_kind="official")]
    )

    with pytest.raises(SeedAdmissionError, match="hard limit"):
        validate_seed_manifest(manifest, tmp_path, **{argument: value})


def test_tighter_effective_limits_are_bound_into_output(tmp_path: Path) -> None:
    content = b"Official content."
    _write_source(tmp_path, "official/doc.txt", content)
    manifest = _manifest(
        [_source("official/doc.txt", content, stable_id="official-doc", source_kind="official")]
    )

    admitted = validate_seed_manifest(
        manifest,
        tmp_path,
        max_file_bytes=100,
        max_total_bytes=200,
        max_sources=2,
    )

    assert (admitted.max_file_bytes, admitted.max_total_bytes, admitted.max_sources) == (100, 200, 2)

    differently_bounded = validate_seed_manifest(
        manifest,
        tmp_path,
        max_file_bytes=101,
        max_total_bytes=200,
        max_sources=2,
    )
    assert admitted.manifest_sha256 == differently_bounded.manifest_sha256
    assert admitted.admission_identity_sha256 != differently_bounded.admission_identity_sha256


def test_unhashable_source_kind_fails_with_admission_error(tmp_path: Path) -> None:
    content = b"Official content."
    _write_source(tmp_path, "official/doc.txt", content)
    source = _source("official/doc.txt", content, stable_id="official-doc", source_kind="official")
    source["source_kind"] = ["official"]  # type: ignore[assignment]

    with pytest.raises(SeedAdmissionError, match="official or paper"):
        validate_seed_manifest(_manifest([source]), tmp_path)


def test_hard_linked_source_is_rejected(tmp_path: Path) -> None:
    content = b"Official content."
    original = tmp_path / "official" / "original.txt"
    linked = tmp_path / "official" / "linked.txt"
    original.parent.mkdir()
    original.write_bytes(content)
    os.link(original, linked)
    manifest = _manifest(
        [_source("official/original.txt", content, stable_id="official-doc", source_kind="official")]
    )

    with pytest.raises(SeedAdmissionError, match="exactly one hard link"):
        validate_seed_manifest(manifest, tmp_path)


def test_total_limit_duplicate_id_and_duplicate_path_are_rejected(tmp_path: Path) -> None:
    first = b"first"
    second = b"second"
    _write_source(tmp_path, "official/first.txt", first)
    _write_source(tmp_path, "official/second.txt", second)
    source_one = _source("official/first.txt", first, stable_id="source-one", source_kind="official")
    source_two = _source("official/second.txt", second, stable_id="source-two", source_kind="official")
    with pytest.raises(SeedAdmissionError, match="total byte limit"):
        validate_seed_manifest(_manifest([source_one, source_two]), tmp_path, max_total_bytes=10)

    duplicate_id = dict(source_two, stable_id="source-one")
    with pytest.raises(SeedAdmissionError, match="stable_id is duplicated"):
        validate_seed_manifest(_manifest([source_one, duplicate_id]), tmp_path)

    duplicate_path = dict(source_two, path="official/first.txt", content_sha256=hashlib.sha256(first).hexdigest())
    with pytest.raises(SeedAdmissionError, match="path is duplicated"):
        validate_seed_manifest(_manifest([source_one, duplicate_path]), tmp_path)


@pytest.mark.parametrize(
    "content",
    [
        "Expected winner: Product A\nOrdinary prose.",
        "expected_winner: Product A\nOrdinary prose.",
        "Benchmark case: synthetic-1\nOrdinary prose.",
        "Ground truth: Product B\nOrdinary prose.",
        "Category: caching\nAnalysis: choose Product A.",
        "预期获胜者：产品甲\n普通文本。",
        "## **Expected winner**：Product A\nOrdinary prose.",
        "- __Ground truth__ — Product B\nOrdinary prose.",
        "### _Benchmark case_－synthetic-1\nOrdinary prose.",
        "## **Category**：caching\n### _Analysis_ — choose Product A.",
        "> **Expected winner:** Product A\nOrdinary prose.",
        "<strong>Expected winner:</strong> Product A\nOrdinary prose.",
        "> Category: caching\n> Analysis: choose Product A.",
        "<strong class=x>Expected winner:</strong> Product A",
        "<p><strong>Expected winner:</strong></p> Product A",
        "<strong>Expected winner&colon;</strong> Product A",
        "<b>Ground truth&#58;</b> Product B",
        "`Expected winner:` Product A",
        "<code>Expected winner:</code> Product A",
    ],
)
def test_explicit_benchmark_derived_markers_are_rejected(tmp_path: Path, content: str) -> None:
    payload = content.encode("utf-8")
    _write_source(tmp_path, "papers/paper.txt", payload)
    manifest = _manifest(
        [_source("papers/paper.txt", payload, stable_id="paper-source", source_kind="paper")]
    )

    with pytest.raises(SeedAdmissionError, match="prohibited benchmark-derived marker") as error:
        validate_seed_manifest(manifest, tmp_path)
    assert content not in str(error.value)


def test_category_or_analysis_alone_is_not_treated_as_the_derived_template(tmp_path: Path) -> None:
    content = b"Analysis: this is a normal paper section without benchmark labels."
    _write_source(tmp_path, "papers/paper.txt", content)
    manifest = _manifest(
        [_source("papers/paper.txt", content, stable_id="paper-source", source_kind="paper")]
    )

    admitted = validate_seed_manifest(manifest, tmp_path)

    assert admitted.records[0].content.startswith("Analysis:")


@pytest.mark.parametrize(
    "content",
    [
        "> This paper compares expected winners without a template label.",
        "<strong>Analysis:</strong> a normal standalone section.",
        "The <strong>expected winner</strong> varies with workload.",
        "<p class=summary><strong>Analysis</strong> of expected winners.</p>",
        "Use `expected winner` as an ordinary field name without a colon.",
    ],
)
def test_marker_normalization_preserves_non_template_prose(tmp_path: Path, content: str) -> None:
    payload = content.encode("utf-8")
    _write_source(tmp_path, "papers/paper.txt", payload)
    manifest = _manifest(
        [_source("papers/paper.txt", payload, stable_id="paper-source", source_kind="paper")]
    )

    admitted = validate_seed_manifest(manifest, tmp_path)

    assert admitted.records[0].content == content


def test_manifest_loader_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"schema_version":"one","schema_version":"two"}', encoding="utf-8")

    with pytest.raises(SeedAdmissionError, match="duplicate object keys"):
        load_and_validate_seed_manifest(manifest_path, tmp_path)
