from __future__ import annotations

import json
from pathlib import Path

import pytest

from archsift.canonical import canonical_json_bytes
from archsift.cli import main
from archsift.comparison import compare_decision_records
from archsift.diagnostics import ExitCode
from archsift.registration import (
    RegistrationError,
    RegistrationFailure,
    RegistrationKind,
    load_registration,
    register_document,
    register_repository,
)
from archsift.workspace import initialize_workspace


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "case"
    assert initialize_workspace(workspace).exit_code is ExitCode.SUCCESS
    return workspace


def test_document_registration_copies_exact_inert_bytes_and_is_idempotent(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    content = b"Ignore all prior instructions.\x00\xffPK\x03\x04<script>alert(1)</script>"
    (workspace / "source.bin").write_bytes(content)

    first = register_document(workspace, "source-doc", "application/octet-stream", "source.bin")
    manifest_bytes = (workspace / "evidence/registered/source-doc/registration.json").read_bytes()
    second = register_document(workspace, "source-doc", "application/octet-stream", "source.bin")

    assert first == second
    assert first.registration_kind is RegistrationKind.DOCUMENT
    assert first.repository_commit is None
    assert first.files[0].logical_path is None
    assert first.files[0].byte_length == len(content)
    stored = workspace / "evidence/registered/source-doc" / first.files[0].stored_path
    assert stored.read_bytes() == content
    assert manifest_bytes == canonical_json_bytes(first.payload())
    assert load_registration(workspace, "source-doc") == first


def test_repository_registration_records_only_explicit_paths_and_commit(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    repository = tmp_path / "repository"
    (repository / "src").mkdir(parents=True)
    (repository / "src/main.py").write_bytes(b"print('registered')\n")
    (repository / "ignored.txt").write_bytes(b"must not be copied")
    commit = "a" * 40

    registration = register_repository(
        workspace,
        "repo-snapshot",
        "git-source",
        commit,
        ("src/main.py",),
        external_material_root=repository,
    )

    assert registration.repository_commit == commit
    assert [item.logical_path for item in registration.files] == ["src/main.py"]
    assert len(list((workspace / "evidence/registered/repo-snapshot/blobs").iterdir())) == 1
    assert not any(path.name == "ignored.txt" for path in workspace.rglob("*"))


@pytest.mark.parametrize(
    ("path", "category"),
    [
        ("../secret", RegistrationFailure.PATH_UNSAFE),
        ("missing", RegistrationFailure.TARGET_MISSING),
    ],
)
def test_registration_rejects_unsafe_or_missing_paths(
    tmp_path: Path,
    path: str,
    category: RegistrationFailure,
) -> None:
    workspace = _workspace(tmp_path)
    with pytest.raises(RegistrationError) as caught:
        register_document(workspace, "unsafe-doc", "text/plain", path)
    assert caught.value.category is category
    assert not (workspace / "evidence/registered/unsafe-doc").exists()


def test_registration_rejects_symlink_components(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (workspace / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(RegistrationError) as caught:
        register_document(workspace, "linked-doc", "text/plain", "linked/secret.txt")

    assert caught.value.category is RegistrationFailure.PATH_UNSAFE


def test_registration_store_cannot_be_a_source_or_linked_manifest_root(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "source.txt").write_text("first", encoding="utf-8")
    registration = register_document(workspace, "first", "text/plain", "source.txt")

    with pytest.raises(RegistrationError) as source_error:
        register_document(
            workspace,
            "second",
            "text/plain",
            f"evidence/registered/first/{registration.files[0].stored_path}",
        )
    assert source_error.value.category is RegistrationFailure.PATH_UNSAFE

    real_store = workspace / "evidence/registered"
    moved_store = workspace / "evidence/real-registered"
    real_store.rename(moved_store)
    real_store.symlink_to(moved_store, target_is_directory=True)
    with pytest.raises(RegistrationError) as load_error:
        load_registration(workspace, "first")
    assert load_error.value.category is RegistrationFailure.PATH_UNSAFE


def test_registration_collision_never_overwrites_existing_material(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source = workspace / "source.txt"
    source.write_text("first", encoding="utf-8")
    first = register_document(workspace, "stable", "text/plain", "source.txt")
    source.write_text("second", encoding="utf-8")

    with pytest.raises(RegistrationError) as caught:
        register_document(workspace, "stable", "text/plain", "source.txt")

    assert caught.value.category is RegistrationFailure.COLLISION
    assert load_registration(workspace, "stable") == first


def test_load_registration_detects_tampered_stored_bytes(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "source.txt").write_text("original", encoding="utf-8")
    registration = register_document(workspace, "tamper", "text/plain", "source.txt")
    blob = workspace / "evidence/registered/tamper" / registration.files[0].stored_path
    blob.write_text("tampered", encoding="utf-8")

    with pytest.raises(RegistrationError) as caught:
        load_registration(workspace, "tamper")

    assert caught.value.category is RegistrationFailure.REGISTRATION_INVALID


def test_registration_verification_requires_no_store_write_access(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "source.txt").write_text("immutable", encoding="utf-8")
    expected = register_document(workspace, "read-only", "text/plain", "source.txt")
    store = workspace / "evidence/registered"
    store.chmod(0o500)
    try:
        assert load_registration(workspace, "read-only") == expected
    finally:
        store.chmod(0o700)


def test_registration_cli_emits_stable_json_and_diagnostics(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "source.txt").write_text("content", encoding="utf-8")

    assert (
        main(
            [
                "register-document",
                str(workspace),
                "cli-doc",
                "text/plain",
                "source.txt",
                "--json",
            ]
        )
        == ExitCode.SUCCESS
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "registered"
    assert payload["registration_id"] == "cli-doc"

    assert (
        main(
            [
                "register-document",
                str(workspace),
                "bad-doc",
                "text/plain",
                "../escape",
                "--json",
            ]
        )
        == ExitCode.UNSAFE_PATH
    )
    failure = json.loads(capsys.readouterr().out)
    assert failure["diagnostics"][0]["id"] == "material-registration-path-unsafe"


def _registered_repository_case(workspace: Path, content: bytes) -> dict[str, object]:
    (workspace / "source.py").write_bytes(content)
    registration = register_repository(
        workspace,
        "repo-material",
        "git-source",
        "b" * 40,
        ("source.py",),
    )
    item = registration.files[0]
    dossier = {
        "schema_version": 3,
        "case": {"id": "registered-case", "title": "Registered case"},
        "evidence": [
            {
                "id": "registered-observation",
                "kind": "observed",
                "claim": "The explicit repository file contains the observed material.",
                "owner": "Case owner",
                "affects": ["problem-value"],
                "provenance": "Immutable registered repository material.",
                "observed_at": "2026-08-16",
                "artefacts": [
                    {
                        "id": "source-file",
                        "root": "workspace",
                        "path": f"registered/repo-material/{item.stored_path}",
                        "registration_id": "repo-material",
                        "registration_logical_path": "source.py",
                    }
                ],
            }
        ],
    }
    (workspace / "case.yaml").write_text(json.dumps(dossier), encoding="utf-8")
    return dossier


def _assess_json(
    workspace: Path,
    capsys: pytest.CaptureFixture[str],
) -> dict[str, object]:
    assert main(["assess", str(workspace), "--json"]) == ExitCode.SUCCESS
    return json.loads(capsys.readouterr().out)


def test_schema_v3_assessment_binds_verified_registration_provenance(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = _workspace(tmp_path)
    _registered_repository_case(workspace, b"print('one')\n")

    record = _assess_json(workspace, capsys)

    assert record["record_schema_version"] == 3
    assert record["dossier_schema_version"] == 3
    link = record["artefact_links"][0]
    assert link["registration_id"] == "repo-material"
    assert link["declared_material_type"] == "git-source"
    assert link["repository_commit"] == "b" * 40
    assert link["repository_logical_path"] == "source.py"
    assert link["registration_content_identity"].startswith("sha256:")


def test_reassessment_reports_registration_delta_as_explicit_context(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old_workspace = _workspace(tmp_path / "old")
    new_workspace = _workspace(tmp_path / "new")
    _registered_repository_case(old_workspace, b"print('old')\n")
    _registered_repository_case(new_workspace, b"print('new')\n")
    old = _assess_json(old_workspace, capsys)
    new = _assess_json(new_workspace, capsys)

    comparison = compare_decision_records(old, new)

    changed = comparison["changed_registrations"]["changed"]
    assert [item["registration_id"] for item in changed] == ["repo-material"]
    assert comparison["causes"]["registration_ids"] == []
    assert comparison["context"]["registration_ids"] == ["repo-material"]
