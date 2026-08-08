"""Safe deterministic content identities for explicitly referenced evidence artefacts."""

from __future__ import annotations

import stat
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from os import fstat
from pathlib import Path
from typing import BinaryIO

from archsift.canonical import canonical_dossier_dict
from archsift.validation import Dossier, EvidenceArtefactReference, EvidenceArtefactRoot

_CHUNK_SIZE = 1024 * 1024


class EvidenceArtefactFailure(StrEnum):
    """Stable failure categories at the evidence-artefact filesystem boundary."""

    DUPLICATE_REFERENCE = "duplicate-reference"
    REFERENCE_PATH_INVALID = "reference-path-invalid"
    WORKSPACE_ROOT_UNAVAILABLE = "workspace-root-unavailable"
    EVIDENCE_ROOT_UNSAFE = "evidence-root-unsafe"
    EXTERNAL_ROOT_REQUIRED = "external-root-required"
    EXTERNAL_ROOT_UNAVAILABLE = "external-root-unavailable"
    TARGET_MISSING = "target-missing"
    TARGET_UNRESOLVABLE = "target-unresolvable"
    TARGET_OUTSIDE_ROOT = "target-outside-root"
    TARGET_NOT_REGULAR = "target-not-regular"
    TARGET_UNREADABLE = "target-unreadable"


@dataclass(frozen=True, slots=True)
class EvidenceArtefactIdentity:
    """Immutable identity of one explicitly authorised evidence file."""

    evidence_id: str
    artefact_id: str
    root: EvidenceArtefactRoot
    path: str
    byte_length: int
    content_identity: str

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible representation without host paths."""
        return {
            "artefact_id": self.artefact_id,
            "byte_length": self.byte_length,
            "content_identity": self.content_identity,
            "evidence_id": self.evidence_id,
            "path": self.path,
            "root": self.root.value,
        }


class EvidenceArtefactError(ValueError):
    """A referenced evidence artefact cannot be identified safely."""

    def __init__(
        self,
        category: EvidenceArtefactFailure,
        *,
        field: str,
        requirement: str,
        message: str,
        remediation: str,
    ) -> None:
        self.category = category
        self.field = field
        self.requirement = requirement
        self.message = message
        self.remediation = remediation
        super().__init__(message)

    def to_dict(self) -> dict[str, str]:
        """Return a stable diagnostic without authored values or absolute paths."""
        return {
            "category": self.category.value,
            "field": self.field,
            "message": self.message,
            "remediation": self.remediation,
            "requirement": self.requirement,
        }


@dataclass(frozen=True, slots=True)
class _PendingArtefact:
    evidence_index: int
    artefact_index: int
    evidence_id: str
    reference: EvidenceArtefactReference

    @property
    def id_field(self) -> str:
        return f"$.evidence[{self.evidence_index}].artefacts[{self.artefact_index}].id"

    @property
    def root_field(self) -> str:
        return f"$.evidence[{self.evidence_index}].artefacts[{self.artefact_index}].root"

    @property
    def path_field(self) -> str:
        return f"$.evidence[{self.evidence_index}].artefacts[{self.artefact_index}].path"


def _error(
    category: EvidenceArtefactFailure,
    *,
    field: str,
    requirement: str,
    message: str,
    remediation: str,
) -> EvidenceArtefactError:
    return EvidenceArtefactError(
        category,
        field=field,
        requirement=requirement,
        message=message,
        remediation=remediation,
    )


def _validate_reference_path(pending: _PendingArtefact) -> None:
    path = pending.reference.path
    segments = path.split("/")
    if (
        path.startswith("/")
        or "\\" in path
        or ":" in path
        or "" in segments
        or "." in segments
        or ".." in segments
        or any(segment.endswith((" ", ".")) for segment in segments)
        or any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in path)
    ):
        raise _error(
            EvidenceArtefactFailure.REFERENCE_PATH_INVALID,
            field=pending.path_field,
            requirement="NFR-004",
            message="The evidence artefact reference is not a safe relative POSIX path.",
            remediation="Use non-empty POSIX segments beneath the selected authorised root.",
        )


def _resolve_workspace_evidence_root(workspace: Path, field: str) -> Path:
    try:
        workspace_root = workspace.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise _error(
            EvidenceArtefactFailure.WORKSPACE_ROOT_UNAVAILABLE,
            field=field,
            requirement="NFR-004",
            message="The case workspace cannot be resolved to an authorised directory.",
            remediation="Provide an existing resolvable case-workspace directory.",
        ) from error
    if not workspace_root.is_dir():
        raise _error(
            EvidenceArtefactFailure.WORKSPACE_ROOT_UNAVAILABLE,
            field=field,
            requirement="NFR-004",
            message="The case workspace is not an authorised directory.",
            remediation="Provide the directory containing the case workspace.",
        )

    try:
        evidence_root = (workspace_root / "evidence").resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise _error(
            EvidenceArtefactFailure.EVIDENCE_ROOT_UNSAFE,
            field=field,
            requirement="NFR-004",
            message="The workspace evidence root cannot be resolved safely.",
            remediation="Create a resolvable evidence directory inside the case workspace.",
        ) from error
    if not evidence_root.is_relative_to(workspace_root) or not evidence_root.is_dir():
        raise _error(
            EvidenceArtefactFailure.EVIDENCE_ROOT_UNSAFE,
            field=field,
            requirement="NFR-004",
            message=(
                "The workspace evidence root is outside its authorised boundary or is not "
                "a directory."
            ),
            remediation="Use a real evidence directory contained by the case workspace.",
        )
    return evidence_root


def _resolve_external_root(external_root: Path | None, field: str) -> Path:
    if external_root is None:
        raise _error(
            EvidenceArtefactFailure.EXTERNAL_ROOT_REQUIRED,
            field=field,
            requirement="NFR-004",
            message="An external artefact requires an explicitly supplied external root.",
            remediation="Supply the authorised external evidence root outside the dossier.",
        )
    try:
        resolved = external_root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise _error(
            EvidenceArtefactFailure.EXTERNAL_ROOT_UNAVAILABLE,
            field=field,
            requirement="NFR-004",
            message="The supplied external evidence root cannot be resolved safely.",
            remediation="Supply an existing resolvable external evidence directory.",
        ) from error
    if not resolved.is_dir():
        raise _error(
            EvidenceArtefactFailure.EXTERNAL_ROOT_UNAVAILABLE,
            field=field,
            requirement="NFR-004",
            message="The supplied external evidence root is not a directory.",
            remediation="Supply an external evidence directory rather than a file.",
        )
    return resolved


def _resolve_target(root: Path, pending: _PendingArtefact) -> Path:
    candidate = root.joinpath(*pending.reference.path.split("/"))
    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError) as error:
        raise _error(
            EvidenceArtefactFailure.TARGET_MISSING,
            field=pending.path_field,
            requirement="FR-011",
            message="The referenced evidence artefact does not exist.",
            remediation="Add the referenced regular file or correct the authored relative path.",
        ) from error
    except (OSError, RuntimeError) as error:
        raise _error(
            EvidenceArtefactFailure.TARGET_UNRESOLVABLE,
            field=pending.path_field,
            requirement="NFR-004",
            message="The referenced evidence artefact cannot be resolved safely.",
            remediation="Remove unsafe links and provide a resolvable regular file.",
        ) from error
    if not resolved.is_relative_to(root):
        raise _error(
            EvidenceArtefactFailure.TARGET_OUTSIDE_ROOT,
            field=pending.path_field,
            requirement="NFR-004",
            message="The referenced evidence artefact resolves outside its authorised root.",
            remediation="Reference a regular file contained by the selected authorised root.",
        )
    try:
        mode = resolved.stat().st_mode
    except OSError as error:
        raise _error(
            EvidenceArtefactFailure.TARGET_UNRESOLVABLE,
            field=pending.path_field,
            requirement="NFR-004",
            message="The referenced evidence artefact cannot be inspected safely.",
            remediation="Provide a resolvable regular file inside the authorised root.",
        ) from error
    if not stat.S_ISREG(mode):
        raise _error(
            EvidenceArtefactFailure.TARGET_NOT_REGULAR,
            field=pending.path_field,
            requirement="NFR-004",
            message="The referenced evidence artefact is not a regular file.",
            remediation="Reference a regular file rather than a directory or special file.",
        )
    return resolved


def _hash_stream(stream: BinaryIO) -> tuple[int, str]:
    digest = sha256()
    byte_length = 0
    while chunk := stream.read(_CHUNK_SIZE):
        byte_length += len(chunk)
        digest.update(chunk)
    return byte_length, f"sha256:{digest.hexdigest()}"


def _identify(root: Path, pending: _PendingArtefact) -> EvidenceArtefactIdentity:
    resolved = _resolve_target(root, pending)
    try:
        with resolved.open("rb") as stream:
            if not stat.S_ISREG(fstat(stream.fileno()).st_mode):
                raise _error(
                    EvidenceArtefactFailure.TARGET_NOT_REGULAR,
                    field=pending.path_field,
                    requirement="NFR-004",
                    message="The referenced evidence artefact is not a regular file.",
                    remediation="Reference a regular file rather than a directory or special file.",
                )
            byte_length, content_identity = _hash_stream(stream)
    except EvidenceArtefactError:
        raise
    except OSError as error:
        raise _error(
            EvidenceArtefactFailure.TARGET_UNREADABLE,
            field=pending.path_field,
            requirement="FR-011",
            message="The referenced evidence artefact cannot be read.",
            remediation="Make the regular file readable or correct the authored reference.",
        ) from error
    return EvidenceArtefactIdentity(
        evidence_id=pending.evidence_id,
        artefact_id=pending.reference.id,
        root=pending.reference.root,
        path=pending.reference.path,
        byte_length=byte_length,
        content_identity=content_identity,
    )


def evidence_artefact_identities(
    dossier: Dossier,
    *,
    workspace: Path,
    external_root: Path | None = None,
) -> tuple[EvidenceArtefactIdentity, ...]:
    """Hash only explicit artefact references beneath caller-authorised roots."""
    canonical_dossier_dict(dossier)
    pending = tuple(
        _PendingArtefact(evidence_index, artefact_index, evidence.id, reference)
        for evidence_index, evidence in enumerate(dossier.evidence)
        for artefact_index, reference in enumerate(evidence.artefacts)
    )
    if not pending:
        return ()
    for item in pending:
        _validate_reference_path(item)

    ordered = tuple(
        sorted(
            pending,
            key=lambda item: (item.evidence_id, item.reference.id),
        )
    )
    seen: set[tuple[str, str]] = set()
    for item in ordered:
        key = (item.evidence_id, item.reference.id)
        if key in seen:
            raise _error(
                EvidenceArtefactFailure.DUPLICATE_REFERENCE,
                field=item.id_field,
                requirement="FR-011",
                message="An evidence and artefact ID pair is duplicated.",
                remediation="Use unique evidence IDs and artefact IDs before hashing.",
            )
        seen.add(key)

    workspace_root: Path | None = None
    authorised_external_root: Path | None = None
    identities: list[EvidenceArtefactIdentity] = []
    for item in ordered:
        if item.reference.root is EvidenceArtefactRoot.WORKSPACE:
            if workspace_root is None:
                workspace_root = _resolve_workspace_evidence_root(workspace, item.root_field)
            root = workspace_root
        else:
            if authorised_external_root is None:
                authorised_external_root = _resolve_external_root(external_root, item.root_field)
            root = authorised_external_root
        identities.append(_identify(root, item))
    return tuple(identities)
