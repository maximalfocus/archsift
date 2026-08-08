"""Safe persistence for immutable content-addressed decision records."""

from __future__ import annotations

import os
import stat
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO

from archsift.decision_record import DecisionRecord, canonical_decision_record_bytes
from archsift.markdown_report import render_markdown_decision_report

_CHUNK_SIZE = 1024 * 1024


class RecordPersistenceFailure(StrEnum):
    """Stable failures at the decision-record output boundary."""

    WORKSPACE_UNAVAILABLE = "workspace-unavailable"
    OUTPUT_ROOT_UNSAFE = "output-root-unsafe"
    TARGET_UNSAFE = "target-unsafe"
    INTEGRITY_CONFLICT = "integrity-conflict"
    WRITE_FAILED = "write-failed"


class RecordPersistenceError(OSError):
    """A canonical decision record cannot be persisted safely."""

    def __init__(
        self,
        category: RecordPersistenceFailure,
        *,
        requirement: str,
        message: str,
        remediation: str,
    ) -> None:
        self.category = category
        self.field = "$.output"
        self.requirement = requirement
        self.message = message
        self.remediation = remediation
        super().__init__(message)

    def to_dict(self) -> dict[str, str]:
        """Return a stable path-free persistence diagnostic."""
        return {
            "category": self.category.value,
            "field": self.field,
            "message": self.message,
            "remediation": self.remediation,
            "requirement": self.requirement,
        }


@dataclass(frozen=True, slots=True)
class PersistedDecisionRecord:
    """One safely created or byte-identically reused record target."""

    relative_path: str
    reused: bool


@dataclass(frozen=True, slots=True)
class PersistedDecisionOutputs:
    """The canonical JSON source and deterministic Markdown review view."""

    json: PersistedDecisionRecord
    markdown: PersistedDecisionRecord


def _error(
    category: RecordPersistenceFailure,
    *,
    requirement: str,
    message: str,
    remediation: str,
) -> RecordPersistenceError:
    return RecordPersistenceError(
        category,
        requirement=requirement,
        message=message,
        remediation=remediation,
    )


def _resolve_output_root(workspace: Path) -> Path:
    try:
        workspace_root = workspace.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise _error(
            RecordPersistenceFailure.WORKSPACE_UNAVAILABLE,
            requirement="NFR-004",
            message="The case workspace cannot be resolved for decision-record output.",
            remediation="Provide an existing resolvable case-workspace directory.",
        ) from error
    if not workspace_root.is_dir():
        raise _error(
            RecordPersistenceFailure.WORKSPACE_UNAVAILABLE,
            requirement="NFR-004",
            message="The case workspace is not a directory.",
            remediation="Provide the directory containing the validated case workspace.",
        )
    try:
        output_root = (workspace_root / "output").resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise _error(
            RecordPersistenceFailure.OUTPUT_ROOT_UNSAFE,
            requirement="NFR-004",
            message="The decision-record output directory cannot be resolved safely.",
            remediation="Create a resolvable output directory inside the case workspace.",
        ) from error
    if not output_root.is_relative_to(workspace_root) or not output_root.is_dir():
        raise _error(
            RecordPersistenceFailure.OUTPUT_ROOT_UNSAFE,
            requirement="NFR-004",
            message="The decision-record output root escapes the workspace or is not a directory.",
            remediation="Use a real output directory contained by the case workspace.",
        )
    return output_root


def _target_name(record: DecisionRecord, extension: str = "json") -> str:
    identity = record.record_content_identity
    if (
        type(identity) is not str
        or len(identity) != 71
        or not identity.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in identity[7:])
    ):
        raise _error(
            RecordPersistenceFailure.TARGET_UNSAFE,
            requirement="FR-011",
            message="The decision record has no valid portable content identity.",
            remediation="Compose and validate the final decision record before persistence.",
        )
    if extension not in {"json", "md"}:
        raise _error(
            RecordPersistenceFailure.TARGET_UNSAFE,
            requirement="FR-011",
            message="The decision-record output format is unsupported.",
            remediation="Persist only the canonical JSON record or its Markdown review view.",
        )
    return f"sha256-{identity[7:]}.{extension}"


def _existing_target_matches(target: Path, output_root: Path, content: bytes) -> bool:
    """Return whether the existing derived target holds exactly the given bytes."""
    try:
        resolved = target.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise _error(
            RecordPersistenceFailure.TARGET_UNSAFE,
            requirement="NFR-004",
            message="The existing decision-record target cannot be resolved safely.",
            remediation="Remove the unsafe target without replacing another record.",
        ) from error
    if resolved != target or not resolved.is_relative_to(output_root):
        raise _error(
            RecordPersistenceFailure.TARGET_UNSAFE,
            requirement="NFR-004",
            message="The existing decision-record target is not a direct in-root file.",
            remediation="Remove links or aliases from the derived decision-record target.",
        )
    try:
        if not stat.S_ISREG(resolved.stat().st_mode):
            raise _error(
                RecordPersistenceFailure.TARGET_UNSAFE,
                requirement="NFR-004",
                message="The existing decision-record target is not a regular file.",
                remediation="Remove the non-regular derived target.",
            )
        with resolved.open("rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise _error(
                    RecordPersistenceFailure.TARGET_UNSAFE,
                    requirement="NFR-004",
                    message="The existing decision-record target is not a regular file.",
                    remediation="Remove the non-regular derived target.",
                )
            offset = 0
            while offset < len(content):
                chunk = stream.read(min(_CHUNK_SIZE, len(content) - offset))
                if not chunk or chunk != content[offset : offset + len(chunk)]:
                    return False
                offset += len(chunk)
            return stream.read(1) == b""
    except RecordPersistenceError:
        raise
    except OSError as error:
        raise _error(
            RecordPersistenceFailure.TARGET_UNSAFE,
            requirement="NFR-004",
            message="The existing decision-record target cannot be read safely.",
            remediation="Make the derived regular file readable or remove it.",
        ) from error


def _reuse_or_conflict(target: Path, output_root: Path, content: bytes) -> bool:
    if _existing_target_matches(target, output_root, content):
        return True
    raise _error(
        RecordPersistenceFailure.INTEGRITY_CONFLICT,
        requirement="FR-011",
        message="The content-addressed target already contains different bytes.",
        remediation="Preserve the existing file and investigate the integrity conflict.",
    )


def _opened_file_identity(stream: BinaryIO) -> tuple[int, int] | None:
    """Return the (device, inode) identity of the just-created open file.

    The identity later proves that a path still names the file created by this
    attempt before any cleanup deletes it. Filesystems without a usable file
    index report a zero inode, which is treated as unknown so cleanup fails
    closed instead of risking a concurrent replacement.
    """
    try:
        status = os.fstat(stream.fileno())
    except OSError:
        return None
    if status.st_ino == 0:
        return None
    return (status.st_dev, status.st_ino)


def _same_created_file(target: Path, identity: tuple[int, int] | None) -> bool:
    """Return whether the path still names the exact file opened this attempt."""
    if identity is None:
        return False
    try:
        status = target.stat()
    except OSError:
        return False
    return (status.st_dev, status.st_ino) == identity


def _unlink_created_file(target: Path, identity: tuple[int, int] | None) -> None:
    """Remove a file this attempt created, never a concurrent replacement."""
    if _same_created_file(target, identity):
        with suppress(OSError):
            target.unlink(missing_ok=True)


def _persist_content(
    output_root: Path,
    filename: str,
    content: bytes,
) -> tuple[PersistedDecisionRecord, tuple[int, int] | None]:
    """Create or byte-identically reuse one derived target.

    Returns the persistence result and, for a freshly created file, the opened
    file identity used to clean up only that exact file on any later failure.
    """
    target = output_root / filename
    if target.exists() or target.is_symlink():
        _reuse_or_conflict(target, output_root, content)
        return PersistedDecisionRecord(f"output/{filename}", True), None

    created_identity: tuple[int, int] | None = None
    created = False
    try:
        with target.open("xb") as stream:
            created = True
            created_identity = _opened_file_identity(stream)
            if stream.write(content) != len(content):
                raise OSError("incomplete decision-record write")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        _reuse_or_conflict(target, output_root, content)
        return PersistedDecisionRecord(f"output/{filename}", True), None
    except OSError as error:
        if created:
            _unlink_created_file(target, created_identity)
        raise _error(
            RecordPersistenceFailure.WRITE_FAILED,
            requirement="FR-011",
            message="A decision-record output could not be written completely.",
            remediation="Restore write access and retry without replacing an existing record.",
        ) from error
    return PersistedDecisionRecord(f"output/{filename}", False), created_identity


def persist_decision_record(
    workspace: Path,
    record: DecisionRecord,
    content: bytes,
) -> PersistedDecisionRecord:
    """Create or byte-identically reuse one derived in-workspace JSON record."""
    expected = canonical_decision_record_bytes(record)
    if type(content) is not bytes or content != expected:
        raise _error(
            RecordPersistenceFailure.INTEGRITY_CONFLICT,
            requirement="FR-011",
            message="Persistence content does not match the canonical decision record.",
            remediation="Persist only bytes produced from the same validated record.",
        )
    return _persist_content(_resolve_output_root(workspace), _target_name(record), content)[0]


def persist_decision_outputs(
    workspace: Path,
    record: DecisionRecord,
    json_content: bytes,
    markdown_content: bytes,
) -> PersistedDecisionOutputs:
    """Safely create or reuse the JSON record and its Markdown review view as one pair."""
    expected_json = canonical_decision_record_bytes(record)
    expected_markdown = render_markdown_decision_report(record)
    if type(json_content) is not bytes or json_content != expected_json:
        raise _error(
            RecordPersistenceFailure.INTEGRITY_CONFLICT,
            requirement="FR-011",
            message="Persistence content does not match the canonical decision record.",
            remediation="Persist only bytes produced from the same validated record.",
        )
    if type(markdown_content) is not bytes or markdown_content != expected_markdown:
        raise _error(
            RecordPersistenceFailure.INTEGRITY_CONFLICT,
            requirement="FR-011",
            message="Persistence content does not match the decision record's Markdown view.",
            remediation="Persist only Markdown bytes rendered from the same validated record.",
        )

    output_root = _resolve_output_root(workspace)
    json_name = _target_name(record, "json")
    markdown_name = _target_name(record, "md")
    expected = ((json_name, json_content), (markdown_name, markdown_content))

    # Detect every existing conflict before creating either missing half of the pair.
    for filename, content in expected:
        target = output_root / filename
        if target.exists() or target.is_symlink():
            _reuse_or_conflict(target, output_root, content)

    created: list[tuple[Path, tuple[int, int] | None]] = []
    try:
        persisted_json, json_identity = _persist_content(output_root, json_name, json_content)
        if not persisted_json.reused:
            created.append((output_root / json_name, json_identity))
        persisted_markdown, markdown_identity = _persist_content(
            output_root, markdown_name, markdown_content
        )
        if not persisted_markdown.reused:
            created.append((output_root / markdown_name, markdown_identity))
        for filename, content in expected:
            if not _existing_target_matches(output_root / filename, output_root, content):
                raise _error(
                    RecordPersistenceFailure.INTEGRITY_CONFLICT,
                    requirement="FR-011",
                    message="A persisted decision-record output failed byte verification.",
                    remediation="Preserve existing records and investigate the integrity conflict.",
                )
    except OSError:
        # Roll back only files this attempt created: a path that once named our
        # inode is not proof it still does, so an identity mismatch preserves
        # the concurrent replacement and fails the pair closed.
        for target, identity in created:
            _unlink_created_file(target, identity)
        raise

    return PersistedDecisionOutputs(persisted_json, persisted_markdown)
