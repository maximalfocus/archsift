from __future__ import annotations

import os
import random
import socket
import time
from dataclasses import FrozenInstanceError, replace
from importlib import metadata
from pathlib import Path

import pytest
import yaml

from archsift.artefacts import (
    EvidenceArtefactError,
    EvidenceArtefactFailure,
    EvidenceArtefactIdentity,
    evidence_artefact_identities,
)
from archsift.canonical import canonical_evidence_bytes, evidence_content_identity
from archsift.diagnostics import ExitCode
from archsift.validation import (
    AssumptionEvidence,
    CaseIdentity,
    DecisionArea,
    Dossier,
    EvidenceArtefactReference,
    EvidenceArtefactRoot,
    ObservedEvidence,
    validate_workspace,
)


def _reference(
    identifier: str = "sample",
    *,
    root: str = "workspace",
    path: str = "sample.bin",
) -> dict[str, str]:
    return {"id": identifier, "root": root, "path": path}


def _entry(
    kind: str,
    identifier: str,
    *,
    artefacts: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "id": identifier,
        "kind": kind,
        "claim": f"Synthetic {kind} claim.",
        "owner": "Synthetic reviewer",
        "affects": ["problem-value"],
    }
    if artefacts is not None:
        entry["artefacts"] = artefacts
    if kind == "observed":
        entry.update(provenance="A named synthetic measurement.", observed_at="2026-08-08")
    elif kind == "assumption":
        entry["falsified_by"] = "A synthetic observation disproves it."
    elif kind == "estimate":
        entry["method"] = "A documented synthetic method."
    else:
        entry["resolved_by"] = "Run a synthetic observation."
    return entry


def _validate(
    tmp_path: Path,
    entries: list[dict[str, object]],
) -> tuple[Path, object]:
    workspace = tmp_path / "case"
    workspace.mkdir()
    (workspace / "evidence").mkdir()
    (workspace / "case.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "case": {"id": "artefacts", "title": "Synthetic artefacts"},
                "evidence": entries,
            },
            sort_keys=False,
        )
    )
    return workspace, validate_workspace(workspace)


def _typed_dossier(*entries: ObservedEvidence | AssumptionEvidence) -> Dossier:
    return Dossier(
        schema_version=1,
        case=CaseIdentity("artefacts", "Synthetic artefacts"),
        evidence=entries,
    )


def _observed(
    identifier: str,
    *references: EvidenceArtefactReference,
) -> ObservedEvidence:
    from datetime import date

    return ObservedEvidence(
        identifier,
        "Synthetic observed claim.",
        "Synthetic reviewer",
        (DecisionArea.PROBLEM_VALUE,),
        provenance="A named synthetic measurement.",
        observed_at=date(2026, 8, 8),
        artefacts=references,
    )


def test_all_evidence_kinds_validate_optional_immutable_artefacts_without_opening_them(
    tmp_path: Path,
) -> None:
    entries = [
        _entry(kind, kind, artefacts=[_reference(path=f"missing/{kind}.bin")])
        for kind in ("observed", "assumption", "estimate", "missing")
    ]

    _, result = _validate(tmp_path, entries)

    assert result.exit_code is ExitCode.SUCCESS
    assert result.dossier is not None
    assert [evidence.id for evidence in result.dossier.evidence] == [
        "observed",
        "assumption",
        "estimate",
        "missing",
    ]
    for evidence in result.dossier.evidence:
        assert evidence.artefacts == (
            EvidenceArtefactReference(
                "sample",
                EvidenceArtefactRoot.WORKSPACE,
                f"missing/{evidence.id}.bin",
            ),
        )
        with pytest.raises(FrozenInstanceError):
            evidence.artefacts[0].path = "changed"  # type: ignore[misc]
    assert result.dossier.evidence[0].provenance == "A named synthetic measurement."  # type: ignore[union-attr]


def test_duplicate_artefact_ids_fail_at_later_exact_path(tmp_path: Path) -> None:
    _, result = _validate(
        tmp_path,
        [
            _entry(
                "observed",
                "observed",
                artefacts=[_reference(), _reference(path="other.bin")],
            )
        ],
    )

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    diagnostic = result.diagnostics[0]
    assert (diagnostic.id, diagnostic.field, diagnostic.requirement) == (
        "duplicate-evidence-artefact-id",
        "$.evidence[0].artefacts[1].id",
        "FR-011",
    )
    assert "artefacts[0].id" in diagnostic.message


@pytest.mark.parametrize(
    ("path", "diagnostic_id"),
    [
        ("/absolute.bin", "evidence-artefact-path-absolute"),
        ("folder\\file.bin", "evidence-artefact-path-backslash"),
        ("folder//file.bin", "evidence-artefact-path-empty-segment"),
        ("folder/", "evidence-artefact-path-empty-segment"),
        ("./file.bin", "evidence-artefact-path-current-segment"),
        ("folder/../file.bin", "evidence-artefact-path-parent-segment"),
        ("folder/\x1bfile.bin", "evidence-artefact-path-control-character"),
        ("C:foo", "evidence-artefact-path-drive-prefix"),
        ("d:/file.bin", "evidence-artefact-path-drive-prefix"),
    ],
)
def test_unsafe_authored_path_shapes_fail_closed(
    tmp_path: Path,
    path: str,
    diagnostic_id: str,
) -> None:
    _, result = _validate(
        tmp_path,
        [_entry("observed", "observed", artefacts=[_reference(path=path)])],
    )

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    diagnostic = result.diagnostics[0]
    assert diagnostic.id == diagnostic_id
    assert diagnostic.field == "$.evidence[0].artefacts[0].path"
    assert diagnostic.requirement == "NFR-004"
    assert "\x1b" not in diagnostic.message


@pytest.mark.parametrize(
    "mutation",
    [
        {"id": "   "},
        {"root": "dossier-selected-root"},
        {"path": "   "},
        {"unexpected": "value"},
    ],
)
def test_artefact_schema_rejects_blank_unknown_and_unsupported_fields(
    tmp_path: Path,
    mutation: dict[str, str],
) -> None:
    reference = {**_reference(), **mutation}
    _, result = _validate(
        tmp_path,
        [_entry("observed", "observed", artefacts=[reference])],
    )

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].requirement == "FR-011"


def test_reference_fields_and_authored_order_participate_in_canonical_identity() -> None:
    first = EvidenceArtefactReference("z", EvidenceArtefactRoot.WORKSPACE, "z.bin")
    second = EvidenceArtefactReference("a", EvidenceArtefactRoot.EXTERNAL, "a.bin")
    evidence = _observed("observed", first, second)
    original = evidence_content_identity(evidence)

    mutations = (
        replace(evidence, artefacts=(replace(first, id="changed"), second)),
        replace(
            evidence,
            artefacts=(replace(first, root=EvidenceArtefactRoot.EXTERNAL), second),
        ),
        replace(evidence, artefacts=(replace(first, path="changed.bin"), second)),
        replace(evidence, artefacts=(second, first)),
    )

    assert all(evidence_content_identity(mutated) != original for mutated in mutations)
    content = canonical_evidence_bytes(evidence)
    assert b'"artefacts":[{"id":"z","path":"z.bin","root":"workspace"}' in content


def test_workspace_and_external_files_hash_in_canonical_pair_order(tmp_path: Path) -> None:
    workspace = tmp_path / "case"
    evidence_root = workspace / "evidence"
    evidence_root.mkdir(parents=True)
    external_root = tmp_path / "external"
    external_root.mkdir()
    (evidence_root / "z.bin").write_bytes(b"\x00workspace\xff")
    (external_root / "a.bin").write_bytes(b"")
    dossier = _typed_dossier(
        _observed(
            "z-evidence",
            EvidenceArtefactReference("z-file", EvidenceArtefactRoot.WORKSPACE, "z.bin"),
        ),
        _observed(
            "a-evidence",
            EvidenceArtefactReference("a-file", EvidenceArtefactRoot.EXTERNAL, "a.bin"),
        ),
    )

    first = evidence_artefact_identities(
        dossier,
        workspace=workspace,
        external_root=external_root,
    )
    os.utime(evidence_root / "z.bin", (1_700_000_000, 1_700_000_000))
    second = evidence_artefact_identities(
        dossier,
        workspace=workspace,
        external_root=external_root,
    )

    assert first == second
    assert [(item.evidence_id, item.artefact_id) for item in first] == [
        ("a-evidence", "a-file"),
        ("z-evidence", "z-file"),
    ]
    assert first[0] == EvidenceArtefactIdentity(
        evidence_id="a-evidence",
        artefact_id="a-file",
        root=EvidenceArtefactRoot.EXTERNAL,
        path="a.bin",
        byte_length=0,
        content_identity="sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )
    assert first[1].byte_length == 11
    assert first[1].content_identity == (
        "sha256:96fd79bc4960a294daa98fac5bbfd3fc6415332153d09994a7600d6c1da52ad4"
    )
    assert first[1].to_dict() == {
        "artefact_id": "z-file",
        "byte_length": 11,
        "content_identity": first[1].content_identity,
        "evidence_id": "z-evidence",
        "path": "z.bin",
        "root": "workspace",
    }


def test_changing_one_file_changes_only_its_identity(tmp_path: Path) -> None:
    workspace = tmp_path / "case"
    evidence_root = workspace / "evidence"
    evidence_root.mkdir(parents=True)
    first_path = evidence_root / "first.bin"
    second_path = evidence_root / "second.bin"
    first_path.write_bytes(b"first")
    second_path.write_bytes(b"second")
    dossier = _typed_dossier(
        _observed(
            "evidence",
            EvidenceArtefactReference("first", EvidenceArtefactRoot.WORKSPACE, "first.bin"),
            EvidenceArtefactReference("second", EvidenceArtefactRoot.WORKSPACE, "second.bin"),
        )
    )

    before = evidence_artefact_identities(dossier, workspace=workspace)
    first_path.write_bytes(b"changed")
    after = evidence_artefact_identities(dossier, workspace=workspace)

    assert before[0] != after[0]
    assert before[1] == after[1]
    assert dossier.evidence[0].artefacts[0].path == "first.bin"


def _assert_error(
    dossier: Dossier,
    workspace: Path,
    category: EvidenceArtefactFailure,
    *,
    external_root: Path | None = None,
) -> EvidenceArtefactError:
    with pytest.raises(EvidenceArtefactError) as captured:
        evidence_artefact_identities(
            dossier,
            workspace=workspace,
            external_root=external_root,
        )
    error = captured.value
    assert error.category is category
    assert error.field.startswith("$.evidence[")
    assert error.requirement in {"FR-011", "NFR-004"}
    assert not error.message.startswith("/")
    return error


@pytest.mark.parametrize(
    "path",
    [
        "/absolute.bin",
        "folder\\file.bin",
        "folder//file.bin",
        "./file.bin",
        "../file.bin",
        "C:foo",
        "D:/file.bin",
    ],
)
def test_hashing_api_rejects_unvalidated_unsafe_paths_before_root_access(
    tmp_path: Path,
    path: str,
) -> None:
    dossier = _typed_dossier(
        _observed(
            "evidence",
            EvidenceArtefactReference("file", EvidenceArtefactRoot.WORKSPACE, path),
        )
    )

    _assert_error(
        dossier,
        tmp_path / "missing-workspace",
        EvidenceArtefactFailure.REFERENCE_PATH_INVALID,
    )


def test_external_reference_requires_an_explicit_root(tmp_path: Path) -> None:
    dossier = _typed_dossier(
        _observed(
            "evidence",
            EvidenceArtefactReference("file", EvidenceArtefactRoot.EXTERNAL, "file.bin"),
        )
    )

    error = _assert_error(
        dossier,
        tmp_path / "unused-workspace",
        EvidenceArtefactFailure.EXTERNAL_ROOT_REQUIRED,
    )

    assert error.field.endswith(".root")
    assert error.to_dict()["category"] == "external-root-required"


@pytest.mark.parametrize(
    ("target_kind", "category"),
    [
        ("missing", EvidenceArtefactFailure.TARGET_MISSING),
        ("directory", EvidenceArtefactFailure.TARGET_NOT_REGULAR),
    ],
)
def test_missing_and_non_regular_targets_fail_closed(
    tmp_path: Path,
    target_kind: str,
    category: EvidenceArtefactFailure,
) -> None:
    workspace = tmp_path / "case"
    root = workspace / "evidence"
    root.mkdir(parents=True)
    if target_kind == "directory":
        (root / "target").mkdir()
    dossier = _typed_dossier(
        _observed(
            "evidence",
            EvidenceArtefactReference("target", EvidenceArtefactRoot.WORKSPACE, "target"),
        )
    )

    _assert_error(dossier, workspace, category)


@pytest.mark.skipif(os.name == "nt", reason="Windows may not permit unprivileged symlinks")
def test_workspace_and_target_symlink_escapes_fail_closed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "secret.bin"
    outside_file.write_bytes(b"outside")

    escaped_root_workspace = tmp_path / "root-escape"
    escaped_root_workspace.mkdir()
    (escaped_root_workspace / "evidence").symlink_to(outside, target_is_directory=True)
    target_escape_workspace = tmp_path / "target-escape"
    target_root = target_escape_workspace / "evidence"
    target_root.mkdir(parents=True)
    (target_root / "secret.bin").symlink_to(outside_file)
    dossier = _typed_dossier(
        _observed(
            "evidence",
            EvidenceArtefactReference("secret", EvidenceArtefactRoot.WORKSPACE, "secret.bin"),
        )
    )

    _assert_error(dossier, escaped_root_workspace, EvidenceArtefactFailure.EVIDENCE_ROOT_UNSAFE)
    _assert_error(dossier, target_escape_workspace, EvidenceArtefactFailure.TARGET_OUTSIDE_ROOT)


@pytest.mark.skipif(os.name == "nt", reason="Windows may not permit unprivileged symlinks")
def test_external_target_symlink_escape_fails_closed(tmp_path: Path) -> None:
    workspace = tmp_path / "case"
    external_root = tmp_path / "external"
    external_root.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    (external_root / "escape.bin").symlink_to(outside)
    dossier = _typed_dossier(
        _observed(
            "evidence",
            EvidenceArtefactReference("escape", EvidenceArtefactRoot.EXTERNAL, "escape.bin"),
        )
    )

    _assert_error(
        dossier,
        workspace,
        EvidenceArtefactFailure.TARGET_OUTSIDE_ROOT,
        external_root=external_root,
    )


def test_unavailable_workspace_and_external_roots_fail_without_leaking_paths(
    tmp_path: Path,
) -> None:
    workspace_dossier = _typed_dossier(
        _observed(
            "evidence",
            EvidenceArtefactReference("file", EvidenceArtefactRoot.WORKSPACE, "file.bin"),
        )
    )
    external_dossier = _typed_dossier(
        _observed(
            "evidence",
            EvidenceArtefactReference("file", EvidenceArtefactRoot.EXTERNAL, "file.bin"),
        )
    )

    workspace_error = _assert_error(
        workspace_dossier,
        tmp_path / "absent-workspace",
        EvidenceArtefactFailure.WORKSPACE_ROOT_UNAVAILABLE,
    )
    external_error = _assert_error(
        external_dossier,
        tmp_path / "unused-workspace",
        EvidenceArtefactFailure.EXTERNAL_ROOT_UNAVAILABLE,
        external_root=tmp_path / "absent-external",
    )

    assert str(tmp_path) not in str(workspace_error.to_dict())
    assert str(tmp_path) not in str(external_error.to_dict())


@pytest.mark.skipif(os.name == "nt", reason="Windows may not permit unprivileged symlinks")
def test_safe_internal_symlink_hashes_but_dangling_and_looping_links_fail(tmp_path: Path) -> None:
    workspace = tmp_path / "case"
    root = workspace / "evidence"
    root.mkdir(parents=True)
    (root / "real.bin").write_bytes(b"real")
    (root / "safe.bin").symlink_to("real.bin")
    safe_dossier = _typed_dossier(
        _observed(
            "evidence",
            EvidenceArtefactReference("safe", EvidenceArtefactRoot.WORKSPACE, "safe.bin"),
        )
    )
    safe = evidence_artefact_identities(safe_dossier, workspace=workspace)
    assert safe[0].byte_length == 4

    (root / "dangling.bin").symlink_to("absent.bin")
    dangling = replace(
        safe_dossier,
        evidence=(
            replace(
                safe_dossier.evidence[0],
                artefacts=(
                    EvidenceArtefactReference(
                        "dangling", EvidenceArtefactRoot.WORKSPACE, "dangling.bin"
                    ),
                ),
            ),
        ),
    )
    _assert_error(dangling, workspace, EvidenceArtefactFailure.TARGET_MISSING)

    (root / "loop.bin").symlink_to("loop.bin")
    looping = replace(
        safe_dossier,
        evidence=(
            replace(
                safe_dossier.evidence[0],
                artefacts=(
                    EvidenceArtefactReference("loop", EvidenceArtefactRoot.WORKSPACE, "loop.bin"),
                ),
            ),
        ),
    )
    _assert_error(looping, workspace, EvidenceArtefactFailure.TARGET_UNRESOLVABLE)


@pytest.mark.skipif(os.name == "nt", reason="Windows does not provide POSIX FIFOs")
def test_special_file_is_refused_without_opening_it(tmp_path: Path) -> None:
    workspace = tmp_path / "case"
    root = workspace / "evidence"
    root.mkdir(parents=True)
    os.mkfifo(root / "pipe")
    dossier = _typed_dossier(
        _observed(
            "evidence",
            EvidenceArtefactReference("pipe", EvidenceArtefactRoot.WORKSPACE, "pipe"),
        )
    )

    _assert_error(dossier, workspace, EvidenceArtefactFailure.TARGET_NOT_REGULAR)


def test_unreadable_file_uses_stable_error_without_host_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "private-case"
    root = workspace / "evidence"
    root.mkdir(parents=True)
    target = root / "file.bin"
    target.write_bytes(b"content")
    dossier = _typed_dossier(
        _observed(
            "evidence",
            EvidenceArtefactReference("file", EvidenceArtefactRoot.WORKSPACE, "file.bin"),
        )
    )
    original_open = Path.open

    def blocked_open(path: Path, *args: object, **kwargs: object):
        if path == target.resolve():
            raise PermissionError("private host detail\x1b")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", blocked_open)
    error = _assert_error(dossier, workspace, EvidenceArtefactFailure.TARGET_UNREADABLE)

    serialized = str(error.to_dict())
    assert str(tmp_path) not in serialized
    assert "\x1b" not in serialized
    assert "private host detail" not in serialized


def test_adapter_does_not_scan_or_use_runtime_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "case"
    root = workspace / "evidence"
    root.mkdir(parents=True)
    (root / "file.bin").write_bytes(b"content")
    dossier = _typed_dossier(
        _observed(
            "evidence",
            EvidenceArtefactReference("file", EvidenceArtefactRoot.WORKSPACE, "file.bin"),
        )
    )

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("artefact hashing crossed an unrelated runtime boundary")

    monkeypatch.setattr(Path, "iterdir", forbidden)
    monkeypatch.setattr(Path, "glob", forbidden)
    monkeypatch.setattr(Path, "rglob", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(os, "getenv", forbidden)
    monkeypatch.setattr(time, "time", forbidden)
    monkeypatch.setattr(random, "random", forbidden)
    monkeypatch.setattr(metadata, "version", forbidden)

    identities = evidence_artefact_identities(dossier, workspace=workspace)

    assert identities[0].byte_length == 7


def test_no_references_returns_empty_without_resolving_roots(tmp_path: Path) -> None:
    dossier = _typed_dossier(_observed("evidence"))

    assert (
        evidence_artefact_identities(
            dossier,
            workspace=tmp_path / "missing-workspace",
            external_root=tmp_path / "missing-external",
        )
        == ()
    )
