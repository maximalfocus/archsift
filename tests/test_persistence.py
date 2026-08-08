from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from archsift.decision_record import canonical_decision_record_bytes, compose_decision_record
from archsift.persistence import (
    RecordPersistenceError,
    RecordPersistenceFailure,
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


def _target(workspace: Path, identity: str) -> Path:
    return workspace / "output" / f"sha256-{identity[7:]}.json"


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
    assert after.st_ctime_ns == before.st_ctime_ns
    assert after.st_size == before.st_size
    assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode)


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


def test_existing_target_replaced_between_check_and_open_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    record = _record()
    content = canonical_decision_record_bytes(record)
    target = _target(workspace, record.record_content_identity)
    target.write_bytes(content)
    original_open = Path.open

    def replacing_open(path: Path, *args: object, **kwargs: object):
        if path == target and args and args[0] == "rb":
            target.unlink()
            target.write_bytes(content)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", replacing_open)

    with pytest.raises(RecordPersistenceError) as captured:
        persist_decision_record(workspace, record, content)

    assert captured.value.category is RecordPersistenceFailure.TARGET_UNSAFE
    assert target.read_bytes() == content


@pytest.mark.skipif(os.name == "nt", reason="Windows may not permit unprivileged symlinks")
def test_existing_target_replaced_by_outside_symlink_between_check_and_open_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    record = _record()
    content = canonical_decision_record_bytes(record)
    target = _target(workspace, record.record_content_identity)
    target.write_bytes(content)
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "outside.bin"
    outside_file.write_bytes(content)
    original_open = Path.open

    def substituting_open(path: Path, *args: object, **kwargs: object):
        if path == target and args and args[0] == "rb":
            target.unlink()
            target.symlink_to(outside_file)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", substituting_open)

    with pytest.raises(RecordPersistenceError) as captured:
        persist_decision_record(workspace, record, content)

    assert captured.value.category is RecordPersistenceFailure.TARGET_UNSAFE
    assert target.is_symlink()
    assert outside_file.read_bytes() == content


def test_failed_write_cleanup_never_deletes_a_replaced_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    record = _record()
    content = canonical_decision_record_bytes(record)
    target = _target(workspace, record.record_content_identity)
    original_open = Path.open

    class ReplacingStream:
        def __init__(self, stream: object) -> None:
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()  # type: ignore[attr-defined]
            return self

        def __exit__(self, *args: object) -> object:
            self.stream.__exit__(*args)  # type: ignore[attr-defined]
            target.unlink(missing_ok=True)
            target.write_bytes(b"replacement")
            return None

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
            return ReplacingStream(stream)
        return stream

    monkeypatch.setattr(Path, "open", failing_open)

    with pytest.raises(RecordPersistenceError) as captured:
        persist_decision_record(workspace, record, content)

    assert captured.value.category is RecordPersistenceFailure.WRITE_FAILED
    assert target.read_bytes() == b"replacement"


@pytest.mark.skipif(os.name == "nt", reason="Windows may not permit unprivileged symlinks")
def test_created_record_redirected_outside_the_workspace_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    record = _record()
    content = canonical_decision_record_bytes(record)
    target = _target(workspace, record.record_content_identity)
    output = workspace / "output"
    outside = tmp_path / "outside"
    outside.mkdir()
    original_open = Path.open

    def redirecting_open(path: Path, *args: object, **kwargs: object):
        if path == target and args and args[0] == "xb":
            output.rmdir()
            output.symlink_to(outside, target_is_directory=True)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", redirecting_open)

    with pytest.raises(RecordPersistenceError) as captured:
        persist_decision_record(workspace, record, content)

    assert captured.value.category is RecordPersistenceFailure.WRITE_FAILED
    assert list(outside.iterdir()) == []


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
