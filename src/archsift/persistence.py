"""Safe persistence for immutable content-addressed decision records."""

from __future__ import annotations

import os
import stat
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from archsift.decision_record import DecisionRecord, canonical_decision_record_bytes


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


def _target_name(record: DecisionRecord) -> str:
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
    return f"sha256-{identity[7:]}.json"


def _existing_target_bytes(target: Path, output_root: Path) -> bytes:
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
            return stream.read()
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
    if _existing_target_bytes(target, output_root) == content:
        return True
    raise _error(
        RecordPersistenceFailure.INTEGRITY_CONFLICT,
        requirement="FR-011",
        message="The content-addressed target already contains different bytes.",
        remediation="Preserve the existing file and investigate the integrity conflict.",
    )


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
    output_root = _resolve_output_root(workspace)
    filename = _target_name(record)
    target = output_root / filename
    if target.exists() or target.is_symlink():
        reused = _reuse_or_conflict(target, output_root, content)
        return PersistedDecisionRecord(f"output/{filename}", reused)

    created = False
    try:
        with target.open("xb") as stream:
            created = True
            if stream.write(content) != len(content):
                raise OSError("incomplete decision-record write")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        reused = _reuse_or_conflict(target, output_root, content)
        return PersistedDecisionRecord(f"output/{filename}", reused)
    except OSError as error:
        if created:
            with suppress(OSError):
                target.unlink(missing_ok=True)
        raise _error(
            RecordPersistenceFailure.WRITE_FAILED,
            requirement="FR-011",
            message="The canonical decision record could not be written completely.",
            remediation="Restore write access and retry without replacing an existing record.",
        ) from error
    return PersistedDecisionRecord(f"output/{filename}", False)
