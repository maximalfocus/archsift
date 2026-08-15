"""Inert, content-addressed registration of explicitly selected case material."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import BinaryIO, cast

from archsift.canonical import JsonObject, canonical_json_bytes

REGISTRATION_SCHEMA_VERSION = 1
_CHUNK_SIZE = 1024 * 1024
_REGISTRATION_ID = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?")
_DECLARED_TYPE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_/-]{0,127}")
_COMMIT_IDENTITY = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


class RegistrationKind(StrEnum):
    """Supported inert material registration shapes."""

    DOCUMENT = "document"
    REPOSITORY = "repository"


class RegistrationFailure(StrEnum):
    """Stable registration failure categories."""

    INVALID_INPUT = "invalid-input"
    ROOT_UNAVAILABLE = "root-unavailable"
    PATH_UNSAFE = "path-unsafe"
    TARGET_MISSING = "target-missing"
    TARGET_NOT_REGULAR = "target-not-regular"
    TARGET_UNREADABLE = "target-unreadable"
    TARGET_CHANGED = "target-changed"
    DUPLICATE_PATH = "duplicate-path"
    COLLISION = "collision"
    REGISTRATION_INVALID = "registration-invalid"
    PUBLISH_FAILED = "publish-failed"


class RegistrationError(ValueError):
    """Material could not be registered without weakening the safety contract."""

    def __init__(self, category: RegistrationFailure, field: str, message: str) -> None:
        self.category = category
        self.field = field
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class RegisteredFile:
    """One immutable file entry in a registration manifest."""

    logical_path: str | None
    content_identity: str
    byte_length: int
    stored_path: str

    def to_dict(self) -> JsonObject:
        return {
            "byte_length": self.byte_length,
            "content_identity": self.content_identity,
            "logical_path": self.logical_path,
            "stored_path": self.stored_path,
        }


@dataclass(frozen=True, slots=True)
class MaterialRegistration:
    """Canonical immutable registration manifest."""

    registration_schema_version: int
    registration_content_identity: str
    registration_id: str
    registration_kind: RegistrationKind
    declared_type: str
    repository_commit: str | None
    files: tuple[RegisteredFile, ...]

    def payload(self, *, include_identity: bool = True) -> JsonObject:
        payload: JsonObject = {
            "declared_type": self.declared_type,
            "files": [item.to_dict() for item in self.files],
            "registration_id": self.registration_id,
            "registration_kind": self.registration_kind.value,
            "registration_schema_version": self.registration_schema_version,
            "repository_commit": self.repository_commit,
        }
        if include_identity:
            payload["registration_content_identity"] = self.registration_content_identity
        return payload


def registration_manifest_path(workspace: Path, registration_id: str) -> Path:
    """Return the conventional manifest path without resolving caller-controlled links."""
    _validate_registration_id(registration_id)
    return workspace / "evidence" / "registered" / registration_id / "registration.json"


def _fail(category: RegistrationFailure, field: str, message: str) -> RegistrationError:
    return RegistrationError(category, field, message)


def _validate_registration_id(value: str) -> None:
    if _REGISTRATION_ID.fullmatch(value) is None:
        raise _fail(
            RegistrationFailure.INVALID_INPUT,
            "registration_id",
            "Registration ID must be a lowercase portable identifier of at most 64 characters.",
        )


def _validate_declared_type(value: str) -> None:
    if _DECLARED_TYPE.fullmatch(value) is None:
        raise _fail(
            RegistrationFailure.INVALID_INPUT,
            "declared_type",
            "Declared type must be a non-empty portable type label.",
        )


def _validate_relative_path(value: str, field: str) -> tuple[str, ...]:
    segments = value.split("/")
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or ":" in value
        or any(segment in {"", ".", ".."} for segment in segments)
        or any(segment.endswith((" ", ".")) for segment in segments)
        or any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value)
    ):
        raise _fail(
            RegistrationFailure.PATH_UNSAFE,
            field,
            "Material paths must be safe relative POSIX paths beneath the authorised root.",
        )
    return tuple(segments)


def _resolve_directory(path: Path, field: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise _fail(
            RegistrationFailure.ROOT_UNAVAILABLE,
            field,
            "The authorised material root is unavailable.",
        ) from error
    if not resolved.is_dir():
        raise _fail(
            RegistrationFailure.ROOT_UNAVAILABLE,
            field,
            "The authorised material root is not a directory.",
        )
    return resolved


def _require_private_store(path: Path) -> None:
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise _fail(
            RegistrationFailure.PATH_UNSAFE,
            "workspace.evidence.registered",
            "The private registration store grants group or other filesystem access.",
        )


def _reject_link_components(root: Path, segments: tuple[str, ...], field: str) -> Path:
    candidate = root
    try:
        for segment in segments:
            candidate = candidate / segment
            mode = candidate.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise _fail(
                    RegistrationFailure.PATH_UNSAFE,
                    field,
                    "Registered material paths cannot contain symbolic links.",
                )
    except RegistrationError:
        raise
    except (FileNotFoundError, NotADirectoryError) as error:
        raise _fail(
            RegistrationFailure.TARGET_MISSING,
            field,
            "The explicitly selected material file does not exist.",
        ) from error
    except OSError as error:
        raise _fail(
            RegistrationFailure.PATH_UNSAFE,
            field,
            "The explicitly selected material path cannot be inspected safely.",
        ) from error
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise _fail(
            RegistrationFailure.PATH_UNSAFE,
            field,
            "The explicitly selected material path cannot be resolved safely.",
        ) from error
    if not resolved.is_relative_to(root):
        raise _fail(
            RegistrationFailure.PATH_UNSAFE,
            field,
            "The explicitly selected material resolves outside the authorised root.",
        )
    return resolved


def _read_inert(
    source: Path,
    field: str,
    *,
    output: BinaryIO | None,
) -> tuple[int, str]:
    digest = sha256()
    byte_length = 0
    before = source.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        raise _fail(
            RegistrationFailure.TARGET_NOT_REGULAR,
            field,
            "Only regular files can be registered as inert material.",
        )
    with source.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(before, opened):
            raise _fail(
                RegistrationFailure.TARGET_CHANGED,
                field,
                "The selected file changed while registration began.",
            )
        while chunk := cast(BinaryIO, stream).read(_CHUNK_SIZE):
            if output is not None:
                output.write(chunk)
            digest.update(chunk)
            byte_length += len(chunk)
        after = os.fstat(stream.fileno())
    current = source.stat(follow_symlinks=False)
    generation_before = (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    generation_after = (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    generation_current = (current.st_size, current.st_mtime_ns, current.st_ctime_ns)
    if (
        not os.path.samestat(before, after)
        or not os.path.samestat(before, current)
        or generation_before != generation_after
        or generation_before != generation_current
        or byte_length != before.st_size
    ):
        raise _fail(
            RegistrationFailure.TARGET_CHANGED,
            field,
            "The selected file changed while it was being registered.",
        )
    return byte_length, f"sha256:{digest.hexdigest()}"


def _copy_inert(source: Path, destination: Path, field: str) -> tuple[int, str]:
    try:
        with destination.open("xb") as output:
            result = _read_inert(source, field, output=output)
            output.flush()
            os.fsync(output.fileno())
    except RegistrationError:
        raise
    except OSError as error:
        raise _fail(
            RegistrationFailure.TARGET_UNREADABLE,
            field,
            "The selected regular file could not be copied as inert bytes.",
        ) from error
    return result


def _hash_inert(source: Path, field: str) -> tuple[int, str]:
    try:
        return _read_inert(source, field, output=None)
    except RegistrationError:
        raise
    except OSError as error:
        raise _fail(
            RegistrationFailure.TARGET_UNREADABLE,
            field,
            "The registered regular file could not be verified as inert bytes.",
        ) from error


def _registration_identity(payload: JsonObject) -> str:
    return f"sha256:{sha256(canonical_json_bytes(payload)).hexdigest()}"


def _parse_manifest(content: bytes) -> MaterialRegistration:
    try:
        raw = json.loads(content.decode("utf-8"))
        if type(raw) is not dict or set(raw) != {
            "declared_type",
            "files",
            "registration_content_identity",
            "registration_id",
            "registration_kind",
            "registration_schema_version",
            "repository_commit",
        }:
            raise ValueError
        _validate_registration_id(raw["registration_id"])
        _validate_declared_type(raw["declared_type"])
        if raw["registration_schema_version"] != REGISTRATION_SCHEMA_VERSION:
            raise ValueError
        kind = RegistrationKind(raw["registration_kind"])
        commit = raw["repository_commit"]
        if (kind is RegistrationKind.DOCUMENT and commit is not None) or (
            kind is RegistrationKind.REPOSITORY
            and (type(commit) is not str or _COMMIT_IDENTITY.fullmatch(commit) is None)
        ):
            raise ValueError
        entries: list[RegisteredFile] = []
        if type(raw["files"]) is not list or not raw["files"]:
            raise ValueError
        for entry in raw["files"]:
            if type(entry) is not dict or set(entry) != {
                "byte_length",
                "content_identity",
                "logical_path",
                "stored_path",
            }:
                raise ValueError
            logical = entry["logical_path"]
            if logical is not None:
                if type(logical) is not str:
                    raise ValueError
                _validate_relative_path(logical, "logical_path")
            identity = entry["content_identity"]
            length = entry["byte_length"]
            stored = entry["stored_path"]
            if (
                type(identity) is not str
                or re.fullmatch(r"sha256:[0-9a-f]{64}", identity) is None
                or type(length) is not int
                or length < 0
                or type(stored) is not str
                or stored != f"blobs/{identity.replace(':', '-')}"
            ):
                raise ValueError
            entries.append(RegisteredFile(logical, identity, length, stored))
        registration = MaterialRegistration(
            REGISTRATION_SCHEMA_VERSION,
            raw["registration_content_identity"],
            raw["registration_id"],
            kind,
            raw["declared_type"],
            commit,
            tuple(entries),
        )
        if raw["registration_content_identity"] != _registration_identity(
            registration.payload(include_identity=False)
        ):
            raise ValueError
        if canonical_json_bytes(registration.payload()) != content:
            raise ValueError
        return registration
    except (KeyError, TypeError, UnicodeDecodeError, ValueError) as error:
        raise _fail(
            RegistrationFailure.REGISTRATION_INVALID,
            "registration",
            "The registration manifest is not a supported canonical registration.",
        ) from error


def load_registration(
    workspace: Path,
    registration_id: str,
    *,
    verify_blobs: bool = True,
) -> MaterialRegistration:
    """Load one registration and optionally verify every stored byte identity."""
    _validate_registration_id(registration_id)
    workspace_root = _resolve_directory(workspace, "workspace")
    evidence_root = _resolve_directory(workspace_root / "evidence", "workspace.evidence")
    if not evidence_root.is_relative_to(workspace_root):
        raise _fail(
            RegistrationFailure.PATH_UNSAFE,
            "workspace.evidence",
            "The workspace evidence directory escapes the case workspace.",
        )
    manifest = _reject_link_components(
        evidence_root,
        ("registered", registration_id, "registration.json"),
        "registration_id",
    )
    _require_private_store(manifest.parent.parent)
    try:
        registration = _parse_manifest(manifest.read_bytes())
    except RegistrationError:
        raise
    except OSError as error:
        raise _fail(
            RegistrationFailure.REGISTRATION_INVALID,
            "registration_id",
            "The named registration manifest is unavailable.",
        ) from error
    if registration.registration_id != registration_id:
        raise _fail(
            RegistrationFailure.REGISTRATION_INVALID,
            "registration_id",
            "The registration directory and manifest identities disagree.",
        )
    if verify_blobs:
        root = manifest.parent.resolve(strict=True)
        for index, item in enumerate(registration.files):
            path = _reject_link_components(
                root,
                tuple(item.stored_path.split("/")),
                f"files[{index}]",
            )
            length, identity = _hash_inert(path, f"files[{index}]")
            if length != item.byte_length or identity != item.content_identity:
                raise _fail(
                    RegistrationFailure.REGISTRATION_INVALID,
                    f"files[{index}]",
                    "Stored registration bytes do not match their declared identity.",
                )
    return registration


def _register(
    workspace: Path,
    registration_id: str,
    declared_type: str,
    kind: RegistrationKind,
    sources: tuple[tuple[str | None, str], ...],
    *,
    repository_commit: str | None,
    external_material_root: Path | None,
) -> MaterialRegistration:
    _validate_registration_id(registration_id)
    _validate_declared_type(declared_type)
    if kind is RegistrationKind.REPOSITORY:
        if repository_commit is None or _COMMIT_IDENTITY.fullmatch(repository_commit) is None:
            raise _fail(
                RegistrationFailure.INVALID_INPUT,
                "repository_commit",
                "Repository commit must be a full lowercase SHA-1 or SHA-256 object identity.",
            )
    elif repository_commit is not None:
        raise _fail(
            RegistrationFailure.INVALID_INPUT,
            "repository_commit",
            "Documents have no repository commit.",
        )
    workspace_root = _resolve_directory(workspace, "workspace")
    evidence = _resolve_directory(workspace_root / "evidence", "workspace.evidence")
    source_root = (
        _resolve_directory(external_material_root, "external_material_root")
        if external_material_root is not None
        else workspace_root
    )
    if source_root.is_relative_to(evidence / "registered"):
        raise _fail(
            RegistrationFailure.PATH_UNSAFE,
            "source",
            "The registration store cannot be used as a material source root.",
        )
    logicals = [logical for logical, _ in sources if logical is not None]
    if len(sources) == 0 or len(logicals) != len(set(logicals)):
        raise _fail(
            RegistrationFailure.DUPLICATE_PATH,
            "source",
            "Repository material paths must be non-empty and unique.",
        )

    registered_root = evidence / "registered"
    try:
        registered_root.mkdir(mode=0o700, exist_ok=True)
        if registered_root.is_symlink() or not registered_root.is_dir():
            raise OSError
        _require_private_store(registered_root)
        stage = Path(tempfile.mkdtemp(prefix=f".{registration_id}-", dir=registered_root))
        (stage / "blobs").mkdir(mode=0o700)
    except OSError as error:
        raise _fail(
            RegistrationFailure.PUBLISH_FAILED,
            "workspace",
            "The private registration staging area could not be created.",
        ) from error

    try:
        entries: list[RegisteredFile] = []
        for index, (logical, source_text) in enumerate(sources):
            field = f"sources[{index}]"
            segments = _validate_relative_path(source_text, field)
            if logical is not None:
                _validate_relative_path(logical, f"logical_paths[{index}]")
            source = _reject_link_components(source_root, segments, field)
            if source.is_relative_to(registered_root):
                raise _fail(
                    RegistrationFailure.PATH_UNSAFE,
                    field,
                    "Existing registration-store files cannot be registered as new sources.",
                )
            scratch = stage / "blobs" / f"pending-{index}"
            length, identity = _copy_inert(source, scratch, field)
            stored = f"blobs/{identity.replace(':', '-')}"
            final_blob = stage / stored
            if final_blob.exists():
                scratch.unlink()
            else:
                os.replace(scratch, final_blob)
            entries.append(RegisteredFile(logical, identity, length, stored))
        entries.sort(key=lambda item: (item.logical_path or "", item.content_identity))
        provisional = MaterialRegistration(
            REGISTRATION_SCHEMA_VERSION,
            "",
            registration_id,
            kind,
            declared_type,
            repository_commit,
            tuple(entries),
        )
        identity = _registration_identity(provisional.payload(include_identity=False))
        registration = MaterialRegistration(
            REGISTRATION_SCHEMA_VERSION,
            identity,
            registration_id,
            kind,
            declared_type,
            repository_commit,
            tuple(entries),
        )
        (stage / "registration.json").write_bytes(canonical_json_bytes(registration.payload()))
        target = registered_root / registration_id
        try:
            os.replace(stage, target)
        except OSError:
            if target.is_dir():
                existing = load_registration(workspace_root, registration_id)
                if existing == registration:
                    return existing
                raise _fail(
                    RegistrationFailure.COLLISION,
                    "registration_id",
                    "The registration ID already names different immutable material.",
                ) from None
            raise
        return registration
    except RegistrationError:
        raise
    except OSError as error:
        raise _fail(
            RegistrationFailure.PUBLISH_FAILED,
            "registration_id",
            "The registration could not be published atomically.",
        ) from error
    finally:
        if "stage" in locals() and stage.exists():
            for child in sorted(stage.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            stage.rmdir()


def register_document(
    workspace: Path,
    registration_id: str,
    declared_type: str,
    source: str,
    *,
    external_material_root: Path | None = None,
) -> MaterialRegistration:
    """Register one explicit file as uninterpreted document bytes."""
    return _register(
        workspace,
        registration_id,
        declared_type,
        RegistrationKind.DOCUMENT,
        ((None, source),),
        repository_commit=None,
        external_material_root=external_material_root,
    )


def register_repository(
    workspace: Path,
    registration_id: str,
    declared_type: str,
    repository_commit: str,
    files: tuple[str, ...],
    *,
    external_material_root: Path | None = None,
) -> MaterialRegistration:
    """Register explicit repository-relative files with caller-supplied commit provenance."""
    return _register(
        workspace,
        registration_id,
        declared_type,
        RegistrationKind.REPOSITORY,
        tuple((path, path) for path in files),
        repository_commit=repository_commit,
        external_material_root=external_material_root,
    )
