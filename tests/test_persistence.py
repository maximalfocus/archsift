from __future__ import annotations

import os
from pathlib import Path

import pytest

import archsift.persistence as persistence
from archsift.decision_record import canonical_decision_record_bytes, compose_decision_record
from archsift.markdown_report import render_markdown_decision_report
from archsift.persistence import (
    RecordPersistenceError,
    RecordPersistenceFailure,
    persist_decision_outputs,
    persist_decision_record,
)
from archsift.validation import CaseIdentity, Dossier


def _record():
    return compose_decision_record(
        Dossier(schema_version=1, case=CaseIdentity("persistence", "Synthetic persistence")),
        tool_version="0.1.0-test",
    )


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "case"
    (workspace / "output").mkdir(parents=True)
    return workspace


def _target(workspace: Path, identity: str, extension: str = "json") -> Path:
    return workspace / "output" / f"sha256-{identity[7:]}.{extension}"


def test_first_write_and_byte_identical_reuse_are_immutable(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    record = _record()
    content = canonical_decision_record_bytes(record)

    created = persist_decision_record(workspace, record, content)
    target = workspace / created.relative_path
    os.utime(target, (1_700_000_000, 1_700_000_000))
    before = target.stat()
    reused = persist_decision_record(workspace, record, content)
    after = target.stat()

    assert created.relative_path == f"output/sha256-{record.record_content_identity[7:]}.json"
    assert created.reused is False
    assert reused.relative_path == created.relative_path
    assert reused.reused is True
    assert target.read_bytes() == content
    assert after.st_mtime_ns == before.st_mtime_ns
    assert after.st_size == before.st_size


def test_paired_outputs_first_write_and_byte_identical_reuse_are_immutable(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    record = _record()
    json_content = canonical_decision_record_bytes(record)
    markdown_content = render_markdown_decision_report(record)

    created = persist_decision_outputs(workspace, record, json_content, markdown_content)
    targets = [workspace / created.json.relative_path, workspace / created.markdown.relative_path]
    for target in targets:
        os.utime(target, (1_700_000_000, 1_700_000_000))
    before = [target.stat().st_mtime_ns for target in targets]

    reused = persist_decision_outputs(workspace, record, json_content, markdown_content)

    assert created.json.relative_path.endswith(".json")
    assert created.markdown.relative_path.endswith(".md")
    assert created.json.reused is created.markdown.reused is False
    assert reused.json.reused is reused.markdown.reused is True
    assert [target.read_bytes() for target in targets] == [json_content, markdown_content]
    assert [target.stat().st_mtime_ns for target in targets] == before


def test_paired_outputs_add_missing_markdown_without_rewriting_landed_json(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    record = _record()
    json_content = canonical_decision_record_bytes(record)
    markdown_content = render_markdown_decision_report(record)
    persisted_json = persist_decision_record(workspace, record, json_content)
    json_target = workspace / persisted_json.relative_path
    os.utime(json_target, (1_700_000_000, 1_700_000_000))
    before = json_target.stat().st_mtime_ns

    outputs = persist_decision_outputs(workspace, record, json_content, markdown_content)

    assert outputs.json.reused is True
    assert outputs.markdown.reused is False
    assert json_target.stat().st_mtime_ns == before
    assert (workspace / outputs.markdown.relative_path).read_bytes() == markdown_content


def test_paired_preflight_conflict_creates_neither_missing_output(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    record = _record()
    json_target = _target(workspace, record.record_content_identity)
    markdown_target = _target(workspace, record.record_content_identity, "md")
    markdown_target.write_bytes(b"different")

    with pytest.raises(RecordPersistenceError) as captured:
        persist_decision_outputs(
            workspace,
            record,
            canonical_decision_record_bytes(record),
            render_markdown_decision_report(record),
        )

    assert captured.value.category is RecordPersistenceFailure.INTEGRITY_CONFLICT
    assert not json_target.exists()
    assert markdown_target.read_bytes() == b"different"


def test_paired_write_failure_removes_outputs_created_by_the_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    record = _record()
    json_target = _target(workspace, record.record_content_identity)
    markdown_target = _target(workspace, record.record_content_identity, "md")
    original_open = Path.open

    def failing_open(path: Path, *args: object, **kwargs: object):
        if path == markdown_target and args and args[0] == "xb":
            raise OSError("synthetic Markdown write failure")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)

    with pytest.raises(RecordPersistenceError) as captured:
        persist_decision_outputs(
            workspace,
            record,
            canonical_decision_record_bytes(record),
            render_markdown_decision_report(record),
        )

    assert captured.value.category is RecordPersistenceFailure.WRITE_FAILED
    assert not json_target.exists()
    assert not markdown_target.exists()


def test_paired_post_write_verification_failure_cleans_pair_and_stays_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    record = _record()
    json_content = canonical_decision_record_bytes(record)
    markdown_content = render_markdown_decision_report(record)
    json_target = _target(workspace, record.record_content_identity)
    markdown_target = _target(workspace, record.record_content_identity, "md")
    original_matches = persistence._existing_target_matches

    def failing_verification(target: Path, output_root: Path, content: bytes) -> bool:
        # Only the post-write verification reads the freshly created JSON target;
        # a False result simulates a pair that failed byte verification.
        if target == json_target:
            return False
        return original_matches(target, output_root, content)

    monkeypatch.setattr(persistence, "_existing_target_matches", failing_verification)

    with pytest.raises(RecordPersistenceError) as captured:
        persist_decision_outputs(workspace, record, json_content, markdown_content)

    assert captured.value.category is RecordPersistenceFailure.INTEGRITY_CONFLICT
    assert not json_target.exists()
    assert not markdown_target.exists()

    monkeypatch.undo()
    outputs = persist_decision_outputs(workspace, record, json_content, markdown_content)

    assert outputs.json.reused is False
    assert outputs.markdown.reused is False
    assert json_target.read_bytes() == json_content
    assert markdown_target.read_bytes() == markdown_content


def test_non_identical_content_address_collision_is_never_overwritten(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    record = _record()
    content = canonical_decision_record_bytes(record)
    target = _target(workspace, record.record_content_identity)
    target.write_bytes(b"different")

    with pytest.raises(RecordPersistenceError) as captured:
        persist_decision_record(workspace, record, content)

    assert captured.value.category is RecordPersistenceFailure.INTEGRITY_CONFLICT
    assert target.read_bytes() == b"different"


def test_target_with_trailing_bytes_is_an_exact_byte_conflict(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    record = _record()
    content = canonical_decision_record_bytes(record)
    target = _target(workspace, record.record_content_identity)
    target.write_bytes(content + b"trailing")

    with pytest.raises(RecordPersistenceError) as captured:
        persist_decision_record(workspace, record, content)

    assert captured.value.category is RecordPersistenceFailure.INTEGRITY_CONFLICT
    assert target.read_bytes() == content + b"trailing"


def test_non_regular_derived_target_is_refused_without_opening_it(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    record = _record()
    target = _target(workspace, record.record_content_identity)
    target.mkdir()

    with pytest.raises(RecordPersistenceError) as captured:
        persist_decision_record(workspace, record, canonical_decision_record_bytes(record))

    assert captured.value.category is RecordPersistenceFailure.TARGET_UNSAFE
    assert target.is_dir()


def test_supplied_bytes_must_match_the_same_canonical_record(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    record = _record()

    with pytest.raises(RecordPersistenceError) as captured:
        persist_decision_record(workspace, record, b"{}\n")

    assert captured.value.category is RecordPersistenceFailure.INTEGRITY_CONFLICT
    assert list((workspace / "output").iterdir()) == []


@pytest.mark.parametrize("shape", ["missing", "file"])
def test_output_root_must_be_an_existing_directory(tmp_path: Path, shape: str) -> None:
    workspace = tmp_path / "case"
    workspace.mkdir()
    if shape == "file":
        (workspace / "output").write_bytes(b"not a directory")
    record = _record()

    with pytest.raises(RecordPersistenceError) as captured:
        persist_decision_record(workspace, record, canonical_decision_record_bytes(record))

    assert captured.value.category is RecordPersistenceFailure.OUTPUT_ROOT_UNSAFE


@pytest.mark.skipif(os.name == "nt", reason="Windows may not permit unprivileged symlinks")
def test_output_root_and_existing_target_symlink_escapes_fail_closed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    escaped_workspace = tmp_path / "escaped"
    escaped_workspace.mkdir()
    (escaped_workspace / "output").symlink_to(outside, target_is_directory=True)
    record = _record()
    content = canonical_decision_record_bytes(record)

    with pytest.raises(RecordPersistenceError) as root_error:
        persist_decision_record(escaped_workspace, record, content)
    assert root_error.value.category is RecordPersistenceFailure.OUTPUT_ROOT_UNSAFE

    workspace = _workspace(tmp_path)
    outside_target = outside / "record.json"
    outside_target.write_bytes(content)
    _target(workspace, record.record_content_identity).symlink_to(outside_target)
    with pytest.raises(RecordPersistenceError) as target_error:
        persist_decision_record(workspace, record, content)
    assert target_error.value.category is RecordPersistenceFailure.TARGET_UNSAFE
    assert outside_target.read_bytes() == content


def test_write_failure_removes_partial_final_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    record = _record()
    content = canonical_decision_record_bytes(record)
    target = _target(workspace, record.record_content_identity)
    original_open = Path.open

    class FailingStream:
        def __init__(self, stream: object) -> None:
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()  # type: ignore[attr-defined]
            return self

        def __exit__(self, *args: object) -> object:
            return self.stream.__exit__(*args)  # type: ignore[attr-defined]

        def write(self, data: bytes) -> int:
            self.stream.write(data[:10])  # type: ignore[attr-defined]
            raise OSError("synthetic write failure")

        def flush(self) -> None:
            self.stream.flush()  # type: ignore[attr-defined]

        def fileno(self) -> int:
            return self.stream.fileno()  # type: ignore[attr-defined,no-any-return]

    def failing_open(path: Path, *args: object, **kwargs: object):
        stream = original_open(path, *args, **kwargs)
        if path == target and args and args[0] == "xb":
            return FailingStream(stream)
        return stream

    monkeypatch.setattr(Path, "open", failing_open)

    with pytest.raises(RecordPersistenceError) as captured:
        persist_decision_record(workspace, record, content)

    assert captured.value.category is RecordPersistenceFailure.WRITE_FAILED
    assert not target.exists()


def test_errors_are_stable_and_do_not_leak_host_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "private-host-location"
    record = _record()

    with pytest.raises(RecordPersistenceError) as captured:
        persist_decision_record(workspace, record, canonical_decision_record_bytes(record))

    payload = captured.value.to_dict()
    assert payload["field"] == "$.output"
    assert payload["requirement"] == "NFR-004"
    assert str(tmp_path) not in str(payload)
