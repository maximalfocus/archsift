from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from archsift.authoring_results import (
    MATERIAL_SET_CONTENT_IDENTITY,
    PROTOCOL_VERSION,
    PROTOCOL_VERSION_1_0_0,
    REQUIRED_MILESTONES,
    REQUIRED_PASS_COUNT,
    REQUIRED_SESSION_COUNT,
    RESULT_SCHEMA_VERSION,
    validate_authoring_results,
)
from archsift.cli import main
from archsift.diagnostics import ExitCode


def _session(index: int, *, passed: bool = True) -> dict[str, Any]:
    return {
        "session_id": f"session-{index:02d}",
        "agent_product": f"agent-product-{index}",
        "agent_model": f"model-{index}",
        "harness_version": "1.0.0",
        "fresh_session": True,
        "environment": {
            "operating_system": "linux",
            "python_version": "3.11",
            "install_mode": "built-wheel",
        },
        "milestones": {
            name: "pass" if passed or name != "assess" else "fail" for name in REQUIRED_MILESTONES
        },
        "maintainer_intervention": False,
        "session_result": "pass" if passed else "fail",
        "failure_reason": None if passed else "Assessment milestone was not completed.",
    }


def _cohort(pass_count: int = 3) -> dict[str, Any]:
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "archsift_source_commit": "a" * 40,
        "material_set_content_identity": MATERIAL_SET_CONTENT_IDENTITY,
        "overall_result": "met" if pass_count >= REQUIRED_PASS_COUNT else "not-met",
        "sessions": [
            _session(index, passed=index <= pass_count)
            for index in range(1, REQUIRED_SESSION_COUNT + 1)
        ],
    }


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


@pytest.fixture(autouse=True)
def _authorised_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_packaged_schema_and_frozen_material_manifest_are_consistent() -> None:
    root = Path(__file__).parents[1]
    schema = json.loads(
        (root / "src/archsift/schemas/authoring-results-v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["schema_version"]["const"] == RESULT_SCHEMA_VERSION
    assert schema["properties"]["protocol_version"]["enum"] == [
        PROTOCOL_VERSION_1_0_0,
        PROTOCOL_VERSION,
    ]
    assert schema["properties"]["sessions"]["minItems"] == REQUIRED_SESSION_COUNT
    assert schema["properties"]["sessions"]["maxItems"] == REQUIRED_SESSION_COUNT
    milestones = schema["$defs"]["session"]["properties"]["milestones"]
    assert tuple(milestones["required"]) == REQUIRED_MILESTONES
    assert REQUIRED_PASS_COUNT == 3

    manifest = json.loads(
        (root / "authoring-material/manifest-v1.json").read_text(encoding="utf-8")
    )
    assert manifest["material_set_content_identity"] == MATERIAL_SET_CONTENT_IDENTITY
    identity_payload = dict(manifest)
    identity_payload.pop("material_set_content_identity")
    canonical = (
        json.dumps(identity_payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("ascii")
    assert f"sha256:{sha256(canonical).hexdigest()}" == MATERIAL_SET_CONTENT_IDENTITY
    assert len(manifest["files"]) == 3
    for item in manifest["files"]:
        content = (root / "authoring-material" / item["path"]).read_bytes()
        assert len(content) == item["byte_length"]
        assert f"sha256:{sha256(content).hexdigest()}" == item["content_identity"]


def test_three_of_four_distinct_sessions_meets_criterion(_authorised_root: Path) -> None:
    path = _authorised_root / "results.json"
    _write(path, _cohort())

    result = validate_authoring_results(Path("results.json"))

    assert result.exit_code is ExitCode.SUCCESS
    assert result.protocol_version == PROTOCOL_VERSION
    assert result.session_count == 4
    assert result.passed_session_count == 3
    assert result.criterion_met is True
    assert result.diagnostics == ()


def test_protocol_1_0_0_result_remains_supported(_authorised_root: Path) -> None:
    payload = _cohort()
    payload["protocol_version"] = PROTOCOL_VERSION_1_0_0
    path = _authorised_root / "results.json"
    _write(path, payload)

    result = validate_authoring_results(path)

    assert result.exit_code is ExitCode.SUCCESS
    assert result.protocol_version == PROTOCOL_VERSION_1_0_0


def test_two_of_four_sessions_is_criterion_not_met(_authorised_root: Path) -> None:
    path = _authorised_root / "results.json"
    _write(path, _cohort(2))

    result = validate_authoring_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.passed_session_count == 2
    assert [item.id for item in result.diagnostics] == ["authoring-threshold-not-met"]


@pytest.mark.parametrize(
    ("mutation", "diagnostic"),
    [
        ("duplicate-session", "authoring-session-id-duplicate"),
        ("duplicate-product", "authoring-agent-product-duplicate"),
        ("material-mismatch", "authoring-material-set-mismatch"),
        ("session-inconsistent", "authoring-session-inconsistent"),
        ("overall-inconsistent", "authoring-overall-inconsistent"),
    ],
)
def test_semantically_inconsistent_results_are_rejected(
    _authorised_root: Path, mutation: str, diagnostic: str
) -> None:
    payload = _cohort(4)
    if mutation == "duplicate-session":
        payload["sessions"][1]["session_id"] = "session-01"
    elif mutation == "duplicate-product":
        payload["sessions"][1]["agent_product"] = "agent-product-1"
    elif mutation == "material-mismatch":
        payload["material_set_content_identity"] = f"sha256:{'0' * 64}"
    elif mutation == "session-inconsistent":
        payload["sessions"][0]["session_result"] = "fail"
        payload["sessions"][0]["failure_reason"] = "Declared failure."
    else:
        payload["overall_result"] = "not-met"
    path = _authorised_root / "results.json"
    _write(path, payload)

    result = validate_authoring_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert diagnostic in [item.id for item in result.diagnostics]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("protocol_version", "2.0.0"),
    ],
)
def test_unsupported_versions_have_stable_exit(
    _authorised_root: Path, field: str, value: object
) -> None:
    payload = _cohort()
    payload[field] = value
    path = _authorised_root / "results.json"
    _write(path, payload)

    result = validate_authoring_results(path)

    assert result.exit_code is ExitCode.UNSUPPORTED_SCHEMA
    assert result.diagnostics[0].id == "authoring-results-version-unsupported"


@pytest.mark.parametrize(
    "content",
    [
        b"\xff",
        b'{"schema_version":1,"schema_version":1}',
        b'{"schema_version":NaN}',
        b"[",
    ],
)
def test_malformed_or_ambiguous_json_is_rejected(_authorised_root: Path, content: bytes) -> None:
    path = _authorised_root / "results.json"
    path.write_bytes(content)

    result = validate_authoring_results(path)

    assert result.exit_code is ExitCode.MALFORMED_INPUT
    assert result.diagnostics[0].id == "authoring-results-malformed"


def test_schema_rejects_extra_privacy_fields(_authorised_root: Path) -> None:
    payload = _cohort()
    payload["sessions"][0]["transcript"] = "private workspace content"
    path = _authorised_root / "results.json"
    _write(path, payload)

    result = validate_authoring_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "authoring-results-contract"
    assert result.diagnostics[0].field == "$.sessions[0]"


def test_safe_reader_rejects_outside_symlink_special_and_missing_paths(
    _authorised_root: Path,
) -> None:
    outside = _authorised_root.parent / f"{_authorised_root.name}-outside.json"
    _write(outside, _cohort())
    try:
        assert validate_authoring_results(outside).exit_code is ExitCode.UNSAFE_PATH
        assert validate_authoring_results(Path("../outside.json")).exit_code is ExitCode.UNSAFE_PATH
        missing = validate_authoring_results(Path("missing.json"))
        assert missing.exit_code is ExitCode.ARTEFACT_UNAVAILABLE

        directory = _authorised_root / "directory.json"
        directory.mkdir()
        assert validate_authoring_results(directory).exit_code is ExitCode.UNSAFE_PATH

        if hasattr(os, "symlink"):
            link = _authorised_root / "link.json"
            try:
                link.symlink_to(outside)
            except OSError:
                pass
            else:
                assert validate_authoring_results(link).exit_code is ExitCode.UNSAFE_PATH
    finally:
        outside.unlink()


def test_reader_accepts_read_only_file_and_is_deterministic(_authorised_root: Path) -> None:
    path = _authorised_root / "results.json"
    _write(path, _cohort())
    path.chmod(0o400)
    try:
        first = validate_authoring_results(path)
        second = validate_authoring_results(path)
    finally:
        path.chmod(0o600)

    assert first == second
    assert first.exit_code is ExitCode.SUCCESS


def test_oversized_result_is_rejected(_authorised_root: Path) -> None:
    path = _authorised_root / "results.json"
    path.write_bytes(b" " * (64 * 1024 + 1))

    result = validate_authoring_results(path)

    assert result.exit_code is ExitCode.MALFORMED_INPUT


def test_cli_human_json_quiet_and_failure_modes(
    _authorised_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _authorised_root / "results.json"
    _write(path, _cohort())

    assert main(["authoring-results", "results.json"]) == ExitCode.SUCCESS
    assert capsys.readouterr().out == (
        "Assisted-authoring criterion met: 3 of 4 sessions passed (protocol 1.0.1)\n"
    )

    assert main(["authoring-results", "results.json", "--json"]) == ExitCode.SUCCESS
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "criterion_met": True,
        "diagnostics": [],
        "exit_code": 0,
        "passed_session_count": 3,
        "protocol_version": "1.0.1",
        "session_count": 4,
        "status": "criterion-met",
    }

    _write(path, _cohort(2))
    assert main(["authoring-results", "results.json", "--json"]) == ExitCode.VALIDATION_FAILED
    failure = json.loads(capsys.readouterr().out)
    assert failure["status"] == "criterion-not-met"
    assert failure["criterion_met"] is False

    assert main(["authoring-results", "results.json", "--quiet"]) == ExitCode.VALIDATION_FAILED
    quiet = capsys.readouterr()
    assert quiet.out == ""
    assert quiet.err == ""


def test_public_protocol_freezes_authoring_contract() -> None:
    root = Path(__file__).parents[1]
    protocol = (root / "docs/authoring-check-v1.0.1.md").read_text(encoding="utf-8")
    words = " ".join(protocol.split())

    assert "protocol 1.0.1" in words
    assert "exactly four fresh sessions" in words
    assert "four distinct agent products" in words
    assert "at least three of the four sessions" in words
    assert "three cohorts have been run" in words
    assert "archsift authoring-results authoring-results.json" in protocol
    assert "transcripts" in protocol
    assert "ordinary user-controlled model transport" in words
    assert "outbound sockets blocked" in words


def test_committed_third_cohort_is_honest_criterion_not_met(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).parents[1]
    monkeypatch.chdir(root)

    result = validate_authoring_results(Path("authoring-results.json"))

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.protocol_version == PROTOCOL_VERSION
    assert result.session_count == 4
    assert result.passed_session_count == 0
    assert result.criterion_met is False
    assert [item.id for item in result.diagnostics] == ["authoring-threshold-not-met"]


def test_preserved_first_cohort_remains_valid_historical_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).parents[1]
    monkeypatch.chdir(root)

    result = validate_authoring_results(Path("authoring-results-1-criterion-not-met.json"))

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.protocol_version == PROTOCOL_VERSION
    assert result.session_count == 4
    assert result.passed_session_count == 1
    assert result.criterion_met is False
    assert [item.id for item in result.diagnostics] == ["authoring-threshold-not-met"]


def test_preserved_second_cohort_remains_valid_historical_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).parents[1]
    monkeypatch.chdir(root)

    result = validate_authoring_results(Path("authoring-results-2-criterion-not-met.json"))

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.protocol_version == PROTOCOL_VERSION
    assert result.session_count == 4
    assert result.passed_session_count == 1
    assert result.criterion_met is False
    assert [item.id for item in result.diagnostics] == ["authoring-threshold-not-met"]
