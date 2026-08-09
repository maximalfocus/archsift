from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from archsift.cli import main
from archsift.diagnostics import ExitCode
from archsift.usability import (
    PROTOCOL_VERSION,
    REQUIRED_MILESTONES,
    REQUIRED_PASS_COUNT,
    REQUIRED_SESSION_COUNT,
    RESULT_SCHEMA_VERSION,
    validate_usability_results,
)


def _session(index: int, *, passed: bool) -> dict[str, Any]:
    milestones = {
        "initialize": "pass",
        "complete": "pass",
        "validate": "pass",
        "assess": "pass" if passed else "fail",
    }
    return {
        "participant_id": f"participant-{index:02d}",
        "target_user_eligible": True,
        "independent": True,
        "environment": {
            "operating_system": "linux",
            "python_version": "3.11",
            "install_mode": "built-wheel",
        },
        "milestones": milestones,
        "maintainer_intervention": False,
        "session_result": "pass" if passed else "fail",
        "failure_reason": None if passed else "Assessment milestone was not completed.",
    }


def _cohort(pass_count: int) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "archsift_version_or_commit": "0.1.0",
        "overall_result": "met" if pass_count >= 4 else "not-met",
        "sessions": [_session(index, passed=index <= pass_count) for index in range(1, 6)],
    }


def _write_result(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def test_packaged_result_schema_is_valid() -> None:
    path = Path(__file__).parents[1] / "src/archsift/schemas/usability-results-v1.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["schema_version"]["const"] == RESULT_SCHEMA_VERSION
    assert schema["properties"]["protocol_version"]["const"] == PROTOCOL_VERSION
    assert schema["properties"]["archsift_version_or_commit"]["pattern"] == (
        r"^(?:[0-9]+\.[0-9]+\.[0-9]+(?:[A-Za-z0-9.+-]*)?|[0-9a-f]{40})$"
    )
    assert schema["properties"]["sessions"]["minItems"] == REQUIRED_SESSION_COUNT
    assert schema["properties"]["sessions"]["maxItems"] == REQUIRED_SESSION_COUNT
    milestones = schema["$defs"]["session"]["properties"]["milestones"]
    assert tuple(milestones["required"]) == REQUIRED_MILESTONES
    assert REQUIRED_PASS_COUNT == 4


@pytest.mark.parametrize(
    "binding",
    ["0.1.0", "95f2a785cbad05a0bd7563e0ff319d53f0c01a7c"],
)
def test_tool_binding_accepts_package_version_or_full_commit(tmp_path: Path, binding: str) -> None:
    payload = _cohort(4)
    payload["archsift_version_or_commit"] = binding
    path = tmp_path / "results.json"
    _write_result(path, payload)

    result = validate_usability_results(path)

    assert result.exit_code is ExitCode.SUCCESS
    assert result.criterion_met is True


@pytest.mark.parametrize(
    "binding",
    [
        "95f2a78",
        "a" * 39,
        "a" * 41,
        "A" * 40,
        "g" * 40,
    ],
)
def test_tool_binding_rejects_inexact_commit_values(tmp_path: Path, binding: str) -> None:
    payload = _cohort(4)
    payload["archsift_version_or_commit"] = binding
    path = tmp_path / "results.json"
    _write_result(path, payload)

    result = validate_usability_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.criterion_met is False
    assert result.session_count == 0
    assert result.passed_session_count == 0
    assert result.diagnostics[0].id == "usability-results-contract"
    assert result.diagnostics[0].field == "$.archsift_version_or_commit"


def test_invalid_tool_binding_fails_in_all_cli_modes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = _cohort(4)
    payload["archsift_version_or_commit"] = "95f2a78"
    path = tmp_path / "results.json"
    _write_result(path, payload)

    assert main(["usability-results", str(path)]) == ExitCode.VALIDATION_FAILED
    human = capsys.readouterr()
    assert human.out == ""
    assert "usability-results-contract" in human.err
    assert "$.archsift_version_or_commit" in human.err
    assert "Usability criterion met" not in human.err

    assert main(["usability-results", str(path), "--json"]) == ExitCode.VALIDATION_FAILED
    structured = capsys.readouterr()
    assert structured.err == ""
    output = json.loads(structured.out)
    assert output["status"] == "invalid"
    assert output["exit_code"] == int(ExitCode.VALIDATION_FAILED)
    assert output["criterion_met"] is False
    assert output["diagnostics"][0]["id"] == "usability-results-contract"

    assert main(["usability-results", str(path), "--quiet"]) == ExitCode.VALIDATION_FAILED
    quiet = capsys.readouterr()
    assert quiet.out == ""
    assert quiet.err == ""


def test_four_of_five_sessions_meets_criterion(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    _write_result(path, _cohort(4))

    result = validate_usability_results(path)

    assert result.exit_code is ExitCode.SUCCESS
    assert result.protocol_version == PROTOCOL_VERSION
    assert result.session_count == 5
    assert result.passed_session_count == 4
    assert result.criterion_met is True
    assert result.diagnostics == ()


def test_cli_reports_success_in_human_and_json_modes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "results.json"
    _write_result(path, _cohort(4))

    assert main(["usability-results", str(path)]) == ExitCode.SUCCESS
    assert capsys.readouterr().out == (
        "Usability criterion met: 4 of 5 sessions passed (protocol 1.0.0)\n"
    )

    assert main(["usability-results", str(path), "--json"]) == ExitCode.SUCCESS
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "criterion_met": True,
        "diagnostics": [],
        "exit_code": 0,
        "passed_session_count": 4,
        "protocol_version": "1.0.0",
        "session_count": 5,
        "status": "criterion-met",
    }


def test_three_of_five_sessions_rejects_the_cohort(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    _write_result(path, _cohort(3))

    result = validate_usability_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.passed_session_count == 3
    assert result.criterion_met is False
    assert [item.id for item in result.diagnostics] == ["usability-threshold-not-met"]


def test_duplicate_participant_id_is_rejected(tmp_path: Path) -> None:
    payload = _cohort(4)
    payload["sessions"][4]["participant_id"] = "participant-01"
    path = tmp_path / "results.json"
    _write_result(path, payload)

    result = validate_usability_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.criterion_met is False
    assert [item.id for item in result.diagnostics] == ["usability-participant-duplicate"]


def test_missing_milestone_is_rejected(tmp_path: Path) -> None:
    payload = _cohort(4)
    del payload["sessions"][0]["milestones"]["assess"]
    path = tmp_path / "results.json"
    _write_result(path, payload)

    result = validate_usability_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "usability-results-contract"
    assert result.diagnostics[0].field == "$.sessions[0].milestones"


def test_invalid_milestone_value_is_rejected(tmp_path: Path) -> None:
    payload = _cohort(4)
    payload["sessions"][0]["milestones"]["assess"] = "skipped"
    path = tmp_path / "results.json"
    _write_result(path, payload)

    result = validate_usability_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "usability-results-contract"
    assert result.diagnostics[0].field == "$.sessions[0].milestones.assess"


def test_intervention_cannot_be_declared_successful(tmp_path: Path) -> None:
    payload = _cohort(4)
    payload["sessions"][0]["maintainer_intervention"] = True
    path = tmp_path / "results.json"
    _write_result(path, payload)

    result = validate_usability_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.passed_session_count == 3
    assert [item.id for item in result.diagnostics] == [
        "usability-session-inconsistent",
        "usability-overall-inconsistent",
        "usability-threshold-not-met",
    ]


def test_overall_success_cannot_be_claimed_below_threshold(tmp_path: Path) -> None:
    payload = _cohort(3)
    payload["overall_result"] = "met"
    path = tmp_path / "results.json"
    _write_result(path, payload)

    result = validate_usability_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert [item.id for item in result.diagnostics] == [
        "usability-overall-inconsistent",
        "usability-threshold-not-met",
    ]


def test_result_requires_exactly_five_sessions(tmp_path: Path) -> None:
    payload = _cohort(4)
    payload["sessions"].pop()
    path = tmp_path / "results.json"
    _write_result(path, payload)

    result = validate_usability_results(path)

    assert result.exit_code is ExitCode.VALIDATION_FAILED
    assert result.diagnostics[0].id == "usability-results-contract"


def test_protocol_version_mismatch_is_unsupported(tmp_path: Path) -> None:
    payload = _cohort(4)
    payload["protocol_version"] = "2.0.0"
    path = tmp_path / "results.json"
    _write_result(path, payload)

    result = validate_usability_results(path)

    assert result.exit_code is ExitCode.UNSUPPORTED_SCHEMA
    assert result.diagnostics[0].id == "usability-protocol-unsupported"


def test_strict_json_rejects_duplicate_object_key(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")

    result = validate_usability_results(path)

    assert result.exit_code is ExitCode.MALFORMED_INPUT
    assert result.diagnostics[0].id == "usability-results-malformed"


def test_quiet_failure_emits_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "results.json"
    _write_result(path, _cohort(3))

    assert main(["usability-results", str(path), "--quiet"]) == ExitCode.VALIDATION_FAILED
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""


def test_public_docs_freeze_protocol_and_exact_offline_command() -> None:
    root = Path(__file__).parents[1]
    protocol = (root / "docs/usability-check-v1.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    protocol_words = " ".join(protocol.split())

    assert "protocol 1.0.0" in protocol_words
    assert "exactly five independent sessions" in protocol_words
    assert "at least four of the five sessions" in protocol_words
    assert "initialize, complete, validate, and assess" in protocol_words
    assert "no participant sessions have been run" in protocol_words
    assert "full 40-character lowercase commit ID" in protocol_words
    assert "archsift usability-results usability-results.json" in protocol
    assert "archsift usability-results usability-results.json" in readme
    assert "docs/usability-check-v1.md" in readme
